"""Typed JSON contracts shared between the renderer and browser scripts.

Course pages embed ``#site-data`` for progress and navigation, exercise pages
embed ``#answer-key`` for client-side checking, and Home embeds a compact
module and exercise-URL catalogue. This module defines the static schema of
those JSON payloads; it does not serialise JSON, render templates or evaluate
learner responses.
"""

from typing import TypedDict

from .model import ResponseKind


class FeedbackPayload(TypedDict):
    """Scope-level correct and incorrect explanations emitted for the browser."""

    correct: str | None
    incorrect: str | None


class QuestionPayload(TypedDict):
    """Browser checking contract for one scored question."""

    kind: ResponseKind
    expected: list[int] | str
    label: str
    gap_feedback: str | None
    option_feedback: dict[str, str]


class GroupPayload(TypedDict):
    """Response group membership and scoped explanations for the browser."""

    id: str
    title: str | None
    questions: list[str]
    feedback: FeedbackPayload


class AnswerPayload(TypedDict):
    """Complete JSON payload emitted in ``#answer-key`` on exercise pages."""

    fingerprint: str
    questions: dict[str, QuestionPayload]
    groups: list[GroupPayload]
    feedback: FeedbackPayload


class CourseSiteData(TypedDict):
    """JSON payload emitted in ``#site-data`` on module, section and exercise pages."""

    module: str
    sections: dict[str, list[str]]
    modules: dict[str, list[str]]
    course_sections: dict[str, dict[str, list[str]]]


class HomeSiteData(TypedDict):
    """JSON payload emitted in ``#site-data`` on the Home page."""

    modules: dict[str, list[str]]
    exercise_urls: dict[str, str]
