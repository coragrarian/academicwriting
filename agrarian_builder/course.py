"""Order course modules and derive the linear learning-page traversal.

Course modules sort by ``(order, slug)``, and the learning sequence visits each
module overview followed by its subsection overviews and their exercises in
authored order. This module owns course order and traversal shared by parsing,
rendering and manifest inspection; it does not choose Previous/Next labels,
apply the Home terminal rule or render pages.
"""

from collections.abc import Sequence
from pathlib import Path

from .model import Document
from .paths import page_path


def ordered_documents(documents: Sequence[Document]) -> list[Document]:
    """Return modules sorted deterministically by ``(order, slug)``.

    Parameters
    ----------
    documents
        Parsed course modules in any discovery order.

    Returns
    -------
    list of Document
        Modules ordered by integer ``order``, with ``slug`` breaking ties.
    """
    return sorted(documents, key=lambda document: (document.order, document.slug))


def learning_sequence(documents: Sequence[Document]) -> list[Path]:
    """Return site-relative ``index.html`` paths in linear reading order.

    Parameters
    ----------
    documents
        Parsed course modules, which are ordered before traversal.

    Returns
    -------
    list of Path
        Ordered learning-page paths built with ``paths.page_path``. Home,
        About and the 404 fallback are outside this sequence.
    """
    sequence: list[Path] = []
    for document in ordered_documents(documents):
        sequence.append(page_path(document))
        for section in document.sections:
            sequence.append(page_path(document, section))
            sequence.extend(
                page_path(document, section, exercise) for exercise in section.exercises
            )
    return sequence
