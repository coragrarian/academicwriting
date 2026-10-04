"""Verify the complete site, portable links, semantic markup and output safety."""

import json
import subprocess
import sys
from hashlib import sha256
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit

import pytest
from conftest import ROOT

from agrarian_builder.parser import parse_document
from agrarian_builder.renderer import build_site


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
        self.scripts = {}
        self._script = None
        self.feed(source)

    def handle_starttag(self, tag, attributes):
        attrs = dict(attributes)
        self.elements.append((tag, attrs))
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
        if tag == "script":
            self._script = None

    def handle_data(self, data):
        if self._script:
            self.scripts[self._script] += data


def test_complete_canonical_build(tmp_path, documents):
    output = tmp_path / "study"
    sources = {
        path: sha256(path.read_bytes()).hexdigest() for path in (ROOT / "exercises").glob("*.md")
    }
    build_site(documents, output)
    pages = {path: Page(path.read_text()) for path in output.rglob("*.html")}
    assert len(pages) == 44
    assert len([page for page in pages.values() if "answer-key" in page.scripts]) == 30
    home = (output / "index.html").read_text()
    assert (
        home.index("introduction/index.html")
        < home.index("methods/index.html")
        < home.index("results/index.html")
    )
    assert json.loads(pages[output / "index.html"].scripts["site-data"])["module"] is None
    for path, page in pages.items():
        source = path.read_text()
        assert source.count("data-site-navigation") == 1
        assert source.count("data-page-content") == 1
        assert "<!-- agrarian" not in source
        assert 'class="correct-answer"' not in source
        assert "[x]" not in source
        assert "@@" not in source
        nav_nodes = {
            attrs["data-nav-node"]: attrs
            for _, attrs in page.elements
            if "data-nav-node" in attrs
        }
        assert len(nav_nodes) == 13  # Three modules and ten subsections on every page.
        for document in documents:
            assert f"module:{document.slug}" in nav_nodes
            for section in document.sections:
                assert f"section:{document.slug}:{section.slug}" in nav_nodes
        assert sum(
            1 for _, attrs in page.elements if "data-exercise-link" in attrs
        ) >= 30
        assert sum(
            1 for _, attrs in page.elements if attrs.get("aria-current") == "page"
        ) == 1
        data = json.loads(page.scripts["site-data"])
        assert data["course_sections"] == {
            document.slug: {
                section.slug: [exercise.id for exercise in section.exercises]
                for section in document.sections
            }
            for document in documents
        }
        for node_id, attrs in nav_nodes.items():
            assert ("open" in attrs) == ("data-nav-current" in attrs)
            if node_id.startswith("module:"):
                assert ("open" in attrs) == (node_id == f"module:{data['module']}")
        for link in page.links:
            target = urlsplit(link)
            if target.scheme or target.netloc:
                continue
            assert not target.path.startswith("/")
            resolved = (path.parent / unquote(target.path)).resolve() if target.path else path
            assert resolved.is_relative_to(output.resolve())
            assert resolved.is_file(), f"{path}: unresolved link {link}"
            if target.fragment:
                assert target.fragment in pages[resolved].ids, f"{path}: missing fragment {link}"
        for asset in ("styles.css", "exercises.js", "navigation.js"):
            assert any(link.endswith("assets/" + asset) for link in page.links)
    ids = set()
    for document in documents:
        assert (output / document.slug / "index.html").is_file()
        for section in document.sections:
            overview = pages[output / document.slug / section.slug / "index.html"]
            assert any(
                attrs.get("aria-current") == "page" and attrs.get("href") == "index.html"
                for _, attrs in overview.elements
            )
            for position, exercise in enumerate(section.exercises, 1):
                path = output / document.slug / section.slug / exercise.slug / "index.html"
                page = pages[path]
                source = path.read_text()
                heading = source.split('<div class="page-head exercise-head">', 1)[1].split(
                    '<form id="exercise-form"', 1
                )[0]
                if len(section.exercises) > 1:
                    assert (
                        f'<p class="eyebrow">{position} of {len(section.exercises)}</p>'
                        in heading
                    )
                else:
                    assert 'class="eyebrow"' not in heading
                assert f"Exercise {position} of {len(section.exercises)}" not in heading
                assert exercise.id not in ids
                ids.add(exercise.id)
                data = json.loads(page.scripts["site-data"])
                assert data["module"] == document.slug
                assert data["sections"][section.slug] == [entry.id for entry in section.exercises]
                assert data["modules"][document.slug] == [
                    entry.id for subsection in document.sections for entry in subsection.exercises
                ]
                answers = json.loads(page.scripts["answer-key"])
                assert set(answers["questions"]) == {
                    question.id for question in exercise.questions
                }
                assert sum(len(group["questions"]) for group in answers["groups"]) == len(
                    exercise.questions
                )
                assert (
                    sum(
                        1
                        for tag, attrs in page.elements
                        if tag == "button" and attrs.get("type") == "submit"
                    )
                    == 1
                )
                assert sum(1 for _, attrs in page.elements if "data-question" in attrs) == len(
                    exercise.questions
                )
                assert sum(
                    1 for _, attrs in page.elements if attrs.get("class") == "exercise-item"
                ) == len(exercise.items)
                for question in exercise.questions:
                    assert question.id + "-feedback" in page.ids
                    if question.kind == "typed-gap":
                        assert answers["questions"][question.id]["expected"] == question.answer
                if document.slug == "introduction" and section.slug == "indicating-a-research-gap" and position == 1:
                    assert [q["gap_feedback"] for q in answers["questions"].values()] == list(
                        exercise.metadata.feedback.gaps.values()
                    )
                for _, attrs in page.elements:
                    for description in attrs.get("aria-describedby", "").split():
                        assert description in page.ids
    assert len(ids) == 30
    assert {path: sha256(path.read_bytes()).hexdigest() for path in sources} == sources
    first_build = {
        path.relative_to(output): path.read_bytes()
        for path in output.rglob("*")
        if path.is_file()
    }
    build_site(documents, output)
    assert {
        path.relative_to(output): path.read_bytes()
        for path in output.rglob("*")
        if path.is_file()
    } == first_build


def test_single_module_build_remains_available(tmp_path, methods):
    output = tmp_path / "site"
    build_site(methods, output)
    assert len(list(output.rglob("*.html"))) == 11
    last = methods.sections[-1].exercises[-1]
    path = output / methods.slug / methods.sections[-1].slug / last.slug / "index.html"
    page = Page(path.read_text())
    terminal = next(attrs for _, attrs in page.elements if "data-course-terminal" in attrs)
    assert (path.parent / terminal["href"]).resolve() == output / "index.html"
    assert not any(attrs.get("rel") == "next" for _, attrs in page.elements)


def course_sequence(documents):
    """Derive expected reading order without using renderer navigation helpers.

    Home stays outside this list: reaching it terminates either direction.
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


def test_whole_course_navigation_graph(tmp_path, documents):
    output = (tmp_path / "study").resolve()
    build_site(documents, output)
    assert [document.slug for document in documents] == ["introduction", "methods", "results"]
    sequence = course_sequence(documents)
    assert len(sequence) == 43  # Three modules, ten subsections, thirty exercises.
    home = Path("index.html")
    targets = {path: navigation_targets(output, path) for path in sequence}
    for index, path in enumerate(sequence):
        previous, following, terminal = targets[path]
        assert previous == (sequence[index - 1] if index else home), path
        assert following == (sequence[index + 1] if index + 1 < len(sequence) else home), path
        assert previous != path and following != path, path
        assert terminal == (index == len(sequence) - 1), path

    visited = []
    current = sequence[0]
    while current != home:
        assert current not in visited, f"Course navigation revisited {current}"
        visited.append(current)
        current = targets[current][1]
    assert visited == sequence
    assert not any(
        attrs.get("rel") == "next" for _, attrs in Page((output / home).read_text()).elements
    )

    backwards = []
    current = sequence[-1]
    while current != home:
        assert current not in backwards, f"Previous navigation revisited {current}"
        backwards.append(current)
        current = targets[current][0]
    assert backwards == list(reversed(sequence))


@pytest.mark.parametrize("module_index", [0, 1])
def test_module_navigation_boundaries_are_inverses(tmp_path, documents, module_index):
    output = (tmp_path / "study").resolve()
    build_site(documents, output)
    current, following = documents[module_index : module_index + 2]
    final_section = current.sections[-1]
    final_exercise = final_section.exercises[-1]
    final_path = Path(current.slug) / final_section.slug / final_exercise.slug / "index.html"
    overview = Path(following.slug) / "index.html"
    assert navigation_targets(output, final_path)[1] == overview
    assert navigation_targets(output, overview)[0] == final_path
    assert "Next module" in (output / final_path).read_text()


def test_all_subsection_navigation_boundaries(tmp_path, documents):
    output = (tmp_path / "study").resolve()
    build_site(documents, output)
    for document in documents:
        for current, following in zip(document.sections, document.sections[1:]):
            final = Path(document.slug) / current.slug / current.exercises[-1].slug / "index.html"
            overview = Path(document.slug) / following.slug / "index.html"
            first = Path(document.slug) / following.slug / following.exercises[0].slug / "index.html"
            assert navigation_targets(output, final)[1] == overview
            assert navigation_targets(output, overview)[:2] == (final, first)
            assert navigation_targets(output, first)[0] == overview
            assert "Next subsection" in (output / final).read_text()


def test_final_course_destination_is_explicit(tmp_path, documents):
    output = (tmp_path / "study").resolve()
    build_site(documents, output)
    final = course_sequence(documents)[-1]
    _, following, terminal = navigation_targets(output, final)
    assert following == Path("index.html") and terminal
    source = (output / final).read_text()
    assert "Back to contents" in source
    assert not any(attrs.get("rel") == "next" for _, attrs in Page(source).elements)


def test_orientation_purpose_display_order_preserves_answer_keys(tmp_path, documents):
    output = tmp_path / "study"
    build_site(documents, output)
    path = output / "introduction/the-introduction-section-of-research-papers/exercise-1/index.html"
    page = Page(path.read_text())
    controls = [attrs["data-question"] for _, attrs in page.elements if "data-question" in attrs]
    assert controls == ["context-q4", "context-q2", "context-q1", "context-q3"]
    questions = json.loads(page.scripts["answer-key"])["questions"]
    assert {identifier: question["expected"] for identifier, question in questions.items()} == {
        "context-q1": [0],  # A: background
        "context-q2": [1],  # B: previous research
        "context-q3": [2],  # C: gap
        "context-q4": [3],  # D: objectives
    }
    assert [questions[identifier]["label"] for identifier in controls] == [
        "Match 1", "Match 2", "Match 3", "Match 4"
    ]


@pytest.mark.parametrize("interaction", [
    "- [x] Yes\n- [ ] No",
    (
        "| Label | Sentence |\n| --- | --- |\n| A | First |\n| B | Second |\n| C | Third |\n\n"
        "**Purposes:**\n\n- <mark class=\"correct-answer\">A</mark> One\n"
        "- <mark class=\"correct-answer\">B</mark> Two\n"
        "- <mark class=\"correct-answer\">C</mark> Three"
    ),
])
def test_presentation_order_does_not_restrict_alternative_module_sources(tmp_path, interaction):
    source = (
        "---\nid: introduction\ntitle: The Introduction section\norder: 1\n---\n\n"
        "# The Introduction section\n\n"
        "## The Introduction section of research papers\n\n"
        "### Exercise 1\n\n" + interaction
    )
    output = tmp_path / "site"
    build_site(parse_document(source), output)
    assert len(list(output.rglob("*.html"))) == 4


def test_slash_title_breaks_keep_text_and_html_escaping(tmp_path):
    document = parse_document(
        "# Module\n\n## Context/background\n\n### Exercise 1\n\n- [x] Yes\n- [ ] No"
    )
    document.sections[0].title = "Context/background & <script>title</script>"
    output = tmp_path / "site"
    build_site(document, output)
    for path in output.rglob("*.html"):
        assert "<script>title</script>" not in path.read_text()
    for path in [
        output / document.slug / "index.html",
        output / document.slug / document.sections[0].slug / "index.html",
    ]:
        rendered = path.read_text()
        assert "Context/<wbr>background" in rendered
        assert (
            "Context/background &amp; &lt;script&gt;title&lt;/script&gt;"
            in rendered.replace("<wbr>", "")
        )


def test_normal_cli_discovers_all_modules(tmp_path):
    result = subprocess.run(
        [sys.executable, str(ROOT / "build.py"), "--output", str(tmp_path / "site")],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "HTML pages: 44" in result.stdout
    assert len(list((tmp_path / "site").rglob("*.html"))) == 44


def test_context_and_instructions_are_outside_cards(tmp_path, methods):
    build_site(methods, tmp_path / "site")
    exercise = methods.sections[1].exercises[1]
    source = (
        tmp_path / "site" / methods.slug / methods.sections[1].slug / exercise.slug / "index.html"
    ).read_text()
    card_start = source.index('<section class="exercise-item"')
    assert source.index("In academic writing,") < card_start
    assert source.index('class="instructions"') < card_start
    assert source.count('class="exercise-item"') == 3
    assert "Exercise content" not in source


@pytest.mark.parametrize("directory", ["site", "site.building"])
def test_refuses_to_replace_unrecognised_directories(tmp_path, methods, directory):
    existing = tmp_path / directory
    existing.mkdir()
    (existing / "keep.txt").write_text("user data")
    with pytest.raises(ValueError, match="unrecognised"):
        build_site(methods, tmp_path / "site")
    assert (existing / "keep.txt").read_text() == "user data"


def test_duplicate_modules_do_not_touch_output(tmp_path, methods):
    output = tmp_path / "site"
    output.mkdir()
    (output / "keep.txt").write_text("unchanged")
    with pytest.raises(ValueError, match="unique module IDs"):
        build_site([methods, methods], output)
    assert (output / "keep.txt").read_text() == "unchanged"


def test_json_metadata_cannot_terminate_script(tmp_path):
    document = parse_document("""# Module

## Section

### Exercise 1

- [x] a) Yes
- [ ] b) No

<!-- agrarian
feedback:
  options:
    a: "</script><script>alert(1)</script>"
-->
""")
    build_site(document, tmp_path / "site")
    path = next((tmp_path / "site").glob("module/*/exercise-1/index.html"))
    page = Page(path.read_text())
    assert json.loads(page.scripts["answer-key"])["questions"]["context-q1"]["option_feedback"][
        "0"
    ].startswith("</script>")
    assert "<script>alert(1)</script>" not in path.read_text()
