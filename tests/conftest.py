"""Separate canonical regressions from independent authoring-contract proofs."""

import os
from pathlib import Path

import pytest
from browser_support import serve_site
from playwright.sync_api import sync_playwright

from agrarian_builder.parser import discover_documents

ROOT = Path(__file__).resolve().parents[1]
SYNTHETIC_COURSE = ROOT / "tests/fixtures/course"


@pytest.fixture(scope="session")
def documents():
    return discover_documents(ROOT / "exercises")


@pytest.fixture(scope="session")
def methods(documents):
    return next(document for document in documents if document.slug == "methods")


@pytest.fixture(scope="session")
def synthetic_documents():
    return discover_documents(SYNTHETIC_COURSE)


@pytest.fixture(params=[
    pytest.param(SYNTHETIC_COURSE, id="synthetic"),
    pytest.param(ROOT / "exercises", id="canonical", marks=pytest.mark.canonical),
])
def course_documents(request):
    """Exercise the same invariants independently against both source sets."""
    return discover_documents(request.param)


@pytest.fixture(scope="session")
def site(tmp_path_factory, documents):
    with serve_site(documents, tmp_path_factory.mktemp("canonical-browser")) as served:
        yield served


@pytest.fixture(scope="session")
def synthetic_site(tmp_path_factory, synthetic_documents):
    with serve_site(synthetic_documents, tmp_path_factory.mktemp("synthetic-browser")) as served:
        yield served


@pytest.fixture(scope="session")
def browser():
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            channel=os.environ.get("AGRARIAN_BROWSER_CHANNEL") or None
        )
        yield browser
        browser.close()


@pytest.fixture
def page(browser):
    """Isolate saved state and surface uncaught runtime errors in every page."""
    context = browser.new_context(
        viewport={"width": 1280, "height": 900}, reduced_motion="reduce"
    )
    page = context.new_page()
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    yield page
    try:
        assert not errors, errors
    finally:
        context.close()
