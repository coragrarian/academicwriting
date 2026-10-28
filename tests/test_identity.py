"""Stable heading identities remain independent of presentation wording."""

import pytest

from agrarian_builder.parser import SourceError, parse_document


def annotation(identifier):
    return f"<!-- agrarian\nid: {identifier}\n-->\n"


def module(section_id="fixed-section", exercise_id="fixed-exercise"):
    return (
        "# Module\n\n## Original subsection\n\n"
        + annotation(section_id)
        + "\nSubsection prose.\n\n### Exercise 1\n\n"
        + annotation(exercise_id)
        + "\n- [x] Yes\n- [ ] No\n"
    )


def test_explicit_ids_override_heading_slugs_and_survive_title_changes():
    source = module()
    original = parse_document(source)
    updated = parse_document(
        source.replace("Original subsection", "Revised wording").replace(
            "Exercise 1", "Revised exercise wording"
        )
    )
    for document in (original, updated):
        section = document.sections[0]
        exercise = section.exercises[0]
        assert section.slug == "fixed-section"
        assert exercise.slug == "fixed-exercise"
        assert exercise.id == "module--fixed-section--fixed-exercise"
        assert "agrarian" not in section.introduction_html
        assert section.introduction_html == "<p>Subsection prose.</p>\n"
    assert original.sections[0].title != updated.sections[0].title
    assert original.sections[0].exercises[0].title != updated.sections[0].exercises[0].title


def test_id_comments_do_not_change_exercise_feedback_scope():
    source = module().replace(
        "- [x] Yes", "<!-- agrarian\nfeedback:\n  correct: Correct choice.\n-->\n\n- [x] Yes"
    )
    exercise = parse_document(source).sections[0].exercises[0]
    assert exercise.metadata.feedback.correct == "Correct choice."
    assert exercise.questions[0].correct_indices == [0]


def test_missing_ids_use_the_original_slug_and_persistence_contract():
    source = (
        module()
        .replace(annotation("fixed-section"), "")
        .replace(annotation("fixed-exercise"), "")
    )
    section = parse_document(source).sections[0]
    assert section.slug == "original-subsection"
    assert section.exercises[0].slug == "exercise-1"
    assert section.exercises[0].id == "module--original-subsection--exercise-1"


@pytest.mark.parametrize("identifier", ["a", "123", "part-2", "0-a-9"])
def test_conservative_url_safe_slugs_are_accepted(identifier):
    section = parse_document(module(f'"{identifier}"', f'"{identifier}"')).sections[0]
    assert section.slug == section.exercises[0].slug == identifier


@pytest.mark.parametrize("level", ["subsection", "exercise"])
@pytest.mark.parametrize(
    "identifier",
    [
        "",
        '""',
        "null",
        "false",
        "123",
        "[]",
        "{}",
        "Upper",
        "with space",
        "café",
        "under_score",
        "../escape",
        "-start",
        "end-",
        "two--hyphens",
    ],
)
def test_malformed_ids_report_the_source_and_heading_scope(level, identifier):
    source = (
        module(section_id=identifier) if level == "subsection" else module(exercise_id=identifier)
    )
    with pytest.raises(SourceError, match="nonempty lowercase URL-safe slug") as error:
        parse_document(source, source_path="invalid.md")
    assert "invalid.md, Original subsection" in str(error.value)
    if level == "exercise":
        assert "Exercise 1" in str(error.value)


@pytest.mark.parametrize(
    "source, message",
    [
        (module().replace("id: fixed-section", "id: [broken"), "malformed YAML"),
        (module().replace("id: fixed-section", "id: one\nid: two"), "duplicate YAML key"),
        (module().replace("id: fixed-section", "id: fixed-section\nfeedback: {}"), "only id"),
        (
            module().replace(
                "## Original subsection\n\n", "## Original subsection\n\nProse first.\n\n"
            ),
            "immediately follow",
        ),
        (
            module().replace(
                "## Original subsection\n\n",
                "## Original subsection\n\n<!-- ordinary comment -->\n\n",
            ),
            "immediately follow",
        ),
        (
            module().replace("# Module\n", "# Module\n\n" + annotation("module-id")),
            "immediately follow",
        ),
        (
            module().replace(
                "- [x] Yes", "#### Item A\n\n" + annotation("item-id") + "\n- [x] Yes"
            ),
            "immediately follow",
        ),
        (
            module().replace(
                annotation("fixed-section"),
                annotation("fixed-section") + "\n" + annotation("another-id"),
            ),
            "immediately follow",
        ),
    ],
)
def test_invalid_id_annotations_are_not_silently_ignored(source, message):
    with pytest.raises(SourceError, match=message) as error:
        parse_document(source, source_path="invalid.md")
    assert "invalid.md" in str(error.value)


@pytest.mark.parametrize("explicit", [False, True])
def test_subsection_ids_must_be_unique_in_the_module(explicit):
    following = (
        "\n## Different title\n\n" + annotation("fixed-section")
        if explicit
        else "\n## Fixed section\n"
    )
    with pytest.raises(SourceError, match="duplicate subsection.*fixed-section"):
        parse_document(module() + following)


@pytest.mark.parametrize("explicit", [False, True])
def test_exercise_ids_must_be_unique_in_the_subsection(explicit):
    source = module(exercise_id="exercise-2") + "\n### Exercise 2\n\n"
    if explicit:
        source += annotation("exercise-2") + "\n"
    with pytest.raises(SourceError, match="duplicate exercise id.*exercise-2"):
        parse_document(source + "- [x] Yes\n")


def test_exercise_ids_can_repeat_in_different_subsections():
    source = (
        module()
        + "\n## Another subsection\n\n### Exercise 1\n\n"
        + annotation("fixed-exercise")
        + "\n- [x] Yes\n"
    )
    document = parse_document(source)
    first, second = (section.exercises[0] for section in document.sections)
    assert first.slug == second.slug == "fixed-exercise"
    assert first.id != second.id


def test_id_examples_inside_fenced_code_are_not_metadata():
    source = module().replace(
        "Subsection prose.", "```markdown\n" + annotation("example-only") + "```\n"
    )
    section = parse_document(source).sections[0]
    assert section.slug == "fixed-section"
    assert "example-only" in section.introduction_html
