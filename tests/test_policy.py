"""Publication policy rules enforced over parsed course documents."""

import json
import shutil
from dataclasses import replace

import pytest
from conftest import SYNTHETIC_COURSE
from test_cli import run_cli

from agrarian_builder.parser import SourceError, parse_document
from agrarian_builder.paths import RESERVED_MODULE_IDS
from agrarian_builder.policy import check_publication
from agrarian_builder.renderer import build_site


def publishable_source(
    *,
    front_matter: str = "---\nid: sample\ntitle: Sample module\norder: 1\n---\n\n",
    heading: str = "# Sample module",
    section_heading: str = "## Sample subsection",
    section_id: str = "\n<!-- agrarian\nid: sample-subsection\n-->\n",
    exercise_heading: str = "### Exercise 1",
    exercise_id: str = "\n<!-- agrarian\nid: exercise-1\n-->\n",
    extra_exercises: str = "",
) -> str:
    return (
        f"{front_matter}{heading}\n\n"
        f"{section_heading}\n{section_id}\n"
        f"{exercise_heading}\n{exercise_id}\n"
        "- [x] Yes\n- [ ] No\n"
        f"{extra_exercises}"
    )


def test_publishable_module_and_free_exercise_titles_pass_policy():
    free_title = publishable_source(
        exercise_heading="### Identifying research gaps",
        exercise_id="\n<!-- agrarian\nid: identifying-gaps\n-->\n",
        extra_exercises=(
            "\n### Exercise 2\n\n<!-- agrarian\nid: exercise-2\n-->\n\n- [x] Yes\n- [ ] No\n"
        ),
    )
    check_publication([parse_document(free_title, source_path="exercises/sample.md")])


def test_publication_requires_front_matter_with_id_and_title():
    document = parse_document(
        publishable_source(front_matter=""),
        document_slug="sample",
        source_path="exercises/sample.md",
    )
    with pytest.raises(SourceError) as error:
        check_publication([document])
    assert str(error.value) == (
        "exercises/sample.md: publication requires front matter with id and title"
    )


def test_publication_requires_level_one_heading_to_equal_front_matter_title():
    document = parse_document(
        publishable_source(heading="# Different heading"),
        source_path="exercises/sample.md",
    )
    with pytest.raises(SourceError) as error:
        check_publication([document])
    assert str(error.value) == (
        "exercises/sample.md: level-one title 'Different heading' "
        "must equal front matter title 'Sample module'"
    )


def test_publication_requires_an_explicit_subsection_id():
    document = parse_document(
        publishable_source(section_id=""),
        source_path="exercises/sample.md",
    )
    with pytest.raises(SourceError) as error:
        check_publication([document])
    assert str(error.value) == (
        "exercises/sample.md, Sample subsection: publication requires an explicit subsection id"
    )


def test_publication_requires_an_explicit_exercise_id():
    document = parse_document(
        publishable_source(exercise_id=""),
        source_path="exercises/sample.md",
    )
    with pytest.raises(SourceError) as error:
        check_publication([document])
    assert str(error.value) == (
        "exercises/sample.md, Sample subsection, Exercise 1: "
        "publication requires an explicit exercise id"
    )


def test_publication_requires_exercise_number_to_match_its_position():
    document = parse_document(
        publishable_source(
            extra_exercises=(
                "\n### Exercise 3\n\n<!-- agrarian\nid: exercise-3\n-->\n\n- [x] Yes\n- [ ] No\n"
            )
        ),
        source_path="exercises/sample.md",
    )
    with pytest.raises(SourceError) as error:
        check_publication([document])
    assert str(error.value) == (
        "exercises/sample.md, Sample subsection, Exercise 3: "
        "exercise number must equal its position 2"
    )


@pytest.mark.parametrize("slug", sorted(RESERVED_MODULE_IDS))
def test_publication_rejects_reserved_module_ids(slug):
    document = parse_document(
        publishable_source(
            front_matter=f"---\nid: {slug}\ntitle: Sample module\norder: 1\n---\n\n"
        ),
        source_path="exercises/reserved.md",
    )
    with pytest.raises(SourceError) as error:
        check_publication([document])
    assert str(error.value) == (
        f"exercises/reserved.md: module id {slug!r} is reserved for the generated site"
    )


def test_renderer_guards_assets_using_shared_reserved_module_ids(tmp_path, synthetic_documents):
    output = tmp_path / "site"
    document = replace(synthetic_documents[0], slug="assets", source_path="assets.md")
    with pytest.raises(ValueError, match="assets.md.*'assets'.*reserved"):
        build_site(document, output)
    assert not output.exists()
    assert not (tmp_path / "site.building").exists()


def test_cli_applies_publication_policy_to_exercises_and_grammar_only_to_other_sources(tmp_path):
    shutil.copytree(SYNTHETIC_COURSE, tmp_path / "exercises")
    draft_only = "# Draft module\n\n## Draft subsection\n\n### Exercise 2\n\n- [x] Yes\n"
    single_file = tmp_path / "exercises/draft.md"
    single_file.write_text(draft_only, encoding="utf-8")

    # Explicit single-file source is checked for grammar only.
    validated = run_cli(tmp_path, "validate", "exercises/draft.md")
    assert validated.returncode == 0, validated.stderr
    inspected = run_cli(tmp_path, "inspect", "exercises/draft.md")
    assert inspected.returncode == 0, inspected.stderr
    assert inspected.stderr == ""
    assert json.loads(inspected.stdout)["modules"][0]["id"] == "draft"

    # Another directory is also checked for grammar only.
    other_dir = tmp_path / "sandbox"
    other_dir.mkdir()
    (other_dir / "draft.md").write_text(draft_only, encoding="utf-8")
    assert run_cli(tmp_path, "validate", "sandbox").returncode == 0
    other_inspect = run_cli(tmp_path, "inspect", "sandbox")
    assert other_inspect.returncode == 0
    assert json.loads(other_inspect.stdout)["modules"][0]["id"] == "draft"

    # Course-level commands against exercises/ enforce publication rules.
    for arguments in (
        ("validate",),
        ("validate", "exercises"),
        ("inspect",),
        ("inspect", "exercises"),
        ("inspect", "--write"),
        ("build",),
    ):
        result = run_cli(tmp_path, *arguments)
        assert result.returncode == 1, arguments
        assert "publication requires front matter with id and title" in result.stderr
        assert "exercises/draft.md" in result.stderr
        assert result.stdout == ""

    # Help text documents the split for validate and inspect.
    for command in ("validate", "inspect"):
        help_result = run_cli(tmp_path, command, "--help")
        assert help_result.returncode == 0
        assert "publication rules" in help_result.stdout.lower()
        assert "grammar only" in help_result.stdout.lower()
