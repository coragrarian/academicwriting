"""Verify the complete site, portable links, semantic markup and output safety."""

import json
import shutil
import struct
import subprocess
import sys
import xml.etree.ElementTree as ET
from dataclasses import replace
from hashlib import sha256
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit

import pytest
from conftest import ROOT

from agrarian_builder import renderer
from agrarian_builder.parser import parse_document
from agrarian_builder.renderer import build_site

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


def test_complete_canonical_build(tmp_path, documents):
    output = tmp_path / "study"
    sources = {
        path: sha256(path.read_bytes()).hexdigest() for path in (ROOT / "exercises").glob("*.md")
    }
    build_site(documents, output)
    pages = {path: Page(path.read_text()) for path in output.rglob("*.html")}
    assert len(pages) == 46
    assert len([page for page in pages.values() if "answer-key" in page.scripts]) == 30
    home = (output / "index.html").read_text()
    assert (
        home.index("introduction/index.html")
        < home.index("methods/index.html")
        < home.index("results/index.html")
    )
    assert "site-data" not in pages[output / "index.html"].scripts
    for path, page in pages.items():
        source = path.read_text()
        not_found = path.relative_to(output) == Path("404.html")
        public_page = path.relative_to(output) in {
            Path("index.html"), Path("about/index.html"), Path("404.html"),
        }
        assert source.count("data-site-navigation") == (0 if public_page else 1)
        assert source.count("data-page-content") == 1
        about_links = [
            attrs for tag, attrs in page.elements
            if tag == "a" and attrs.get("class") == "about-link"
        ]
        assert len(about_links) == 1
        assert local_link_target(output, path, about_links[0]["href"]) == output / "about/index.html"
        assert "<!-- agrarian" not in source
        assert 'class="correct-answer"' not in source
        assert "[x]" not in source
        assert "@@" not in source
        nav_nodes = {
            attrs["data-nav-node"]: attrs
            for _, attrs in page.elements
            if "data-nav-node" in attrs
        }
        if public_page:
            assert not nav_nodes
            assert not any("data-exercise-link" in attrs for _, attrs in page.elements)
        else:
            assert len(nav_nodes) == 13  # Three modules and ten subsections in the course.
            for document in documents:
                assert f"module:{document.slug}" in nav_nodes
                for section in document.sections:
                    assert f"section:{document.slug}:{section.slug}" in nav_nodes
            assert sum(
                1 for _, attrs in page.elements if "data-exercise-link" in attrs
            ) >= 30
        assert sum(
            1 for _, attrs in page.elements if attrs.get("aria-current") == "page"
        ) == (0 if not_found else 1)
        data = {}
        if public_page:
            assert "site-data" not in page.scripts
            assert not any(tag == "script" for tag, _ in page.elements)
        else:
            data = json.loads(page.scripts["site-data"])
            assert data["course_sections"] == {
                document.slug: {
                    section.slug: [exercise.id for exercise in section.exercises]
                    for section in document.sections
                }
                for document in documents
            }
            assert page.title.endswith(" · Academic Writing for Agrarian Sciences")
        for node_id, attrs in nav_nodes.items():
            assert ("open" in attrs) == ("data-nav-current" in attrs)
            if node_id.startswith("module:"):
                assert ("open" in attrs) == (node_id == f"module:{data['module']}")
        for link in page.links:
            target = urlsplit(link)
            resolved = local_link_target(output, path, link)
            if resolved is None:
                continue
            assert resolved.is_file(), f"{path}: unresolved link {link}"
            if target.fragment:
                assert target.fragment in pages[resolved].ids, f"{path}: missing fragment {link}"
        assets = ("styles.css",) if public_page else ("styles.css", "exercises.js", "navigation.js")
        for asset in assets:
            assert any(link.endswith("assets/" + asset) for link in page.links)
    ids = set()
    for document in documents:
        assert (output / document.slug / "index.html").is_file()
        for section in document.sections:
            overview = pages[output / document.slug / section.slug / "index.html"]
            exercise_links = [
                attrs for tag, attrs in overview.regions["main"]
                if tag == "a" and "data-exercise-link" in attrs
            ]
            assert [
                (link["data-exercise-link"], link["data-module-id"], link["href"])
                for link in exercise_links
            ] == [
                (exercise.id, document.slug, f"{exercise.slug}/index.html")
                for exercise in section.exercises
            ]
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


def test_public_pages_exclude_course_runtime_and_traversal(tmp_path, documents):
    output = tmp_path / "site"
    build_site(documents, output)
    module = Page((output / "introduction/index.html").read_text())
    expected_data = json.loads(module.scripts["site-data"])
    assert {module: len(ids) for module, ids in expected_data["modules"].items()} == {
        "introduction": 14,
        "methods": 7,
        "results": 9,
    }
    assert sum(map(len, expected_data["modules"].values())) == 30
    assert expected_data["module"] == "introduction"
    for path in (Path("index.html"), Path("about/index.html"), Path("404.html")):
        page = Page((output / path).read_text())
        assert "site-data" not in page.scripts
        assert not any(tag == "script" for tag, _ in page.elements)
        assert "answer-key" not in page.scripts
        assert not any(
            attrs.get("rel") in {"prev", "next"} or "data-course-terminal" in attrs
            for _, attrs in page.elements
        )
        assert not any(attrs.get("id") == "exercise-form" for _, attrs in page.elements)
        assert not any(
            "course-panel" in attrs.get("class", "").split() or "data-site-navigation" in attrs
            or any(name.startswith("data-progress-") for name in attrs)
            for tag, attrs in page.elements
        )
        assert any("public-layout" in attrs.get("class", "").split() for _, attrs in page.elements)
        expected_title = "Academic Writing for Agrarian Sciences"
        if path.parent.name == "about":
            expected_title = "About · " + expected_title
        elif path.name == "404.html":
            expected_title = "Page not found · " + expected_title
        assert page.title == expected_title


def test_home_and_about_public_content(tmp_path, documents):
    output = tmp_path / "site"
    build_site(documents, output)
    home_source = (output / "index.html").read_text()
    home = Page(home_source)
    assert "course" in home.ids
    rows = [attrs for _, attrs in home.elements if attrs.get("class") == "contents-link"]
    assert len(rows) == 3
    start = rows[0]
    assert "project-start" not in home_source and "project-actions" not in home_source
    hero = home_source.split('<div class="page-head">', 1)[1].split("</div>", 1)[0]
    assert "<a " not in hero
    assert "eyebrow" not in hero and "Interactive self-study" not in hero
    assert '<ol class="course-contents" role="list">' in home_source
    assert "Course contents" in home_source and "Explore the course" not in home_source
    assert "Start here" not in home_source and ">Explore" not in home_source
    assert 'class="programme-' not in home_source
    assert "About the project" not in home_source
    first = min(documents, key=lambda document: (document.order, document.slug))
    assert (output / start["href"]).resolve() == output / first.slug / "index.html"
    assert any(attrs.get("href") == "about/index.html" for _, attrs in home.elements)
    assert "Start the course" not in home_source
    assert "About the research project" in home_source
    assert (
        "An interactive self-study resource for students and researchers writing "
        "research articles in the Agrarian Sciences."
    ) in hero
    assert [row["href"] for row in rows] == [
        "introduction/index.html", "methods/index.html", "results/index.html",
    ]
    for label in ("Introduction", "Methods", "Results"):
        assert f'<strong class="contents-title">{label}</strong>' in home_source
    for number, document in enumerate(sorted(documents, key=lambda doc: (doc.order, doc.slug)), 1):
        exercise_count = sum(len(section.exercises) for section in document.sections)
        assert f'>{number:02d}</span>' in home_source
        assert f"{len(document.sections)} subsections · {exercise_count} exercises" in home_source
        module_page = Page((output / document.slug / "index.html").read_text())
        assert ("h1", document.title) in module_page.headings
    public_pages = (
        (output / "index.html", home),
        (output / "about/index.html", Page((output / "about/index.html").read_text())),
    )
    for path, page in public_pages:
        header_links = [attrs for tag, attrs in page.regions["header"] if tag == "a"]
        course = next(attrs for attrs in header_links if attrs.get("class") == "course-link")
        target = urlsplit(course["href"])
        assert target.fragment == "course"
        assert (path.parent / target.path).resolve() == output / "index.html"
        assert any(attrs.get("class") == "about-link" for attrs in header_links)
    for detail in (
        "About this resource", "Research context", "Institutional context", "Funding and support",
        "APQ-01173-22", "FUNDEP", "Escrita acadêmica em língua inglesa nas ciências agrárias",
    ):
        assert detail not in home_source.split("<main", 1)[1].split("</main>", 1)[0]
    about_source = (output / "about/index.html").read_text()
    about = Page(about_source)
    assert '<h1>About Academic Writing for Agrarian Sciences</h1>' in about_source
    assert {
        "research-heading", "corpus-heading", "materials-heading",
        "team", "data-platform", "licensing-heading", "facts-heading",
    } <= about.ids
    assert [text for tag, text in about.headings if tag == "h2"] == [
        "The research project", "CorAgrarian", "Pedagogical materials", "Research team",
        "Data and platform", "Project information", "Software and licensing",
    ]
    for old_heading in (
        "About the resource", "Research behind the resource", "From research to learning",
        "Project at a glance", "Source and reuse",
    ):
        assert old_heading not in about_source
    assert 'href="https://github.com/coragrarian/academicwriting"' in about_source
    assert (
        "Escrita acadêmica em língua inglesa nas ciências agrárias: "
        "necessidades e insumos para aplicações pedagógicas"
    ) in about_source
    for fact in (
        "APQ-01173-22", "UFMG", "FUNDEP", "Executing institution", "Fund administrator",
        "FAPEMIG", "CAPES", "lexical and syntactic", "rhetorical functions",
        "specialised corpus of English-language journal articles", "classroom use",
        "independent online study", "undergraduate and postgraduate",
    ):
        assert fact in about_source
    assert "Original software is licensed under MIT" in about_source
    assert "original teaching content is licensed under CC BY-NC-SA 4.0" in about_source
    assert "third-party material retain their own rights" in about_source
    assert any(tag == "dl" for tag, _ in about.regions["main"])
    assert not any(tag == "img" for tag, _ in about.regions["main"])
    assert "contact" not in about.ids
    assert "mailto:" not in about_source and "Coming soon" not in about_source
    assert not any(
        attrs.get("class") == "nav-home" and "aria-current" in attrs
        for _, attrs in about.elements
    )
    assert any(
        attrs.get("class") == "about-link" and attrs.get("aria-current") == "page"
        for _, attrs in about.elements
    )


def test_public_team_uses_named_roles_and_anonymous_member_slots(tmp_path, documents):
    output = tmp_path / "site"
    build_site(documents, output)
    names = ["Deise Prina Dutra", "Gustavo Leal Teixeira", "Danilo Duarte Costa", "Jhonatan H. Lopes"]
    home_source = (output / "index.html").read_text()
    about_source = (output / "about/index.html").read_text()
    home, about = Page(home_source), Page(about_source)
    assert [text for tag, text in home.headings if tag == "h2"] == [
        "Course contents", "The research project",
    ]
    assert not any(name in home_source for name in names)
    assert not {"people-heading", "team", "data-platform"} & home.ids
    assert "person-portrait" not in home_source
    assert [text for tag, text in about.headings if tag == "h4"] == names[:3] + ["Research team member"] * 6
    assert [text for tag, text in about.headings if tag == "h3"] == [
        "Coordinators", "Members", "Jhonatan H. Lopes",
    ]
    assert about_source.count('class="person-role">Coordinator') == 3
    assert "Data processing and web development" in about_source
    for source in (home_source, about_source):
        assert "Data curation and web development" not in source
        assert 'class="person-affiliation"' not in source
        assert 'class="person-profile"' not in source
    assert "Details to be added" not in home_source
    assert about_source.count("Details to be added") == 6
    assert 'href="about/index.html#team"' not in home_source
    project = home_source.split('aria-labelledby="project-heading"', 1)[1].split("</section>", 1)[0]
    assert project.count("<p>") == 2 and "CorAgrarian" in project
    assert "pedagogical materials" in project and "self-study activities" in project
    assert "Jhonatan cleans and organises" not in about_source
    assert "person-contribution" not in about_source
    for page, count in ((home, 0), (about, 10)):
        portraits = [attrs for _, attrs in page.elements if attrs.get("class") == "person-portrait"]
        assert len(portraits) == count and all(attrs.get("aria-hidden") == "true" for attrs in portraits)


@pytest.mark.parametrize("path", ["index.html", "about/index.html"])
def test_people_component_supports_optional_portrait_and_metadata(tmp_path, documents, monkeypatch, path):
    assets = tmp_path / "static"
    shutil.copytree(ROOT / "static", assets)
    (assets / "people").mkdir()
    # A local PNG fixture exercises asset routing, without fetching a person's image.
    portrait = assets / "people/test-portrait.png"
    portrait.write_bytes((ROOT / "static/institutions/logo-ufmg-fale.png").read_bytes())
    person = replace(
        renderer.COORDINATORS[0], portrait="people/test-portrait.png",
        affiliation="Verified test affiliation", profile_url="https://example.org/profile",
        contribution="Verified test contribution",
    )
    monkeypatch.setattr(renderer, "STATIC", assets)
    monkeypatch.setattr(renderer, "COORDINATORS", (person, *renderer.COORDINATORS[1:]))
    output = tmp_path / "site"
    build_site(documents, output)
    page_path = output / path
    page = Page(page_path.read_text())
    images = [attrs for tag, attrs in page.elements if tag == "img" and attrs.get("alt") == person.name]
    if path == "index.html":
        assert not images
        for value in (person.name, person.affiliation, person.contribution, person.profile_url):
            assert value not in page_path.read_text()
        return
    assert len(images) == 1
    image = images[0]
    assert (page_path.parent / image["src"]).resolve().read_bytes() == portrait.read_bytes()
    assert image["width"] == image["height"] == "144"
    assert "Verified test affiliation" in page_path.read_text()
    assert "Verified test contribution" in page_path.read_text()
    assert any(attrs.get("class") == "person-portrait" and attrs.get("aria-hidden") == "true" for _, attrs in page.elements)
    assert any(attrs.get("href") == person.profile_url for _, attrs in page.elements)


def test_home_contents_follow_supplied_modules_and_preserve_unrecognised_titles(tmp_path, documents):
    # A reduced, reordered course catches canonical paths or counts baked into Home.
    introduction, methods, _ = documents
    modules = [
        replace(introduction, order=10, sections=introduction.sections[:2]),
        replace(methods, title="Methods and materials", order=0, sections=methods.sections[:1]),
    ]
    output = tmp_path / "site"
    build_site(modules, output)
    source = (output / "index.html").read_text()
    home = Page(source)
    start = next(attrs for _, attrs in home.elements if attrs.get("class") == "contents-link")
    assert start["href"] == "methods/index.html"
    rows = source.split('<ol class="course-contents" role="list">', 1)[1].split("</ol>", 1)[0]
    rows = rows.split("<li>")[1:]
    assert len(rows) == 2
    for number, (row, module) in enumerate(zip(rows, reversed(modules), strict=True), 1):
        assert f'>{number:02d}</span>' in row
        assert f'href="{module.slug}/index.html"' in row
        label = "Methods and materials" if number == 1 else "Introduction"
        assert f'<strong class="contents-title">{label}</strong>' in row
        assert row.count("<a ") == 1 and "<button" not in row
        assert row.index("<a ") < row.index("contents-title") < row.index("</a>")
        subsection_count = len(module.sections)
        subsection_label = "subsection" if subsection_count == 1 else "subsections"
        exercise_count = sum(len(section.exercises) for section in module.sections)
        assert f"{subsection_count} {subsection_label} · {exercise_count} exercises" in row


@pytest.mark.parametrize(("path", "title", "description"), [
    (
        "index.html", "Academic Writing for Agrarian Sciences",
        "Interactive self-study activities for academic writing in research articles in the Agrarian Sciences.",
    ),
    (
        "about/index.html", "About · Academic Writing for Agrarian Sciences",
        "Research, CorAgrarian, pedagogical materials, project information and the research team behind Academic Writing for Agrarian Sciences.",
    ),
    (
        "methods/index.html", "The Methods section · Academic Writing for Agrarian Sciences",
        "The Methods section: interactive academic-writing activities for Agrarian Sciences research articles.",
    ),
    (
        "methods/purpose-of-the-methods-section/index.html",
        "Purpose of the Methods section · Academic Writing for Agrarian Sciences",
        "Academic-writing activities on “Purpose of the Methods section” in the module “The Methods section”.",
    ),
    (
        "methods/purpose-of-the-methods-section/exercise-1/index.html",
        "Exercise 1: Purpose of the Methods section · Academic Writing for Agrarian Sciences",
        "Interactive exercise 1 on “Purpose of the Methods section” in the module “The Methods section”.",
    ),
])
def test_publication_metadata_for_each_page_type(tmp_path, documents, path, title, description):
    output = tmp_path / "site"
    build_site(documents, output)
    page = Page((output / path).read_text())
    assert page.title == title
    metadata = {}
    for tag, attrs in page.elements:
        if tag != "meta":
            continue
        key = attrs.get("name") or attrs.get("property")
        if key:
            assert key not in metadata, f"Duplicate metadata: {key}"
            metadata[key] = attrs["content"]
    canonical = PRODUCTION_URL + path.removesuffix("index.html")
    links = [attrs for tag, attrs in page.elements if tag == "link"]
    assert [link["href"] for link in links if link["rel"] == "canonical"] == [canonical]
    assert metadata["description"] == metadata["og:description"] == metadata["twitter:description"] == description
    assert metadata["og:title"] == metadata["twitter:title"] == title
    assert metadata["og:url"] == canonical
    assert metadata["og:type"] == "website"
    assert metadata["og:site_name"] == "Academic Writing for Agrarian Sciences"
    assert metadata["og:image"] == metadata["twitter:image"] == PRODUCTION_URL + "assets/social-preview.png"
    assert metadata["og:image:width"] == "1200" and metadata["og:image:height"] == "630"
    assert metadata["og:image:alt"] == metadata["twitter:image:alt"]
    assert "Academic Writing for Agrarian Sciences" in metadata["og:image:alt"]
    assert metadata["twitter:card"] == "summary_large_image"
    assert "twitter:site" not in metadata and "author" not in metadata
    assert "robots" not in metadata
    for rel, filename in (("icon", "favicon.svg"), ("apple-touch-icon", "apple-touch-icon.png")):
        icons = [link for link in links if link["rel"] == rel]
        assert len(icons) == 1
        assert (output / path).parent.joinpath(icons[0]["href"]).resolve() == output / "assets" / filename
    assert f'--accent: {metadata["theme-color"]};' in (output / "assets/styles.css").read_text()


def test_publication_assets_are_local_and_sized_for_their_purpose(tmp_path, documents):
    output = tmp_path / "site"
    build_site(documents, output)
    favicon = ET.parse(output / "assets/favicon.svg").getroot()
    assert favicon.attrib["viewBox"] == "0 0 64 64"
    assert favicon.find("{http://www.w3.org/2000/svg}text").text == "AW"
    for filename, dimensions, limit in (
        ("social-preview.png", (1200, 630), 200_000),
        ("apple-touch-icon.png", (180, 180), 20_000),
    ):
        data = (output / "assets" / filename).read_bytes()
        assert data[:8] == b"\x89PNG\r\n\x1a\n"
        assert struct.unpack(">II", data[16:24]) == dimensions
        assert len(data) < limit
    assert not (output / "tools").exists()
    assert not list(output.rglob("*.webmanifest"))


def test_not_found_is_a_public_fallback_with_safe_recovery_links(tmp_path, documents):
    output = tmp_path / "site"
    build_site(documents, output)
    path = output / "404.html"
    page = Page(path.read_text())
    assert page.headings == [("h1", "Page not found")]
    assert "The page you requested does not exist or may have moved." in path.read_text()
    assert not page.scripts
    assert not any(tag == "script" or "course-panel" in attrs.get("class", "").split() for tag, attrs in page.elements)
    assert any(attrs.get("name") == "robots" and attrs.get("content") == "noindex" for _, attrs in page.elements)
    assert not any(attrs.get("rel") == "canonical" or attrs.get("property") == "og:url" for _, attrs in page.elements)
    assert not any(attrs.get("aria-current") == "page" for _, attrs in page.elements)
    actions = [attrs["href"] for tag, attrs in page.regions["main"] if tag == "a"]
    assert actions == [PRODUCTION_URL, PRODUCTION_URL + "#course"]
    # Fixed production paths also protect the shell at arbitrary missing depths.
    for tag, attrs in page.elements:
        if tag in {"img", "link"}:
            href = attrs.get("href") or attrs.get("src")
            assert href.startswith(PRODUCTION_URL + "assets/")
            assert local_link_target(output, path, href).is_file()


def test_sitemap_contains_exactly_the_normal_content_in_course_order(tmp_path, documents):
    output = tmp_path / "site"
    build_site(documents, output)
    root = ET.parse(output / "sitemap.xml").getroot()
    namespace = "{http://www.sitemaps.org/schemas/sitemap/0.9}"
    assert root.tag == namespace + "urlset"
    urls = [node.find(namespace + "loc").text for node in root]
    paths = ["", "about/"]
    for document in sorted(documents, key=lambda doc: (doc.order, doc.slug)):
        paths.append(f"{document.slug}/")
        for section in document.sections:
            paths.append(f"{document.slug}/{section.slug}/")
            paths.extend(f"{document.slug}/{section.slug}/{exercise.slug}/" for exercise in section.exercises)
    assert len(urls) == len(set(urls)) == 45
    assert urls == [PRODUCTION_URL + path for path in paths]
    for node in root:
        assert node.tag == namespace + "url"
        assert [child.tag for child in node] == [namespace + "loc"]
    assert not any("404" in url or "localhost" in url or "127.0.0.1" in url for url in urls)
    for url in urls:
        assert url.startswith(PRODUCTION_URL) and url.endswith("/")
        assert local_link_target(output, output / "index.html", url).is_file()
    assert not (output / "robots.txt").exists()


def test_sitemap_follows_a_reduced_course_without_adding_the_fallback(tmp_path, methods):
    output = tmp_path / "site"
    build_site(methods, output)
    urls = [node.text for node in ET.parse(output / "sitemap.xml").iter("{http://www.sitemaps.org/schemas/sitemap/0.9}loc")]
    assert len(urls) == 2 + 1 + len(methods.sections) + sum(len(section.exercises) for section in methods.sections)
    assert not any("introduction/" in url or "results/" in url or "404" in url for url in urls)


def test_global_footer_has_portable_institutional_and_utility_links(tmp_path, documents):
    output = tmp_path / "site"
    build_site(documents, output)
    destinations = {
        "logo-ufmg-fale.png": ("https://www.letras.ufmg.br/site/", "Faculdade de Letras da UFMG"),
        "logo-fapemig.png": ("https://fapemig.br/", "FAPEMIG"),
        "logo-capes.png": ("https://www.gov.br/capes/pt-br/", "CAPES"),
    }
    for path in output.rglob("*.html"):
        source = path.read_text()
        page = Page(source)
        assert sum(tag == "footer" for tag, _ in page.elements) == 1
        assert source.index("</main>") < source.index('<footer class="site-footer">')
        assert not any(tag == "img" and "institution-logo" in attrs.get("class", "").split() for tag, attrs in page.regions["main"])
        assert len(page.image_links) == len(destinations)
        assert sum(tag == "img" for tag, _ in page.regions["footer"]) == 3
        for image, link in page.image_links:
            href, name = destinations[Path(image["src"]).name]
            assert link["href"] == href
            assert "target" not in link
            assert image["alt"] == name
        utility_links = [attrs["href"] for tag, attrs in page.regions["footer"] if tag == "a"]
        assert len(utility_links) == 4
        assert set(utility_links) == {href for href, _ in destinations.values()} | {
            "https://github.com/coragrarian/academicwriting",
        }
        footer = source.split('<footer class="site-footer">', 1)[1].split("</footer>", 1)[0]
        for text in ("Developed at UFMG", "Supported by FAPEMIG and CAPES", "APQ-01173-22", "coragrarian/academicwriting"):
            assert text in footer
        for excluded in ("Source code", "FUNDEP", "Contact", "Escrita acadêmica", "licence"):
            assert excluded not in footer
        repository = next(
            attrs for tag, attrs in page.regions["footer"]
            if tag == "a" and attrs["href"] == "https://github.com/coragrarian/academicwriting"
        )
        assert repository["aria-label"] == "GitHub repository: coragrarian/academicwriting"
        icon = next(attrs for tag, attrs in page.regions["footer"] if tag == "svg")
        assert icon["aria-hidden"] == "true" and icon["focusable"] == "false"
        assert not any(tag == "figcaption" for tag, _ in page.elements)


@pytest.mark.parametrize("path", [
    "index.html", "about/index.html", "methods/index.html",
    "methods/purpose-of-the-methods-section/index.html",
    "methods/purpose-of-the-methods-section/exercise-1/index.html",
])
def test_institutional_images_are_portable_and_unmodified(tmp_path, documents, path):
    output = tmp_path / "site"
    build_site(documents, output)
    page_path = output / path
    page = Page(page_path.read_text())
    images = [attrs for tag, attrs in page.elements if tag == "img" and "institution-logo" in attrs.get("class", "").split()]
    assert {Path(attrs["src"]).name for attrs in images} == {
        "logo-ufmg-fale.png", "logo-fapemig.png", "logo-capes.png",
    }
    for attrs in images:
        assert attrs["alt"]
        image = (page_path.parent / attrs["src"]).resolve()
        assert image.is_relative_to(output) and image.is_file()
        source = ROOT / "static/institutions" / image.name
        source_bytes = source.read_bytes()
        assert image.read_bytes() == source_bytes
        # PNG's IHDR stores intrinsic width and height as big-endian integers.
        assert int(attrs["width"]) == int.from_bytes(source_bytes[16:20])
        assert int(attrs["height"]) == int.from_bytes(source_bytes[20:24])


def test_single_module_build_remains_available(tmp_path, methods):
    output = tmp_path / "site"
    build_site(methods, output)
    assert len(list(output.rglob("*.html"))) == 13
    assert (output / "about/index.html").is_file()
    last = methods.sections[-1].exercises[-1]
    path = output / methods.slug / methods.sections[-1].slug / last.slug / "index.html"
    page = Page(path.read_text())
    terminal = next(attrs for _, attrs in page.elements if "data-course-terminal" in attrs)
    assert (path.parent / terminal["href"]).resolve() == output / "index.html"
    assert not any(attrs.get("rel") == "next" for _, attrs in page.elements)


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


def test_whole_course_navigation_graph(tmp_path, documents):
    output = (tmp_path / "study").resolve()
    build_site(documents, output)
    assert [document.slug for document in documents] == ["introduction", "methods", "results"]
    sequence = course_sequence(documents)
    assert len(sequence) == 43  # Three modules, ten subsections, thirty exercises.
    assert Path("about/index.html") not in sequence
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
    assert len(list(output.rglob("*.html"))) == 6
    assert (output / "about/index.html").is_file()


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
    assert "Learning pages: 43" in result.stdout
    assert "Content pages: 45; HTML files including 404: 46" in result.stdout
    assert len(list((tmp_path / "site").rglob("*.html"))) == 46


def test_context_and_instructions_are_outside_cards(tmp_path, methods):
    build_site(methods, tmp_path / "site")
    exercise = methods.sections[1].exercises[1]
    source = (
        tmp_path / "site" / methods.slug / methods.sections[1].slug / exercise.slug / "index.html"
    ).read_text()
    card_start = source.index('<section class="exercise-item"')
    assert source.index("In these exercises,") < card_start
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
