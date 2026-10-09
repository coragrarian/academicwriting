"""Small, independent source-to-site proofs for additive course authoring."""

import copy
import json
import re
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from dataclasses import asdict, replace
from pathlib import Path

import pytest
from conftest import ROOT, SYNTHETIC_COURSE
from jinja2 import TemplateNotFound
from site_support import PRODUCTION_URL, Page, course_sequence, navigation_targets

from agrarian_builder import renderer
from agrarian_builder.parser import discover_documents
from agrarian_builder.renderer import build_site


def file_bytes(directory):
    return {
        path.relative_to(directory).as_posix(): path.read_bytes()
        for path in directory.rglob("*") if path.is_file()
    }


def structure(output, documents):
    """Read structural results from HTML/JSON/XML rather than compiler helpers."""
    pages = {path.relative_to(output): Page(path.read_text()) for path in output.rglob("*.html")}
    home = pages[Path("index.html")]
    rows = [attrs["href"] for _, attrs in home.elements if attrs.get("class") == "contents-link"]
    counts = re.findall(r'<span class="contents-counts">([^<]+)</span>', (output / "index.html").read_text())
    first = pages[Path(rows[0])]
    data = json.loads(first.scripts["site-data"])
    answers = {}
    for page in pages.values():
        if "answer-key" in page.scripts:
            exercise_id = next(attrs["data-exercise-id"] for _, attrs in page.elements if "data-exercise-id" in attrs)
            answers[exercise_id] = json.loads(page.scripts["answer-key"])
    sequence = course_sequence(documents)
    return {
        "paths": set(pages),
        "home": dict(zip(rows, counts, strict=True)),
        "tree": {attrs["data-nav-node"] for _, attrs in first.elements if "data-nav-node" in attrs},
        "tree_exercises": {attrs["data-exercise-link"] for _, attrs in first.elements if "data-exercise-link" in attrs},
        "modules": data["modules"],
        "sections": data["course_sections"],
        "answers": answers,
        "sequence": sequence,
        "edges": {path: navigation_targets(output, path) for path in sequence},
        "sitemap": [node.text for node in ET.parse(output / "sitemap.xml").iter("{http://www.sitemaps.org/schemas/sitemap/0.9}loc")],
    }


def assert_shape(result, documents):
    """Compare independently authored entities with all structural projections."""
    sequence = course_sequence(documents)
    assert result["paths"] == set(sequence) | {Path("index.html"), Path("about/index.html"), Path("404.html")}
    assert result["home"] == {
        f"{doc.slug}/index.html": (
            f"{len(doc.sections)} subsection{'s' if len(doc.sections) != 1 else ''} · "
            f"{sum(len(section.exercises) for section in doc.sections)} "
            f"exercise{'s' if sum(len(section.exercises) for section in doc.sections) != 1 else ''}"
        )
        for doc in documents
    }
    assert result["tree"] == {
        f"module:{doc.slug}" for doc in documents
    } | {
        f"section:{doc.slug}:{section.slug}" for doc in documents for section in doc.sections
    }
    expected_sections = {
        doc.slug: {section.slug: [exercise.id for exercise in section.exercises] for section in doc.sections}
        for doc in documents
    }
    expected_modules = {
        doc.slug: [exercise.id for section in doc.sections for exercise in section.exercises]
        for doc in documents
    }
    assert result["sections"] == expected_sections
    assert result["modules"] == expected_modules
    assert result["tree_exercises"] == set(result["answers"]) == {identifier for ids in expected_modules.values() for identifier in ids}
    assert result["sitemap"] == [PRODUCTION_URL, PRODUCTION_URL + "about/"] + [
        PRODUCTION_URL + path.as_posix().removesuffix("index.html") for path in sequence
    ]
    for index, path in enumerate(sequence):
        previous, following, terminal = result["edges"][path]
        assert previous == (sequence[index - 1] if index else Path("index.html")), path
        assert following == (sequence[index + 1] if index + 1 < len(sequence) else Path("index.html")), path
        assert terminal == (index == len(sequence) - 1), path


def test_synthetic_authoring_contract_and_cli(tmp_path, synthetic_documents):
    assert [doc.slug for doc in synthetic_documents] == ["alpha", "beta", "gamma", "delta"]
    assert [Path(doc.source_path).name for doc in synthetic_documents] != sorted(path.name for path in SYNTHETIC_COURSE.glob("*.md"))
    alpha, beta, gamma, delta = synthetic_documents
    first, second = (section.exercises[0] for section in alpha.sections)
    assert first.slug == second.slug == "exercise-1" and first.id != second.id
    exercises = [exercise for doc in synthetic_documents for section in doc.sections for exercise in section.exercises]
    assert {question.kind for exercise in exercises for question in exercise.questions} == {
        "single-choice", "multi-select", "inline-choice", "gap", "typed-gap", "matching",
    }
    assert first.context and first.instructions and alpha.introduction_html
    assert first.examples[0].questions and not any(q.id.startswith("model-") for q in first.questions)
    assert not gamma.sections[0].exercises[0].examples[0].questions
    bank = beta.sections[0].exercises[0].questions
    assert [q.source_label for q in bank] == ["A", "B"]
    assert bank[0].correct_indices == bank[1].correct_indices == [0]
    assert len(bank[0].options) == 2 and bank[0].options[1].text_html == "unused label"
    matching = delta.sections[0].exercises[0].questions
    assert [q.id for q in matching] == ["context-q1", "context-q2"]
    assert [q.correct_indices for q in matching] == [[1], [0]]
    source = tmp_path / "source"
    shutil.copytree(SYNTHETIC_COURSE, source)
    (source / "nested").mkdir()
    (source / "00-last.md").rename(source / "nested/00-last.md")
    assert [doc.slug for doc in discover_documents(source)] == [doc.slug for doc in synthetic_documents]
    result = subprocess.run(
        [sys.executable, str(ROOT / "build.py"), str(source), "--output", str(tmp_path / "site")],
        cwd=tmp_path, capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "Modules: 4; subsections: 5; exercises: 6" in result.stdout
    assert "Learning pages: 15" in result.stdout
    assert_shape(structure(tmp_path / "site", synthetic_documents), synthetic_documents)


@pytest.mark.parametrize("entity", ["subsection", "exercise", "module"])
def test_additive_markdown_changes_only_expected_structure(tmp_path, entity):
    source = tmp_path / "source"
    shutil.copytree(SYNTHETIC_COURSE, source)
    fourth = source / "00-last.md"
    if entity == "module":
        fourth.unlink()
    output = tmp_path / "site"
    before_documents = discover_documents(source)
    build_site(before_documents, output)
    before = structure(output, before_documents)
    initial_bytes = file_bytes(output)
    expected = copy.deepcopy(before)
    if entity == "subsection":
        path = source / "30-first.md"
        path.write_text(path.read_text() + "\n\n## Additional labels\n\nA prose-only subsection.\n")
        added_paths = {Path("alpha/additional-labels/index.html")}
        expected["home"]["alpha/index.html"] = "3 subsections · 3 exercises"
        expected["tree"].add("section:alpha:additional-labels")
        expected["sections"]["alpha"]["additional-labels"] = []
    elif entity == "exercise":
        path = source / "20-third.md"
        path.write_text(path.read_text() + "\n\n### Exercise 2\n\n**Instructions:** Choose.\n\n- [ ] No\n- [x] Yes\n")
        added_paths = {Path("gamma/writing-labels/exercise-2/index.html")}
        identifier = "gamma--writing-labels--exercise-2"
        expected["home"]["gamma/index.html"] = "1 subsection · 2 exercises"
        expected["modules"]["gamma"].append(identifier)
        expected["sections"]["gamma"]["writing-labels"].append(identifier)
        expected["tree_exercises"].add(identifier)
    else:
        shutil.copyfile(SYNTHETIC_COURSE / fourth.name, fourth)
        section = "pairing-labels-with-their-corresponding-descriptions"
        identifier = f"delta--{section}--exercise-1"
        added_paths = {Path("delta/index.html"), Path(f"delta/{section}/index.html"), Path(f"delta/{section}/exercise-1/index.html")}
        expected["home"]["delta/index.html"] = "1 subsection · 1 exercise"
        expected["tree"] |= {"module:delta", f"section:delta:{section}"}
        expected["modules"]["delta"] = [identifier]
        expected["sections"]["delta"] = {section: [identifier]}
        expected["tree_exercises"].add(identifier)

    after_documents = discover_documents(source)
    build_site(after_documents, output)
    after = structure(output, after_documents)
    assert_shape(after, after_documents)
    assert after["paths"] - before["paths"] == added_paths
    assert not before["paths"] - after["paths"]
    for projection in ("home", "tree", "tree_exercises", "modules", "sections"):
        assert after[projection] == expected[projection], (entity, projection)
    assert {key: after["answers"][key] for key in before["answers"]} == before["answers"]
    if entity == "subsection":
        assert after["answers"] == before["answers"]
    else:
        assert set(after["answers"]) - set(before["answers"]) == {identifier}
        added = after["answers"][identifier]["questions"]
        assert {key: value["expected"] for key, value in added.items()} == (
            {"context-q1": [1]} if entity == "exercise" else {"context-q1": [1], "context-q2": [0]}
        )
    assert [path for path in after["sequence"] if path not in added_paths] == before["sequence"]
    added_urls = {PRODUCTION_URL + path.as_posix().removesuffix("index.html") for path in added_paths}
    assert [url for url in after["sitemap"] if url not in added_urls] == before["sitemap"]
    assert {name: content for name, content in file_bytes(output).items() if name.startswith("assets/")} == {
        name: content for name, content in initial_bytes.items() if name.startswith("assets/")
    }
    if entity == "module":
        fourth.unlink()
        restored_documents = discover_documents(source)
        build_site(restored_documents, output)
        assert structure(output, restored_documents) == before
        assert file_bytes(output) == initial_bytes


def test_rendering_preserves_semantic_model_and_sources(tmp_path, synthetic_documents):
    before_model = [asdict(doc) for doc in synthetic_documents]
    before_sources = {Path(doc.source_path): Path(doc.source_path).read_bytes() for doc in synthetic_documents}
    output = tmp_path / "site"
    build_site(list(reversed(synthetic_documents)), output)
    first = file_bytes(output)
    build_site(synthetic_documents, output)
    assert file_bytes(output) == first
    assert [asdict(doc) for doc in synthetic_documents] == before_model
    assert {path: path.read_bytes() for path in before_sources} == before_sources
    for doc in synthetic_documents:
        for section in doc.sections:
            for exercise in section.exercises:
                page = Page((output / doc.slug / section.slug / exercise.slug / "index.html").read_text())
                assert [attrs["data-question"] for _, attrs in page.elements if "data-question" in attrs] == [q.id for q in exercise.questions]
                payload = json.loads(page.scripts["answer-key"])
                assert {identifier: value["expected"] for identifier, value in payload["questions"].items()} == {
                    q.id: q.answer if q.kind == "typed-gap" else q.correct_indices for q in exercise.questions
                }
    typed = next(doc for doc in synthetic_documents if doc.slug == "gamma").sections[0].exercises[0]
    payload = renderer._answer_data(typed)
    assert payload["feedback"]["correct"] == "The labels agree."
    assert payload["groups"][0]["feedback"]["correct"] == "The first local label agrees."
    assert payload["questions"]["item-a-q1"]["gap_feedback"] == "This local explanation replaces the shared explanation."
    assert payload["questions"]["item-b-q1"]["gap_feedback"] == "Use the second label."


def test_render_failure_preserves_previous_output_and_marked_staging_can_retry(tmp_path, synthetic_documents, monkeypatch):
    output = tmp_path / "site"
    build_site(synthetic_documents, output)
    before = file_bytes(output)
    templates = tmp_path / "templates"
    shutil.copytree(ROOT / "templates", templates)
    (templates / "exercise.html").unlink()
    with monkeypatch.context() as patch:
        patch.setattr(renderer, "TEMPLATES", templates)
        with pytest.raises(TemplateNotFound, match="exercise.html"):
            build_site(synthetic_documents, output)
    assert file_bytes(output) == before
    staging = tmp_path / "site.building"
    assert (staging / ".agrarian-built").is_file()
    assert (staging / synthetic_documents[0].slug / "index.html").is_file()
    build_site(synthetic_documents, output)
    assert file_bytes(output) == before
    assert not staging.exists()


def test_reserved_module_path_cannot_replace_about_or_existing_output(tmp_path, synthetic_documents):
    output = tmp_path / "site"
    build_site(synthetic_documents, output)
    before = file_bytes(output)
    document = replace(synthetic_documents[0], slug="about", source_path="reserved.md")
    with pytest.raises(ValueError, match="reserved.md.*about.*public About"):
        build_site(document, output)
    assert file_bytes(output) == before
    assert not (tmp_path / "site.building").exists()
