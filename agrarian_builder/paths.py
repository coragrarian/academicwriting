"""Derive site-relative page paths and portable links from semantic entities.

Module, subsection and exercise slugs map deterministically to ``index.html``
paths relative to the generated site root. This module owns site layout
conventions shared by policy checking, rendering and manifest inspection,
including module IDs reserved for generated site routes and static assets; it
does not sort modules, choose course traversal order or touch the filesystem.
"""

import os
from pathlib import Path

from .model import Document, Exercise, Section

RESERVED_MODULE_IDS: frozenset[str] = frozenset({"about", "assets"})


def page_path(
    document: Document, section: Section | None = None, exercise: Exercise | None = None
) -> Path:
    """Return ``module/section/exercise/index.html`` relative to the site root.

    Parameters
    ----------
    document
        Module supplying the top-level directory slug.
    section
        Optional subsection supplying the second directory level.
    exercise
        Optional exercise supplying the leaf directory level.

    Returns
    -------
    Path
        Site-relative path ending in ``index.html``. Omitting ``exercise`` or
        both optional levels selects the subsection or module overview page.
    """
    path = Path(document.slug)
    if section is not None:
        path /= section.slug
    if exercise is not None:
        path /= exercise.slug
    return path / "index.html"


def link_for(root: Path, current: Path, target: Path) -> str:
    """Link between site-relative page paths using portable URL separators."""
    return os.path.relpath(root / target, (root / current).parent).replace(os.sep, "/")
