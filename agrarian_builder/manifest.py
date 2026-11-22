"""Derive a review-oriented description of the published course from the model.

Structural fingerprints summarise the response contract of an exercise so the
browser can detect when saved responses no longer correspond to the authored
controls. This module reads semantic ``Document`` trees and shared path/text
helpers; it neither parses Markdown nor renders HTML.
"""

import hashlib
import json

from .model import Exercise
from .text import plain_text


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
