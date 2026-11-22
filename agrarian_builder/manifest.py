"""Derive a review-oriented description of the published course from the model.

Structural fingerprints summarise the response contract of an exercise so the
browser can detect when saved responses no longer correspond to the authored
controls. The course manifest records module, subsection and exercise paths,
response shapes, group membership, feedback presence, worked-model counts and
the learning sequence so structural diffs appear in review. This module reads
semantic ``Document`` trees and shared path/text helpers; it neither parses
Markdown nor renders HTML.
"""

import hashlib
import json
import os
from collections.abc import Sequence
from pathlib import Path
from typing import Literal, TypedDict

from .model import Document, Exercise, Feedback, ResponseKind, Section
from .paths import page_path
from .text import plain_text


class ResponseManifest(TypedDict):
    """Scored response contract recorded in the course manifest."""

    id: str
    kind: ResponseKind
    source_label: str | None
    option_count: int
    expected: list[int] | str


class GroupManifest(TypedDict):
    """Response group membership recorded in the course manifest."""

    id: str
    responses: list[str]


class FeedbackPresence(TypedDict):
    """Authored feedback keys present in one exercise or item scope."""

    correct: bool
    incorrect: bool
    options: list[str]
    gaps: list[str]


class ExerciseManifest(TypedDict):
    """Exercise structure, fingerprint and feedback presence in the manifest."""

    id: str
    title: str
    path: str
    fingerprint: str
    responses: list[ResponseManifest]
    groups: list[GroupManifest]
    feedback: dict[str, FeedbackPresence]
    models: int


class SectionManifest(TypedDict):
    """Subsection overview and exercises recorded in the course manifest."""

    id: str
    title: str
    path: str
    exercises: list[ExerciseManifest]


class ModuleManifest(TypedDict):
    """Module identity, order, source file and subsections in the manifest."""

    id: str
    title: str
    order: int
    source: str
    path: str
    sections: list[SectionManifest]


class CourseManifest(TypedDict):
    """Complete review-oriented structural manifest for the course."""

    manifest_version: Literal[1]
    modules: list[ModuleManifest]
    sequence: list[str]


def exercise_fingerprint(exercise: Exercise) -> str:
    """Compute a 16-character structural digest of an exercise's scored responses.

    Parameters
    ----------
    exercise
        Semantic exercise whose scored ``questions`` define the browser
        response structure. Worked models in ``examples`` are excluded.

    Returns
    -------
    str
        First 16 lowercase hexadecimal characters of the SHA-256 digest over
        the canonical JSON representation of the scored questions.

    Notes
    -----
    The fingerprint deliberately excludes answer keys, option correctness
    flags, typed-gap answers, feedback, surrounding prose, worked models and
    titles. Saved responses are re-scored against the current answer key on
    load, so key changes need no invalidation, and prose or feedback edits
    must not discard learners' drafts.
    """
    questions = [
        {
            "id": question.id,
            "kind": question.kind,
            "label": question.source_label,
            "prompt": plain_text(question.prompt_html),
            "options": [plain_text(option.text_html) for option in question.options],
        }
        for question in exercise.questions
    ]
    serialised = json.dumps(
        questions, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(serialised.encode("utf-8")).hexdigest()[:16]


def _directory_url(
    document: Document, section: Section | None = None, exercise: Exercise | None = None
) -> str:
    """Convert an index page path into a site-relative directory URL."""
    return page_path(document, section, exercise).as_posix().removesuffix("index.html")


def _relative_sources(documents: Sequence[Document]) -> dict[str, str]:
    """Derive POSIX source file names relative to the shared source directory."""
    parents = [Path(document.source_path).parent.as_posix() for document in documents]
    try:
        root = Path(os.path.commonpath(parents)) if parents else Path(".")
        return {
            document.slug: Path(document.source_path).relative_to(root).as_posix()
            for document in documents
        }
    except ValueError:
        return {
            document.slug: Path(document.source_path).name for document in documents
        }


def _feedback_presence(feedback: Feedback) -> FeedbackPresence:
    """Record which feedback channels exist in a scope without storing prose."""
    return {
        "correct": feedback.correct is not None,
        "incorrect": feedback.incorrect is not None,
        "options": sorted(feedback.options),
        "gaps": sorted(feedback.gaps),
    }


def _exercise_manifest(
    document: Document, section: Section, exercise: Exercise
) -> ExerciseManifest:
    """Summarise one exercise's response contract and feedback presence."""
    scopes = [("exercise", exercise.direct_questions)] + [
        (item.id, item.questions) for item in exercise.items
    ]
    groups: list[GroupManifest] = [
        {"id": group_id, "responses": [question.id for question in questions]}
        for group_id, questions in scopes
        if questions
    ]
    feedback: dict[str, FeedbackPresence] = {
        "exercise": _feedback_presence(exercise.metadata.feedback),
        **{
            item.id: _feedback_presence(item.metadata.feedback)
            for item in exercise.items
        },
    }
    responses: list[ResponseManifest] = [
        {
            "id": question.id,
            "kind": question.kind,
            "source_label": question.source_label,
            "option_count": len(question.options),
            "expected": (
                question.answer or ""
                if question.kind == "typed-gap"
                else question.correct_indices
            ),
        }
        for question in exercise.questions
    ]
    return {
        "id": exercise.id,
        "title": exercise.title,
        "path": _directory_url(document, section, exercise),
        "fingerprint": exercise_fingerprint(exercise),
        "responses": responses,
        "groups": groups,
        "feedback": feedback,
        "models": len(exercise.examples),
    }


def course_manifest(documents: Sequence[Document]) -> CourseManifest:
    """Build the deterministic structural manifest for a sequence of modules.

    Parameters
    ----------
    documents
        Parsed course modules. They are sorted by ``(order, slug)`` so the
        manifest is independent of discovery order.

    Returns
    -------
    CourseManifest
        JSON-serialisable dictionary describing modules, subsections,
        exercises, response contracts, fingerprints and learning traversal.
    """
    ordered = sorted(documents, key=lambda document: (document.order, document.slug))
    sources = _relative_sources(ordered)
    modules: list[ModuleManifest] = []
    sequence: list[str] = []
    for document in ordered:
        module_url = _directory_url(document)
        sequence.append(module_url)
        sections: list[SectionManifest] = []
        for section in document.sections:
            section_url = _directory_url(document, section)
            sequence.append(section_url)
            exercises: list[ExerciseManifest] = []
            for exercise in section.exercises:
                exercise_entry = _exercise_manifest(document, section, exercise)
                sequence.append(exercise_entry["path"])
                exercises.append(exercise_entry)
            sections.append(
                {
                    "id": section.slug,
                    "title": section.title,
                    "path": section_url,
                    "exercises": exercises,
                }
            )
        modules.append(
            {
                "id": document.slug,
                "title": document.title,
                "order": document.order,
                "source": sources[document.slug],
                "path": module_url,
                "sections": sections,
            }
        )
    return {
        "manifest_version": 1,
        "modules": modules,
        "sequence": sequence,
    }


def format_manifest(manifest: CourseManifest) -> str:
    """Serialise a course manifest as deterministic JSON with a trailing newline."""
    return json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
