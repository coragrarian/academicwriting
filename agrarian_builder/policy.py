"""Enforce publication policy over already-parsed course documents.

This layer validates naming and identity conventions required when publishing
or inspecting the canonical course in ``exercises/``: module front matter,
aligned level-one titles, explicit subsection and exercise IDs, sequential
``Exercise N`` numbering and reserved site module IDs.

It deliberately does not parse Markdown, check response grammar, sort modules,
derive page paths or render HTML; grammar validation belongs to ``parser.py``
and site layout constants belong to ``paths.py``.
"""

import re
from collections.abc import Sequence

from .model import Document
from .parser import SourceError
from .paths import RESERVED_MODULE_IDS

EXERCISE_NUMBER_RE = re.compile(r"Exercise\s+(\d+)")


def check_publication(documents: Sequence[Document]) -> None:
    """Verify that parsed documents satisfy the course publication policy.

    Parameters
    ----------
    documents
        Parsed course modules whose grammar has already been validated by
        ``parser.py``.

    Raises
    ------
    SourceError
        A module omits front matter, uses a reserved module ID, diverges
        between its level-one heading and front-matter title, omits an explicit
        subsection or exercise ID, or has an ``Exercise N`` title whose number
        does not match its one-based position within its subsection.

    Notes
    -----
    Free exercise titles permitted by explicit ID comments are exempt from the
    sequential ``Exercise N`` numbering rule.
    """
    for document in documents:
        source = document.source_path
        if not document.front_matter:
            raise SourceError(f"{source}: publication requires front matter with id and title")
        if document.slug in RESERVED_MODULE_IDS:
            raise SourceError(
                f"{source}: module id {document.slug!r} is reserved for the generated site"
            )
        if document.heading_title != document.title:
            raise SourceError(
                f"{source}: level-one title {document.heading_title!r} must equal "
                f"front matter title {document.title!r}"
            )
        for section in document.sections:
            if not section.explicit_id:
                raise SourceError(
                    f"{source}, {section.title}: publication requires an explicit subsection id"
                )
            for position, exercise in enumerate(section.exercises, start=1):
                if not exercise.explicit_id:
                    raise SourceError(
                        f"{source}, {section.title}, {exercise.title}: "
                        "publication requires an explicit exercise id"
                    )
                match = EXERCISE_NUMBER_RE.fullmatch(exercise.title)
                if match is not None and int(match.group(1)) != position:
                    raise SourceError(
                        f"{source}, {section.title}, {exercise.title}: "
                        f"exercise number must equal its position {position}"
                    )
