"""Inspect generated artefacts independently of compiler helpers."""

from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit

PRODUCTION_URL = "https://coragrarian.github.io/academicwriting/"


class Page(HTMLParser):
    """Inspect rendered HTML independently of renderer implementation helpers.

    The collector rejects duplicate IDs and retains raw JSON scripts so build
    tests can check the browser data contract as well as page structure.
    """

    def __init__(self, source):
        super().__init__()
        self.elements = []
        self.ids = set()
        self.links = []
        self.image_links = []
        self.scripts = {}
        self.regions = {"header": [], "main": [], "footer": []}
        self.title = ""
        self.headings = []
        self._script = None
        self._link = None
        self._region = None
        self._title = False
        self._heading = None
        self._heading_text = ""
        self.feed(source)

    def handle_starttag(self, tag, attributes):
        attrs = dict(attributes)
        self.elements.append((tag, attrs))
        if tag in self.regions:
            self._region = tag
        if self._region:
            self.regions[self._region].append((tag, attrs))
        if tag == "title":
            self._title = True
        if tag in ("h1", "h2", "h3", "h4"):
            self._heading = tag
            self._heading_text = ""
        if tag == "a":
            self._link = attrs
        if tag == "img" and self._link:
            self.image_links.append((attrs, self._link))
        if attrs.get("id"):
            assert attrs["id"] not in self.ids, f"Duplicate HTML id {attrs['id']}"
            self.ids.add(attrs["id"])
        if tag == "script":
            self._script = attrs.get("id")
            if self._script:
                self.scripts[self._script] = ""
        for key in ("href", "src"):
            if key in attrs:
                self.links.append(attrs[key])

    def handle_endtag(self, tag):
        if tag == self._region:
            self._region = None
        if tag == "title":
            self._title = False
        if tag == self._heading:
            self.headings.append((tag, self._heading_text.strip()))
            self._heading = None
        if tag == "a":
            self._link = None
        if tag == "script":
            self._script = None

    def handle_data(self, data):
        if self._title:
            self.title += data
        if self._heading:
            self._heading_text += data
        if self._script:
            self.scripts[self._script] += data



def local_link_target(output: Path, page: Path, href: str) -> Path | None:
    """Map production URLs back to output, retaining relative-link checks."""
    target = urlsplit(href)
    if href.startswith(PRODUCTION_URL):
        resolved = output / unquote(urlsplit(href[len(PRODUCTION_URL):]).path)
    elif target.scheme or target.netloc:
        return None
    else:
        assert not target.path.startswith("/"), f"Unexpected host-root link: {href}"
        resolved = page.parent / unquote(target.path) if target.path else page
    resolved = resolved.resolve()
    assert resolved.is_relative_to(output.resolve())
    return resolved / "index.html" if resolved.is_dir() else resolved



def course_sequence(documents):
    """Derive expected reading order without using renderer navigation helpers.

    Home and About stay outside this list; Home terminates either direction.
    """
    sequence = []
    for document in documents:
        module = Path(document.slug)
        sequence.append(module / "index.html")
        for section in document.sections:
            subsection = module / section.slug
            sequence.append(subsection / "index.html")
            sequence.extend(
                subsection / exercise.slug / "index.html" for exercise in section.exercises
            )
    return sequence



def navigation_targets(output, path):
    """Resolve page-relative links, including the terminal return to Home.

    Returns
    -------
    tuple
        Previous path, forward path and whether the forward link terminates
        the course. Paths are relative to the generated site root.
    """
    page = Page((output / path).read_text())
    previous = [attrs for tag, attrs in page.elements if tag == "a" and attrs.get("rel") == "prev"]
    following = [
        attrs for tag, attrs in page.elements
        if tag == "a" and (attrs.get("rel") == "next" or "data-course-terminal" in attrs)
    ]
    assert len(previous) == len(following) == 1

    def resolve(attributes):
        return ((output / path).parent / attributes["href"]).resolve().relative_to(output)

    return resolve(previous[0]), resolve(following[0]), "data-course-terminal" in following[0]

