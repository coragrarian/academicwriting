"""Check authoring semantics and validation independently of generated HTML."""

import re
from pathlib import Path

import pytest

from agrarian_builder.parser import SourceError, discover_documents, parse_document

MARK = '<mark class="correct-answer">{}</mark>'


def exercise(body):
    """Wrap a body in valid hierarchy so tests isolate exercise semantics.

    The fixed source path also makes author-facing diagnostics testable.
    """
    return (
        parse_document(
            "# Module\n\n## Section\n\n### Exercise 1\n\n" + body,
            "module",
            source_path="fixture.md",
        )
        .sections[0]
        .exercises[0]
    )


def mapping(label, text):
    return "- " + MARK.format(label) + " " + text + "\n"


def test_front_matter_is_authoritative():
    document = parse_document(
        """---
id: stable-id
title: Configured title
order: 3
---
# Heading

## Section

### Exercise 1

- [x] Yes
- [ ] No
""",
        "filename",
    )
    assert (document.slug, document.title, document.order) == ("stable-id", "Configured title", 3)
    assert not document.introduction_html
    assert document.sections[0].exercises[0].id.startswith("stable-id--")


def test_module_discovery_and_canonical_counts(documents):
    assert [document.slug for document in documents] == ["introduction", "methods", "results"]
    assert [document.order for document in documents] == [1, 2, 3]
    assert [len(document.sections) for document in documents] == [6, 2, 2]
    assert [
        sum(len(section.exercises) for section in document.sections) for document in documents
    ] == [14, 7, 9]
    ids = [
        item.id
        for document in documents
        for section in document.sections
        for item in section.exercises
    ]
    assert len(set(ids)) == 30


def test_discovery_orders_by_metadata_and_rejects_duplicate_ids(tmp_path):
    source = "# Module\n\n## Section\n\n### Exercise 1\n\n- [x] Yes\n"
    for filename, slug, order in [("a.md", "later", 2), ("z.md", "earlier", 1)]:
        (tmp_path / filename).write_text(
            f"---\nid: {slug}\ntitle: Module\norder: {order}\n---\n" + source
        )
    assert [document.slug for document in discover_documents(tmp_path)] == ["earlier", "later"]
    (tmp_path / "a.md").write_text((tmp_path / "z.md").read_text())
    with pytest.raises(
        SourceError, match=r"a.md.*duplicate module id.*z.md|z.md.*duplicate module id.*a.md"
    ):
        discover_documents(tmp_path)


def test_empty_discovery_fails(tmp_path):
    with pytest.raises(SourceError, match="no Markdown modules"):
        discover_documents(tmp_path)


def test_context_instructions_and_real_item_boundaries():
    parsed = exercise("""Ordinary exercise context.

> A contextual quotation.

**Instructions:** Choose an answer.

#### Item A

A prompt.

- [x] Yes
- [ ] No

#### Item B

- [ ] Yes
- [x] No
""")
    assert len(parsed.context) == 2
    assert len(parsed.instructions) == 1
    assert parsed.instructions[0].html == "Choose an answer."
    assert parsed.direct_questions == []
    assert [item.title for item in parsed.items] == ["Item A", "Item B"]
    assert [len(item.questions) for item in parsed.items] == [1, 1]
    assert all(
        "Ordinary exercise context" not in block.html
        for item in parsed.items
        for block in item.blocks
    )


def test_exercise_without_item_headings_has_no_anonymous_item():
    parsed = exercise("**Instructions:** Choose.\n\n- [x] Yes\n- [ ] No\n")
    assert not parsed.items
    assert len(parsed.direct_questions) == 1
    assert len(parsed.instructions) == 1


def test_document_hierarchy_and_repeated_exercise_numbers(methods):
    assert [len(section.exercises) for section in methods.sections] == [3, 4]
    first, second = [section.exercises[0] for section in methods.sections]
    assert first.title == second.title == "Exercise 1"
    assert first.slug == second.slug == "exercise-1"
    assert first.id == "methods--purpose-of-the-methods-section--exercise-1"
    assert first.id != second.id


@pytest.mark.parametrize(
    ("options", "kind", "correct"),
    [
        ("- [ ] a) No\n- [x] b) Yes\n", "single-choice", [1]),
        ("- [x] Yes\n- [ ] No\n- [x] Also yes\n", "multi-select", [0, 2]),
    ],
)
def test_task_choice_types(options, kind, correct):
    question = exercise(options).questions[0]
    assert question.kind == kind
    assert question.correct_indices == correct
    assert "[x]" not in "".join(option.text_html for option in question.options)


@pytest.mark.parametrize("label", ["1", "A"])
@pytest.mark.parametrize("before", [True, False])
@pytest.mark.parametrize("bank_first", [True, False])
def test_bank_gaps_in_both_orders(label, before, bank_first):
    gap = f"[{label}] __________" if before else f"__________ [{label}]"
    passage = f"> Complete {gap} here.\n\n"
    bank = "**Answer bank:**\n\n" + mapping(f"[{label}]", "the answer") + "- distractor\n\n"
    parsed = exercise(bank + passage if bank_first else passage + bank)
    question = parsed.questions[0]
    assert question.kind == "gap"
    assert question.label == f"Gap {label}"
    assert [option.text_html for option in question.options] == ["the answer", "distractor"]
    assert question.correct_indices == [0]
    assert not parsed.items


def test_legacy_bank_heading_is_supported():
    assert (
        exercise("___ [1]\n\n#### Answer bank\n\n" + mapping("[1]", "yes")).questions[0].kind
        == "gap"
    )


def test_gaps_inside_numbered_and_bulleted_passages():
    parsed = exercise(
        "1. ___ [1]\n2. ___ [2]\n\n**Answer bank:**\n\n"
        + mapping("[2]", "two")
        + mapping("[1]", "one")
    )
    assert [question.correct_indices for question in parsed.questions] == [[1], [0]]
    assert "<ol>" in parsed.context[0].html


def test_bank_distractors_and_repeated_answers(documents):
    introduction, _, results = documents
    repeated = introduction.sections[-1].exercises[-1].questions
    assert repeated[2].correct_indices == repeated[3].correct_indices
    assert len(repeated[0].options) == 6
    comparison = results.sections[1].exercises[4]
    assert len(comparison.questions) == 7
    assert len(comparison.questions[0].options) == 8
    unused = [
        option for option in comparison.questions[0].options if option.text_html == "lowest"
    ]
    assert len(unused) == 1 and not unused[0].correct
    assert all("not used" not in option.text_html for option in comparison.questions[0].options)
    weather = results.sections[1].exercises[0]
    assert len(weather.questions[0].options) == 6  # was/were each appear twice in the bank


def test_inline_alternatives_in_blockquotes(methods):
    questions = methods.sections[1].exercises[0].questions
    assert len(questions) == 10
    assert all(question.kind == "inline-choice" for question in questions)
    assert [option.text_html for option in questions[5].options] == ["was consisted", "consisted"]
    assert questions[-1].options[1].text_html == "was asked"


@pytest.mark.parametrize(
    "body",
    [
        "conducted | " + MARK.format("was conducted"),
        MARK.format("was conducted") + " | conducted",
    ],
)
def test_inline_choice_orientation(body):
    question = exercise("> It " + body + " yesterday.").questions[0]
    assert question.options[question.correct_indices[0]].text_html == "was conducted"


def test_matching_is_independent_of_column_names():
    parsed = exercise(
        """| Beginning | Wording |
| --- | --- |
| A | First clause |
| B | Second clause |

**Endings:**

"""
        + mapping("[B]", "second ending")
        + mapping("A", "first ending")
    )
    assert [question.kind for question in parsed.questions] == ["matching", "matching"]
    assert [question.correct_indices for question in parsed.questions] == [[1], [0]]
    assert parsed.questions[0].prompt_html == "second ending"
    assert any(
        "Beginning" in block.html and "First clause" in block.html for block in parsed.context
    )


def test_canonical_matching_mapping(methods):
    parsed = methods.sections[0].exercises[2]
    assert [
        question.options[question.correct_indices[0]].text_html for question in parsed.questions
    ] == ["D", "A", "C", "B"]
    assert not parsed.items
    assert any("matching-sentences" in block.html for block in parsed.context)


def test_shared_passage_links_to_item_answers_without_treating_citations_as_gaps(documents):
    parsed = documents[0].sections[2].exercises[1]
    assert len(parsed.questions) == 5
    assert not parsed.direct_questions
    passage = "".join(block.html for block in parsed.context)
    assert "Reddy et al. [8]" in passage
    assert 'href="#item-a"' in passage
    assert 'href="#item-e"' in passage


def test_typed_gap_and_shared_answer_key_across_items(documents):
    introduction, _, results = documents
    parsed = introduction.sections[3].exercises[0]
    assert parsed.metadata.interaction == "typed-gap"
    assert [question.answer for question in parsed.questions] == [
        "has concentrated",
        "have been found",
        "have examined",
    ]
    transformed = results.sections[1].exercises[2]
    assert len(transformed.items) == 4
    assert [item.questions[0].answer for item in transformed.items] == [
        "significantly",
        "adversely",
        "clearly",
        "substantially",
    ]
    assert all(question.kind == "typed-gap" for question in transformed.questions)


def test_approved_introduction_content_is_self_contained(documents):
    introduction = documents[0]
    assert introduction.sections[-1].title == "Grammar and vocabulary in the Introduction section"
    assert introduction.sections[-1].slug == "grammar-and-vocabulary-in-the-introduction-section"
    first, second = introduction.sections[3].exercises[:2]
    assert "active or passive" in first.instructions[0].html
    assert "excerpt below" in second.instructions[0].html
    assert [question.source_label for question in first.questions] == ["1", "2", "3"]
    assert set(first.metadata.feedback.gaps) == {"1", "2", "3"}
    assert "singular" in first.metadata.feedback.gaps["1"]
    assert "have + been + past participle" in first.metadata.feedback.gaps["2"]
    assert "have + past participle" in first.metadata.feedback.gaps["3"]
    source = Path(introduction.source_path).read_text()
    passages = re.findall(r"^> Cotton is mainly cultivated.*$", source, re.MULTILINE)
    answers = {question.source_label: question.answer for question in first.questions}
    completed = re.sub(
        r"__________ \[(\d)\] \*\([^)]*\)\*",
        lambda match: answers[match.group(1)],
        passages[0],
    )
    assert completed == passages[1]
    assert second.questions[0].correct_indices == [2]


def test_gap_feedback_scopes_and_unknown_labels():
    parsed = exercise(
        """<!-- agrarian
interaction: typed-gap
feedback:
  gaps:
    "1": Shared explanation.
    "2": Second explanation.
-->

#### Item A

___ [1]

<!-- agrarian
feedback:
  gaps:
    "1": Local explanation.
-->

#### Item B

___ [2]

**Answer key:**

"""
        + mapping("[1]", "one")
        + mapping("[2]", "two")
    )
    assert parsed.metadata.feedback.gaps["1"] == "Shared explanation."
    assert parsed.items[0].metadata.feedback.gaps["1"] == "Local explanation."
    assert not parsed.items[1].metadata.feedback.gaps
    with pytest.raises(SourceError, match="unknown gap"):
        exercise(
            "___ [1]\n\n**Answer bank:**\n\n"
            + mapping("[1]", "one")
            + '\n<!-- agrarian\nfeedback:\n  gaps:\n    "2": Wrong label.\n-->\n'
        )


@pytest.mark.parametrize("entry", ['1: Unquoted.', '"1": ""', '"bad label": Text.'])
def test_gap_feedback_requires_valid_labels_and_text(entry):
    with pytest.raises(SourceError, match="quoted gap labels"):
        exercise(f"- [x] Yes\n\n<!-- agrarian\nfeedback:\n  gaps:\n    {entry}\n-->\n")


def test_worked_models_are_not_scored(documents):
    introduction, _, results = documents
    for parsed in [
        introduction.sections[3].exercises[2],
        introduction.sections[4].exercises[1],
        results.sections[1].exercises[5],
    ]:
        assert len(parsed.examples) == 1
        assert parsed.examples[0].questions[0].kind == "single-choice"
        assert len(parsed.questions) == 5
        assert not any(question.id.startswith("model-") for question in parsed.questions)
    assert not results.sections[1].exercises[2].examples[0].questions


def test_canonical_feedback_scopes(methods, documents):
    synonyms = methods.sections[1].exercises[1]
    assert synonyms.metadata.feedback.correct is None
    assert all(
        item.metadata.feedback.correct and item.metadata.feedback.incorrect
        for item in synonyms.items
    )
    shared = documents[2].sections[1].exercises[1]
    assert shared.metadata.feedback.correct
    assert all(item.metadata.feedback.correct is None for item in shared.items)
    options = methods.sections[0].exercises[0].metadata.feedback.options
    assert set(options) == {"a", "b", "c", "d"}
    assert "\n" not in options["b"]  # YAML folded scalar


def test_exercise_and_local_metadata():
    parsed = exercise("""<!-- agrarian
feedback:
  correct: Shared correct.
  incorrect: Shared review.
-->

#### Item A

- [ ] a) No
- [x] b) Yes

<!-- agrarian
feedback:
  options:
    a: Local option review.
    b: Local option correct.
  correct: Local correct.
-->

#### Item B

- [x] Yes
- [ ] No
""")
    assert parsed.metadata.feedback.incorrect == "Shared review."
    assert parsed.items[0].metadata.feedback.correct == "Local correct."
    assert parsed.items[0].metadata.feedback.options["a"] == "Local option review."
    assert not parsed.items[1].metadata.feedback.options
    assert "agrarian" not in "".join(block.html for block in parsed.blocks)


@pytest.mark.parametrize(
    ("body", "message"),
    [
        ("- [ ] No\n", "no correct answer"),
        ("- [x] Yes\n- ordinary\n", "mixed task"),
        ("___ [1] ___ [1]\n\n**Answer bank:**\n\n" + mapping("[1]", "yes"), "duplicate gap"),
        ("___ [1]\n\n**Answer bank:**\n\n" + mapping("[2]", "yes"), "no canonical answer"),
        (
            "___ [1]\n\n**Answer bank:**\n\n" + mapping("[1]", "yes") + mapping("[2]", "no"),
            "nonexistent gap",
        ),
        (
            "___ [1]\n\n**Answer bank:**\n\n" + mapping("[1]", "yes") + mapping("[1]", "yes"),
            "duplicate answer mapping",
        ),
        ("___ [1]\n\n**Answer bank:**\n\n- distractor\n", "no canonical mappings"),
        ("___ [1]\n\n**Answer bank:**\n\n" + mapping("[1]", ""), "empty answer-bank"),
        ("___ [1]\n\n**Answer key:**\n\n- answer\n", "invalid typed-gap answer key"),
        ("___ [1]\n\n**Answer key:**\n\n" + mapping("[1]", "yes"), "requires interaction"),
        (
            "___ [1]\n\n**Answer bank:**\n\n"
            + mapping("[1]", "yes")
            + "\n<!-- agrarian\ninteraction: typed-gap\n-->\n",
            "requires an Answer key",
        ),
        ("- [x] Yes\n\n<!-- agrarian\ninteraction: typed-gap\n-->\n", "no labelled gaps"),
        ("- [x] Yes\n\n" + MARK.format("stray"), "stray answer marker"),
        ("#### Other\n\n- [x] Yes\n", "unsupported item heading"),
        ("#### Item A\n\nContext only.\n", "no supported question"),
        ("#### Item A\n\n- [x] Yes\n\n#### Item A\n\n- [x] Yes\n", "duplicate item heading"),
        ("___ [A]\n\n#### Item B\n\n- [x] Yes\n", "no canonical answer"),
        ("Only context.\n", "no supported questions"),
        ("**Answer bank:**\n", "has no list"),
        ("**Answer bank:**\n\nNot a list.\n", "require a bullet list"),
        (
            "___ [1]\n\n**Answer bank:**\n\n"
            + mapping("[1]", "yes")
            + "\n**Answer bank:**\n\n"
            + mapping("[1]", "yes"),
            "multiple answer banks",
        ),
        ("- [x] Yes\n\n<!-- agrarian\nfeedback: [wrong\n-->\n", "malformed YAML"),
        ("- [x] Yes\n\n<!-- agrarian\nfeedback: text\n-->\n", "feedback requires"),
        ("- [x] Yes\n\n<!-- agrarian\nfeedback:\n  correct: 42\n-->\n", "must be nonempty text"),
        (
            "- [x] a) Yes\n\n<!-- agrarian\nfeedback:\n  options:\n    z: Unknown\n-->\n",
            "unknown option",
        ),
        (
            "- [x] Yes\n\n<!-- agrarian\nfeedback:\n  options:\n    a: Unlabelled\n-->\n",
            "one labelled choice",
        ),
        (
            "- [x] Yes\n\n<!-- agrarian\ninteraction: drag-and-drop\n-->\n",
            "unsupported interaction",
        ),
        ("- [x] Yes\n\n<!-- agrarian\nanalytics: true\n-->\n", "unsupported metadata"),
        (
            "- [x] Yes\n\n<!-- agrarian\nfeedback:\n  correct: one\n  correct: two\n-->\n",
            "duplicate YAML key",
        ),
        (
            "- [x] Yes\n\n<!-- agrarian\nfeedback: !!python/object:builtins.object {}\n-->\n",
            "malformed YAML",
        ),
    ],
)
def test_invalid_exercises_fail_with_author_context(body, message):
    with pytest.raises(SourceError, match=message) as error:
        exercise(body)
    assert "fixture.md, Section, Exercise 1" in str(error.value)


@pytest.mark.parametrize(
    ("entries", "mappings", "message"),
    [
        ("| A | First |", mapping("Z", "ending"), "unknown entry"),
        ("| A | First |\n| B | Second |", mapping("A", "ending"), "no mapping"),
        ("| A | First |\n| A | Second |", mapping("A", "ending"), "duplicate matching entry"),
        (
            "| A | First |",
            mapping("A", "ending") + mapping("A", "another"),
            "duplicate answer mapping",
        ),
    ],
)
def test_invalid_matching(entries, mappings, message):
    with pytest.raises(SourceError, match=message):
        exercise("| Label | Text |\n|---|---|\n" + entries + "\n\n**Purposes:**\n\n" + mappings)


@pytest.mark.parametrize(
    ("source", "message"),
    [
        ("---\nid: module\n", "unterminated front matter"),
        ("---\nid: module\n---\n# Module\n", "requires nonempty title"),
        ("---\nid: Module Space\ntitle: Title\n---\n# Module\n", "URL-safe slug"),
        (
            "---\nid: module\ntitle: Title\norder: false\n---\n# Module\n",
            "order must be an integer",
        ),
        ("# Module\n\n### Exercise 1\n\n- [x] Yes\n", "without a subsection"),
        ("# Module\n\n## Section\n\n#### Item A\n", "without an exercise"),
        (
            "# Module\n\n## Section\n\n### Exercise 1\n\n- [x] Yes\n\n### Exercise 1\n\n- [x] Yes\n",
            "duplicate exercise",
        ),
        ("# Module\n\n## Section\n\n## Section\n", "duplicate subsection"),
        ("# Module\n", "no level-two subsections"),
    ],
)
def test_document_validation(source, message):
    with pytest.raises(SourceError, match=message):
        parse_document(source, source_path="broken.md")
