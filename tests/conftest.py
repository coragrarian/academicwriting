"""Canonical documents shared by parser, build and browser checks."""

from pathlib import Path

import pytest

from agrarian_builder.parser import discover_documents

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="session")
def documents():
    return discover_documents(ROOT / "exercises")


@pytest.fixture(scope="session")
def methods(documents):
    return next(document for document in documents if document.slug == "methods")
