"""Structural fingerprint and course manifest contracts."""

import json
import re

import pytest
from conftest import ROOT
from site_support import course_sequence

from agrarian_builder.fingerprint import exercise_fingerprint
from agrarian_builder.manifest import (
    course_manifest,
    format_manifest,
)
from agrarian_builder.parser import parse_document

CHOICE_SOURCE = """---
id: sample
title: Sample module
order: 1
---

# Sample module

Module prose.

## First subsection

Subsection prose.

### Exercise 1

Introductory prose.

**Instructions:** Select the appropriate option.

<!-- agrarian
feedback:
  correct: Overall correct feedback.
  incorrect: Overall incorrect feedback.
  options:
    a: Feedback for option a.
-->

- [x] a) First option
- [ ] b) Second option

#### Model

- [x] Model first
- [ ] Model second
"""

TYPED_GAP_SOURCE = """# Sample module

## First subsection

### Exercise 1

<!-- agrarian
interaction: typed-gap
feedback:
  correct: All typed gaps agree.
  gaps:
    "1": Gap one feedback.
    "2": Gap two feedback.
-->

Context before ___ [1] and ___ [2].

**Answer key:**

- <mark class="correct-answer">[1]</mark> expected one
- <mark class="correct-answer">[2]</mark> expected two
"""

MATCHING_SOURCE = """# Sample module

## First subsection

### Exercise 1

| Label | Statement |
| --- | --- |
| A | First sentence. |
| B | Second sentence. |

**Purposes:**

- <mark class="correct-answer">A</mark> Describe the background.
- <mark class="correct-answer">B</mark> State the objective.
"""


def first_exercise(source: str):
    return parse_document(source).sections[0].exercises[0]


def test_fingerprint_is_stable_hex_across_repeated_parses():
    first = exercise_fingerprint(first_exercise(CHOICE_SOURCE))
    second = exercise_fingerprint(first_exercise(CHOICE_SOURCE))
    assert first == second
    assert re.fullmatch(r"[0-9a-f]{16}", first)


@pytest.mark.parametrize(
    "transform",
    [
        lambda s: s.replace("title: Sample module", "title: Renamed module"),
        lambda s: s.replace("# Sample module", "# Renamed heading"),
        lambda s: s.replace("## First subsection", "## Renamed subsection"),
        lambda s: s.replace("### Exercise 1", "### Exercise 9"),
        lambda s: s.replace("order: 1", "order: 42"),
        lambda s: s.replace("Introductory prose.", "Revised introductory prose with *emphasis*."),
        lambda s: s.replace("Select the appropriate option.", "Choose one answer carefully."),
        lambda s: s.replace("Overall correct feedback.", "Updated correct explanation."),
        lambda s: s.replace("Feedback for option a.", "Updated option a explanation."),
        lambda s: s.replace(
            "- [x] a) First option\n- [ ] b) Second option",
            "- [ ] a) First option\n- [x] b) Second option",
        ),
        lambda s: s.replace(
            "- [x] Model first\n- [ ] Model second",
            "- [x] Model changed\n- [ ] Model extra\n- [ ] Model third",
        ),
    ],
)
def test_fingerprint_is_unchanged_by_titles_order_feedback_answer_keys_or_prose(transform):
    baseline = exercise_fingerprint(first_exercise(CHOICE_SOURCE))
    assert exercise_fingerprint(first_exercise(transform(CHOICE_SOURCE))) == baseline


def test_typed_gap_fingerprint_ignores_answer_key_and_feedback_changes():
    baseline = exercise_fingerprint(first_exercise(TYPED_GAP_SOURCE))
    changed_answers = TYPED_GAP_SOURCE.replace("expected one", "revised answer").replace(
        "Gap one feedback.", "Revised gap feedback."
    ).replace("Context before", "Updated prose before")
    assert exercise_fingerprint(first_exercise(changed_answers)) == baseline


@pytest.mark.parametrize(
    "transform",
    [
        lambda s: s.replace(
            "- [ ] b) Second option",
            "- [ ] b) Second option\n- [ ] c) Third option",
        ),
        lambda s: s.replace(
            "- [x] a) First option\n- [ ] b) Second option",
            "- [x] a) First option",
        ),
        lambda s: s.replace(
            "- [x] a) First option\n- [ ] b) Second option",
            "- [ ] b) Second option\n- [x] a) First option",
        ),
        lambda s: s.replace(
            "Introductory prose.",
            "Inline <mark class=\"correct-answer\">left</mark> | right response.",
        ),
        lambda s: s.replace(
            "- [x] a) First option\n- [ ] b) Second option",
            "- [x] a) First option\n- [x] b) Second option",
        ),
    ],
)
def test_fingerprint_changes_when_options_response_order_or_kind_change(transform):
    baseline = exercise_fingerprint(first_exercise(CHOICE_SOURCE))
    assert exercise_fingerprint(first_exercise(transform(CHOICE_SOURCE))) != baseline


def test_fingerprint_changes_when_matching_mapping_order_changes():
    baseline = exercise_fingerprint(first_exercise(MATCHING_SOURCE))
    reordered_mappings = MATCHING_SOURCE.replace(
        "- <mark class=\"correct-answer\">A</mark> Describe the background.\n"
        "- <mark class=\"correct-answer\">B</mark> State the objective.",
        "- <mark class=\"correct-answer\">B</mark> State the objective.\n"
        "- <mark class=\"correct-answer\">A</mark> Describe the background.",
    )
    unchanged_structure_key_swap = MATCHING_SOURCE.replace(
        "- <mark class=\"correct-answer\">A</mark> Describe the background.\n"
        "- <mark class=\"correct-answer\">B</mark> State the objective.",
        "- <mark class=\"correct-answer\">B</mark> Describe the background.\n"
        "- <mark class=\"correct-answer\">A</mark> State the objective.",
    )
    assert exercise_fingerprint(first_exercise(reordered_mappings)) != baseline
    assert exercise_fingerprint(first_exercise(unchanged_structure_key_swap)) == baseline


def test_course_manifest_derives_deterministic_structure_from_model(synthetic_documents):
    manifest = course_manifest(list(reversed(synthetic_documents)))
    assert manifest == course_manifest(synthetic_documents)
    assert manifest["manifest_version"] == 1
    assert [module["id"] for module in manifest["modules"]] == ["alpha", "beta", "gamma", "delta"]
    assert [module["source"] for module in manifest["modules"]] == [
        "30-first.md",
        "10-second.md",
        "20-third.md",
        "00-last.md",
    ]
    assert manifest["sequence"] == [
        path.as_posix().removesuffix("index.html")
        for path in course_sequence(synthetic_documents)
    ]
    assert all(path.endswith("/") for path in manifest["sequence"])

    alpha = manifest["modules"][0]
    assert alpha["path"] == "alpha/"
    first_ex = alpha["sections"][0]["exercises"][0]
    assert first_ex["id"] == "alpha--choosing-a-label--exercise-1"
    assert first_ex["path"] == "alpha/choosing-a-label/exercise-1/"
    assert first_ex["models"] == 1
    assert first_ex["groups"] == [{"id": "exercise", "responses": ["context-q1"]}]
    assert first_ex["responses"] == [
        {
            "id": "context-q1",
            "kind": "single-choice",
            "source_label": None,
            "option_count": 2,
            "expected": [1],
        }
    ]
    assert first_ex["feedback"] == {
        "exercise": {
            "correct": False,
            "incorrect": False,
            "options": ["a", "b"],
            "gaps": [],
        }
    }

    gamma_ex = manifest["modules"][2]["sections"][0]["exercises"][0]
    assert gamma_ex["models"] == 1
    assert gamma_ex["groups"] == [
        {"id": "item-a", "responses": ["item-a-q1"]},
        {"id": "item-b", "responses": ["item-b-q1"]},
    ]
    assert gamma_ex["responses"] == [
        {
            "id": "item-a-q1",
            "kind": "typed-gap",
            "source_label": "1",
            "option_count": 0,
            "expected": "North",
        },
        {
            "id": "item-b-q1",
            "kind": "typed-gap",
            "source_label": "2",
            "option_count": 0,
            "expected": "South east",
        },
    ]
    assert gamma_ex["feedback"] == {
        "exercise": {
            "correct": True,
            "incorrect": True,
            "options": [],
            "gaps": ["1", "2"],
        },
        "item-a": {
            "correct": True,
            "incorrect": False,
            "options": [],
            "gaps": ["1"],
        },
        "item-b": {
            "correct": False,
            "incorrect": False,
            "options": [],
            "gaps": [],
        },
    }
    serialised = format_manifest(manifest)
    assert serialised.endswith("\n")
    assert "This local explanation replaces" not in serialised
    assert json.loads(serialised) == manifest


@pytest.mark.canonical
def test_committed_course_manifest_matches_canonical_sources(documents):
    committed = (ROOT / "course.manifest.json").read_text(encoding="utf-8")
    assert committed == format_manifest(course_manifest(documents))
