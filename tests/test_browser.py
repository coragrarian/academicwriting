"""Real-browser regression checks. Run explicitly with pytest -m browser."""

import json
import os
import shutil
import threading
from dataclasses import replace
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from itertools import pairwise
from pathlib import Path

import pytest
from playwright.sync_api import expect, sync_playwright

from agrarian_builder import renderer
from agrarian_builder.renderer import build_site

pytestmark = pytest.mark.browser


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, format, *args):
        pass


@pytest.fixture(scope="module")
def site(tmp_path_factory, documents):
    """Serve below /study so tests also exercise deployment under a URL prefix."""
    root = tmp_path_factory.mktemp("browser-site")
    build_site(documents, root / "study")
    server = ThreadingHTTPServer(("127.0.0.1", 0), partial(QuietHandler, directory=str(root)))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}/study", root / "study"
    server.shutdown()
    thread.join()
    server.server_close()


@pytest.fixture(scope="module")
def browser():
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            channel=os.environ.get("AGRARIAN_BROWSER_CHANNEL") or None
        )
        yield browser
        browser.close()


@pytest.fixture
def page(browser):
    """Isolate learner storage between tests and surface uncaught frontend errors."""
    context = browser.new_context(
        viewport={"width": 1280, "height": 900}, reduced_motion="reduce"
    )
    page = context.new_page()
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    yield page
    assert not errors, errors
    context.close()


def open_exercise(page, site, module, section, number):
    page.goto(f"{site[0]}/{module}/{section}/exercise-{number}/index.html")
    expect(page.locator("#exercise-form")).to_have_attribute("data-exercise-initialised", "true")
    return json.loads(page.locator("#answer-key").text_content())


def respond(page, key, *, wrong_id=None, normalised=False):
    """Fill native controls; leave the Check action to each test.

    Parameters
    ----------
    wrong_id
        Replace one response with an incorrect choice or text, keeping the
        remaining responses correct.
    normalised
        Vary only case and whitespace in correct typed answers to exercise
        the checking contract without changing the expected words.
    """
    for question_id, question in key["questions"].items():
        control = page.locator(f'[data-question="{question_id}"]')
        wrong = question_id == wrong_id
        expected = question["expected"]
        if question["kind"] == "typed-gap":
            value = "wrong answer" if wrong else expected
            if normalised and not wrong:
                value = "  " + value.upper().replace(" ", "   ") + "  "
            control.fill(value)
        elif question["kind"] in ("single-choice", "multi-select"):
            selected = (
                expected
                if not wrong
                else [
                    next(
                        index
                        for index in range(control.locator("input").count())
                        if index not in expected
                    )
                ]
            )
            for input in control.locator("input").all():
                should_select = int(input.get_attribute("value")) in selected
                if question["kind"] == "multi-select":
                    input.set_checked(should_select)
                elif should_select:
                    input.check()
        else:
            value = (
                expected[0]
                if not wrong
                else next(
                    index
                    for index in range(control.locator("option").count() - 1)
                    if index not in expected
                )
            )
            control.select_option(str(value))


CASES = [
    ("methods", "grammar-and-vocabulary-in-the-methods-section", 2),
    ("methods", "grammar-and-vocabulary-in-the-methods-section", 3),
    ("methods", "grammar-and-vocabulary-in-the-methods-section", 1),
    ("introduction", "giving-a-context-background", 1),
    ("introduction", "reviewing-previous-research", 2),
    ("introduction", "reviewing-previous-research", 1),
    ("introduction", "indicating-a-research-gap", 1),
    ("introduction", "indicating-a-research-gap", 2),
    ("introduction", "grammar-and-vocabulary-in-the-introduction-section", 1),
    ("methods", "purpose-of-the-methods-section", 3),
    ("results", "grammar-and-vocabulary-in-the-results-section", 2),
    ("results", "grammar-and-vocabulary-in-the-results-section", 3),
    ("results", "grammar-and-vocabulary-in-the-results-section", 6),
    ("results", "grammar-and-vocabulary-in-the-results-section", 7),
]


@pytest.mark.parametrize(("module", "section", "number"), CASES)
def test_representative_interactions_feedback_retry_reset_and_persistence(
    page, site, module, section, number
):
    key = open_exercise(page, site, module, section, number)
    expect(page.locator("button[type=submit]")).to_have_count(1)
    expect(page.locator("[data-current-status]")).to_have_text("Not started")
    wrong = next(iter(key["questions"]))
    respond(page, key, wrong_id=wrong)
    expect(page.locator("[data-current-status]")).to_have_text("In progress")
    page.locator("button[type=submit]").click()
    expect(page.locator(f'[data-question="{wrong}"]')).to_have_attribute("aria-invalid", "true")
    expect(page.locator("#exercise-feedback")).to_contain_text("Review")
    expect(page.locator("[data-current-status]")).to_have_text("In progress")
    if key["groups"][0]["title"]:
        expect(
            page.locator("[data-response-group]")
            .filter(has=page.locator(f'[data-question="{wrong}"]'))
            .locator("[data-item-feedback]")
        ).to_contain_text("Review this item")
    feedback = page.locator("#exercise-feedback").text_content()
    page.reload()
    expect(page.locator("#exercise-feedback")).to_have_text(feedback)
    expect(page.locator(f'[data-question="{wrong}"]')).to_have_attribute("aria-invalid", "true")
    respond(page, key, normalised=True)
    expect(page.locator("#exercise-feedback")).to_be_empty()
    page.locator("button[type=submit]").click()
    expect(page.locator("[data-current-status]")).to_have_text("Completed")
    expect(page.locator("[data-question][aria-invalid=true]")).to_have_count(0)
    expect(page.locator(f'[data-progress-module="{module}"]')).to_have_text(
        f"1/{ {'methods': 7, 'introduction': 14, 'results': 9}[module] }"
    )
    assert page.locator("[data-item-feedback]").all_text_contents()
    assert "Correct." in " ".join(
        page.locator("[data-item-feedback], #shared-feedback").all_text_contents()
    )
    given = page.evaluate(
        'JSON.parse(localStorage.getItem(`agrarian-writing-v2:${JSON.parse(document.querySelector("#site-data").textContent).module}`)).responses'
    )
    page.reload()
    expect(page.locator("[data-current-status]")).to_have_text("Completed")
    assert given == page.evaluate(
        'JSON.parse(localStorage.getItem(`agrarian-writing-v2:${JSON.parse(document.querySelector("#site-data").textContent).module}`)).responses'
    )
    page.locator("#reset-exercise").click()
    expect(page.locator("[data-current-status]")).to_have_text("Not started")
    expect(page.locator("#exercise-feedback")).to_be_empty()
    expect(page.locator("[data-result]")).to_have_count(0)
    expect(page.locator("[data-item-feedback]:visible, #shared-feedback:visible")).to_have_count(
        0
    )
    expect(page.locator("input:checked")).to_have_count(0)
    assert all(
        value == ""
        for value in page.locator("select, input[type=text]").evaluate_all(
            "(nodes) => nodes.map(node => node.value)"
        )
    )
    page.reload()
    expect(page.locator("[data-current-status]")).to_have_text("Not started")


def test_option_feedback_follows_selected_option(page, site):
    key = open_exercise(page, site, "methods", "purpose-of-the-methods-section", 1)
    question_id = next(iter(key["questions"]))
    for index in [0, 2, 1]:
        page.locator(f'[data-question="{question_id}"] input[value="{index}"]').check()
        page.locator("button[type=submit]").click()
        expect(page.locator("[data-item-feedback]")).to_contain_text(
            key["questions"][question_id]["option_feedback"][str(index)]
        )
    expect(page.locator("[data-current-status]")).to_have_text("Completed")


def test_typed_normalisation_remains_exact(page, site):
    key = open_exercise(page, site, "introduction", "indicating-a-research-gap", 1)
    respond(page, key, normalised=True)
    page.locator("button[type=submit]").click()
    expect(page.locator("[data-current-status]")).to_have_text("Completed")
    question_id = next(iter(key["questions"]))
    # The adverb is now outside the gap; including it duplicates source text.
    page.locator(f'[data-question="{question_id}"]').fill("has primarily concentrated")
    page.locator("button[type=submit]").click()
    expect(page.locator("[data-current-status]")).to_have_text("In progress")
    expect(page.locator(f'[data-question="{question_id}"]')).to_have_attribute(
        "aria-invalid", "true"
    )


def test_partial_navigation_history_focus_and_reinitialisation(page, site):
    key = open_exercise(page, site, "methods", "grammar-and-vocabulary-in-the-methods-section", 2)
    respond(page, key)
    page.locator("button[type=submit]").click()
    original = page.url
    # A value in the JS heap survives partial navigation but not a full load.
    page.evaluate("window.navigationProbe = 17")
    for _ in range(3):
        page.get_by_role("link", name="Next", exact=True).click()
        expect(page.locator("h1")).to_have_text("Exercise 3")
        expect(page.locator("h1")).to_be_focused()
        assert page.evaluate("window.navigationProbe") == 17
        assert (
            page.locator("h1").evaluate("node => getComputedStyle(node).outlineStyle") == "none"
        )
        key_next = json.loads(page.locator("#answer-key").text_content())
        respond(page, key_next)
        # One submit must produce one feedback update after repeated navigation.
        page.evaluate("""() => {
          window.feedbackChanges = 0;
          new MutationObserver(() => window.feedbackChanges++).observe(
            document.querySelector('#exercise-feedback'), {childList: true});
        }""")
        page.locator("button[type=submit]").click()
        expect(page.locator("[data-current-status]")).to_have_text("Completed")
        assert page.evaluate("window.feedbackChanges") == 1
        page.go_back()
        expect(page.locator("h1")).to_have_text("Exercise 2")
        expect(page.locator("[data-current-status]")).to_have_text("Completed")
        assert page.url == original
    page.go_forward()
    expect(page.locator("h1")).to_have_text("Exercise 3")
    page.get_by_role("button", name="Reset", exact=True).focus()
    page.keyboard.press("Tab")
    active = page.locator(":focus")
    assert active.evaluate("node => getComputedStyle(node).outlineStyle") == "solid"
    assert active.evaluate("node => getComputedStyle(node).outlineColor") == "rgb(40, 94, 81)"


def test_public_gateway_preserves_independent_module_progress(page, site):
    for module, section, number in [CASES[0], CASES[3], CASES[-1]]:
        key = open_exercise(page, site, module, section, number)
        respond(page, key)
        page.locator("button[type=submit]").click()
    page.evaluate("window.fullNavigationProbe = 21")
    page.locator(".nav-home").click()
    expect(page.locator("h1")).to_have_text("Academic Writing for Agrarian Sciences")
    assert page.evaluate("window.fullNavigationProbe") is None
    expect(page.locator(".course-panel, [data-progress-other-module], [data-progress-module]")).to_have_count(0)
    page.locator(".contents-link").first.click()
    expect(page.locator("h1")).to_have_text("The Introduction section")
    for module, total in [("introduction", 14), ("methods", 7), ("results", 9)]:
        expect(page.locator(f'[data-progress-module="{module}"]')).to_have_text(
            f"1/{total}"
        )


def test_every_canonical_exercise_can_complete(page, site, documents):
    for document in documents:
        for section in document.sections:
            for exercise in section.exercises:
                key = open_exercise(
                    page, site, document.slug, section.slug, int(exercise.slug.split("-")[-1])
                )
                respond(page, key)
                page.locator("button[type=submit]").click()
                expect(page.locator("[data-current-status]")).to_have_text("Completed")
        total = sum(len(section.exercises) for section in document.sections)
        expect(page.locator(f'[data-progress-module="{document.slug}"]')).to_have_text(f"{total}/{total}")


@pytest.mark.parametrize(
    ("module", "section", "number"),
    CASES,
)
def test_mobile_layout(page, site, module, section, number):
    page.set_viewport_size({"width": 375, "height": 812})
    key = open_exercise(page, site, module, section, number)
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    for control in page.locator("select, input[type=text], button").all():
        box = control.bounding_box()
        assert box["x"] >= 0 and box["x"] + box["width"] <= 375
    respond(page, key, wrong_id=next(iter(key["questions"])))
    page.locator("button[type=submit]").click()
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    screenshots = os.environ.get("AGRARIAN_SCREENSHOTS")
    if screenshots:
        directory = Path(screenshots)
        directory.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(directory / f"{module}-{number}-mobile.png"), full_page=True)


def test_fetch_failure_and_modified_click_fallback(page, site):
    open_exercise(page, site, "methods", "grammar-and-vocabulary-in-the-methods-section", 2)
    page.evaluate(
        '() => { window.fallbackProbe = 19; window.fetch = () => Promise.reject(new Error("offline")); }'
    )
    page.get_by_role("link", name="Next", exact=True).click()
    expect(page.locator("h1")).to_have_text("Exercise 3")
    assert page.evaluate("window.fallbackProbe") is None
    with page.context.expect_page() as opened:
        page.get_by_role("link", name="Next", exact=True).click(modifiers=["Control"])
    tab = opened.value
    expect(tab.locator("h1")).to_have_text("Exercise 4")
    tab.close()


def test_javascript_disabled_and_file_preview(browser, site):
    context = browser.new_context(java_script_enabled=False)
    page = context.new_page()
    page.goto(
        site[0] + "/methods/grammar-and-vocabulary-in-the-methods-section/exercise-2/index.html"
    )
    expect(page.locator(".instructions")).to_be_visible()
    page.get_by_role("link", name="Next", exact=True).click()
    expect(page.locator("h1")).to_have_text("Exercise 3")
    context.close()
    context = browser.new_context()
    page = context.new_page()
    page.goto(
        (
            site[1]
            / "methods"
            / "grammar-and-vocabulary-in-the-methods-section"
            / "exercise-2"
            / "index.html"
        ).as_uri()
    )
    key = json.loads(page.locator("#answer-key").text_content())
    respond(page, key)
    page.locator("button[type=submit]").click()
    expect(page.locator("[data-current-status]")).to_have_text("Completed")
    page.get_by_role("link", name="Next", exact=True).click()
    expect(page.locator("h1")).to_have_text("Exercise 3")
    context.close()


def test_storage_unavailable_still_allows_checking(browser, site):
    context = browser.new_context()
    context.add_init_script("""Object.defineProperty(window, 'localStorage', {
      get() { throw new Error('storage unavailable'); }
    });""")
    page = context.new_page()
    key = open_exercise(page, site, "results", "grammar-and-vocabulary-in-the-results-section", 7)
    respond(page, key)
    page.locator("button[type=submit]").click()
    expect(page.locator("[data-current-status]")).to_have_text("Completed")
    context.close()


def test_unchecked_typed_input_persists_after_refresh(page, site):
    key = open_exercise(page, site, "introduction", "indicating-a-research-gap", 1)
    question_id = next(iter(key["questions"]))
    typed = "  HAS   concentrated  "
    page.locator(f'[data-question="{question_id}"]').fill(typed)
    page.reload()
    expect(page.locator(f'[data-question="{question_id}"]')).to_have_value(typed)
    expect(page.locator("[data-current-status]")).to_have_text("In progress")
    expect(page.locator("#exercise-feedback")).to_be_empty()


def test_multi_select_requires_exact_set(page, site):
    key = open_exercise(page, site, "methods", "grammar-and-vocabulary-in-the-methods-section", 3)
    respond(page, key)
    question_id, question = next(iter(key["questions"].items()))
    wrong_option = next(index for index in range(3) if index not in question["expected"])
    control = page.locator(f'[data-question="{question_id}"]')
    control.locator(f'input[value="{wrong_option}"]').check()
    page.locator("button[type=submit]").click()
    expect(page.locator("[data-current-status]")).to_have_text("In progress")
    control.locator(f'input[value="{wrong_option}"]').uncheck()
    control.locator(f'input[value="{question["expected"][0]}"]').uncheck()
    page.locator("button[type=submit]").click()
    expect(page.locator("[data-current-status]")).to_have_text("In progress")
    respond(page, key)
    page.locator("button[type=submit]").click()
    expect(page.locator("[data-current-status]")).to_have_text("Completed")


def test_desktop_layout_and_shared_gap_links(page, site):
    key = open_exercise(page, site, "introduction", "reviewing-previous-research", 2)
    expect(page.locator(".exercise-item")).to_have_count(5)
    assert (
        page.locator(".exercise-content").evaluate(
            "node => getComputedStyle(node).borderTopStyle"
        )
        == "none"
    )
    assert (
        page.locator(".instructions").evaluate("node => getComputedStyle(node).borderTopStyle")
        == "none"
    )
    page.locator('.item-gap[href="#item-c"]').click()
    assert page.url.endswith("#item-c")
    respond(page, key, wrong_id="item-c-q1")
    page.locator("button[type=submit]").click()
    expect(page.locator("#exercise-feedback")).to_have_text(
        "4 of 5 items correct. Review Item C."
    )
    expect(page.locator("#shared-feedback")).to_be_visible()
    screenshots = os.environ.get("AGRARIAN_SCREENSHOTS")
    if screenshots:
        directory = Path(screenshots)
        directory.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(directory / "introduction-tense-desktop.png"), full_page=True)
        open_exercise(page, site, "methods", "grammar-and-vocabulary-in-the-methods-section", 2)
        page.screenshot(path=str(directory / "methods-context-desktop.png"), full_page=True)


@pytest.mark.parametrize(
    ("module", "section", "number"),
    [
        ("methods", "purpose-of-the-methods-section", 1),
        ("methods", "grammar-and-vocabulary-in-the-methods-section", 2),
        ("methods", "grammar-and-vocabulary-in-the-methods-section", 3),
    ],
)
def test_selected_rows_distinguish_review_from_success(page, site, module, section, number):
    key = open_exercise(page, site, module, section, number)
    question_id, question = next(iter(key["questions"].items()))
    control = page.locator(f'[data-question="{question_id}"]')
    wrong = next(
        index for index in range(control.locator("input").count())
        if index not in question["expected"]
    )
    wrong_row = control.locator(".choice-option").nth(wrong)
    correct_row = control.locator(".choice-option").nth(question["expected"][0])
    correct_background = correct_row.evaluate("node => getComputedStyle(node).backgroundColor")
    wrong_row.click()
    assert wrong_row.evaluate("node => getComputedStyle(node).backgroundColor") == "rgb(237, 241, 240)"
    page.locator("button[type=submit]").click()
    assert wrong_row.evaluate("node => getComputedStyle(node).backgroundColor") == "rgb(255, 240, 229)"
    assert correct_row.evaluate("node => getComputedStyle(node).backgroundColor") == correct_background
    expect(correct_row.locator("input")).not_to_be_checked()
    respond(page, key)
    page.locator("button[type=submit]").click()
    assert correct_row.evaluate("node => getComputedStyle(node).backgroundColor") == "rgb(243, 248, 245)"
    correct_row.locator("input").focus()
    page.keyboard.press("Tab")
    page.keyboard.press("Shift+Tab")
    assert correct_row.evaluate("node => getComputedStyle(node).outlineStyle") == "solid"
    if page.locator(".exercise-item").count():
        assert wrong_row.evaluate("node => getComputedStyle(node).borderTopWidth") == "0px"
        assert page.locator(".exercise-item").first.evaluate(
            "node => getComputedStyle(node).borderTopWidth"
        ) == "1px"


def test_research_gap_diagnostics_and_self_contained_excerpt(page, site):
    key = open_exercise(page, site, "introduction", "indicating-a-research-gap", 1)
    for control in page.locator("input[type=text]").all():
        control.fill("wrong answer")
    page.locator("button[type=submit]").click()
    explanations = page.locator(".gap-feedback")
    expect(explanations).to_have_count(3)
    expect(explanations.nth(0)).to_contain_text('"Previous research" is grammatically singular')
    expect(explanations.nth(1)).to_contain_text("have + been + past participle")
    expect(explanations.nth(2)).to_contain_text('"Investigations" is plural')
    for question_id, question in key["questions"].items():
        expect(page.locator(f"#{question_id}-feedback")).to_contain_text(question["gap_feedback"])
    respond(page, key)
    page.locator("button[type=submit]").click()
    expect(page.locator("[data-current-status]")).to_have_text("Completed")
    page.get_by_role("link", name="Next", exact=True).click()
    expect(page.locator("h1")).to_have_text("Exercise 2")
    expect(page.locator(".exercise-content blockquote")).to_contain_text(
        "thereby limiting our understanding of the mechanisms underlying cotton growth and nutrient absorption"
    )
    expect(page.locator(".exercise-content blockquote")).to_contain_text("have examined only")
    expect(page.locator(".instructions")).to_contain_text("Read the excerpt below")


@pytest.mark.parametrize("native_fallback", [False, True])
def test_inline_selects_adapt_to_the_answer_and_column(page, site, native_fallback):
    key = open_exercise(page, site, "methods", "purpose-of-the-methods-section", 2)
    if native_fallback:
        page.add_style_tag(content=".inline-select { field-sizing: fixed !important; }")
    respond(page, key)
    long = page.locator(".inline-select").first
    assert long.bounding_box()["width"] > 23 * 16
    assert long.bounding_box()["width"] <= long.locator("xpath=..").bounding_box()["width"]
    for width in [375, 320]:
        page.set_viewport_size({"width": width, "height": 812})
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        for control in page.locator(".inline-select").all():
            box = control.bounding_box()
            parent = control.locator("xpath=..").bounding_box()
            assert box["x"] >= parent["x"] - 1
            assert box["x"] + box["width"] <= parent["x"] + parent["width"] + 1
    page.set_viewport_size({"width": 1280, "height": 900})
    key = open_exercise(page, site, "results", "grammar-and-vocabulary-in-the-results-section", 7)
    if native_fallback:
        page.add_style_tag(content=".inline-select { field-sizing: fixed !important; }")
    respond(page, key)
    assert all(control.bounding_box()["width"] < 220 for control in page.locator(".inline-select").all())


@pytest.mark.parametrize("level", ["home", "about", "module", "section", "exercise"])
def test_global_course_tree_defaults_and_current_page(page, site, level):
    suffix = {
        "home": "",
        "about": "/about",
        "module": "/methods",
        "section": "/methods/purpose-of-the-methods-section",
        "exercise": "/methods/purpose-of-the-methods-section/exercise-1",
    }[level]
    page.goto(f"{site[0]}{suffix}/index.html")
    expect(page.locator('[aria-current="page"]')).to_have_count(1)
    if level in {"home", "about"}:
        expect(page.locator(".course-panel, [data-site-navigation], [data-course-navigator]")).to_have_count(0)
        expect(page.locator(".nav-module-group, .nav-section-group, [data-exercise-link]")).to_have_count(0)
    else:
        expect(page.locator(".nav-module-group")).to_have_count(3)
        expect(page.locator(".nav-section-group")).to_have_count(10)
        expect(page.locator(".course-panel [data-exercise-link]")).to_have_count(30)
        expect(page.locator('.course-panel [aria-current="page"]')).to_have_count(1)
        expect(page.locator(".nav-module-group[open]")).to_have_count(1)
        assert page.locator(".nav-section-group[open]").count() == (1 if level in {"section", "exercise"} else 0)
        expect(page.locator('[data-nav-node="module:methods"]')).to_have_attribute("open", "")


def test_global_tree_toggles_keyboard_progress_and_partial_state(page, site):
    key = open_exercise(page, site, "methods", "grammar-and-vocabulary-in-the-methods-section", 2)
    respond(page, key)
    page.locator("button[type=submit]").click()
    other_module = page.locator('[data-nav-node="module:introduction"]')
    other_module.locator(":scope > summary").focus()
    original = page.url
    page.keyboard.press("Enter")
    expect(other_module).to_have_attribute("open", "")
    other_section = page.locator('[data-nav-node="section:introduction:indicating-a-research-gap"]')
    other_section.locator(":scope > summary").click()
    expect(other_section).to_have_attribute("open", "")
    assert page.url == original
    page.get_by_role("link", name="Next", exact=True).click()
    expect(page.locator("h1")).to_have_text("Exercise 3")
    expect(page.locator('[data-nav-node="module:introduction"]')).to_have_attribute("open", "")
    expect(page.locator('[data-nav-node="section:introduction:indicating-a-research-gap"]')).to_have_attribute("open", "")
    expect(page.locator('[data-progress-module="methods"]')).to_have_text("1/7")
    expect(page.locator('[data-progress-module="introduction"]')).to_have_text("0/14")
    expect(page.locator('[data-progress-section="grammar-and-vocabulary-in-the-methods-section"][data-progress-module-id="methods"]')).to_have_text("1/4")
    link = page.locator('.course-panel [data-exercise-link="methods--grammar-and-vocabulary-in-the-methods-section--exercise-2"]')
    expect(link).to_have_attribute("data-status", "completed")
    page.set_viewport_size({"width": 375, "height": 812})
    expect(page.locator("[data-course-navigator]")).not_to_have_attribute("open", "")
    toggle = page.locator(".course-toggle")
    toggle.focus()
    page.keyboard.press("Enter")
    expect(page.locator("[data-course-navigator]")).to_have_attribute("open", "")
    page.get_by_role("link", name="Next", exact=True).click()
    expect(page.locator("h1")).to_have_text("Exercise 4")
    expect(page.locator("[data-course-navigator]")).to_have_attribute("open", "")


def test_global_course_tree_remains_usable_without_javascript(browser, site):
    context = browser.new_context(java_script_enabled=False)
    page = context.new_page()
    page.goto(site[0] + "/index.html")
    page.locator(".contents-link").first.click()
    page.locator('[data-nav-node="module:results"] > summary').click()
    page.locator('[data-nav-node="section:results:grammar-and-vocabulary-in-the-results-section"] > summary').click()
    page.locator('.course-panel [data-exercise-link="results--grammar-and-vocabulary-in-the-results-section--exercise-3"]').click()
    expect(page.locator("h1")).to_have_text("Exercise 3")
    expect(page.locator(".worked-model")).to_be_visible()
    context.close()


@pytest.mark.parametrize(("module", "section", "count"), [
    ("introduction", "the-introduction-section-of-research-papers", 1),
    ("methods", "grammar-and-vocabulary-in-the-methods-section", 4),
])
def test_overview_rows_preserve_keyboard_progress_and_history(page, site, module, section, count):
    overview = f"{site[0]}/{module}/{section}/index.html"
    page.goto(overview)
    rows = page.locator(".exercise-list a")
    expect(rows).to_have_count(count)
    for number, row in enumerate(rows.all(), 1):
        expect(row).to_have_attribute("data-exercise-link", f"{module}--{section}--exercise-{number}")
        expect(row).to_have_attribute("data-module-id", module)
        expect(row).to_have_attribute("href", f"exercise-{number}/index.html")
        expect(row.locator(".state-dot")).to_have_attribute("aria-hidden", "true")
    navigation = page.locator(".page-navigation a").evaluate_all(
        "nodes => nodes.map(n => [n.href, n.rel, n.textContent.trim()])"
    )
    page.keyboard.press("Tab")
    expect(page.locator(".skip-link")).to_be_focused()
    page.keyboard.press("Enter")
    for _ in range(12):
        page.keyboard.press("Tab")
        if rows.first.evaluate("node => node === document.activeElement"):
            break
    expect(rows.first).to_be_focused()
    assert rows.first.evaluate("node => getComputedStyle(node).outlineStyle") == "solid"
    page.evaluate("window.overviewProbe = 29")
    first_exercise = rows.first.evaluate("node => node.href")
    page.keyboard.press("Enter")
    expect(page).to_have_url(first_exercise)
    expect(page.locator("#exercise-form")).to_have_attribute("data-exercise-initialised", "true")
    respond(page, json.loads(page.locator("#answer-key").text_content()))
    page.locator("button[type=submit]").click()
    expect(page.locator("[data-current-status]")).to_have_text("Completed")
    page.locator('.page-navigation a[rel="prev"]').click()
    expect(page).to_have_url(overview)
    assert page.evaluate("window.overviewProbe") == 29
    expect(rows.first).to_have_attribute("data-status", "completed")
    expect(rows.first).to_have_accessible_name("Exercise 1: Completed")
    expect(page.locator(".section-count")).to_have_text(f"1/{count} exercises completed")
    assert page.locator(".page-navigation a").evaluate_all(
        "nodes => nodes.map(n => [n.href, n.rel, n.textContent.trim()])"
    ) == navigation
    page.go_back()
    expect(page).to_have_url(first_exercise)
    expect(page.locator("[data-current-status]")).to_have_text("Completed")
    page.go_forward()
    expect(page).to_have_url(overview)
    expect(rows.first).to_have_attribute("data-status", "completed")
    for width in (1280, 1024, 768, 375, 320):
        page.set_viewport_size({"width": width, "height": 900})
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        assert page.locator(".page-navigation").bounding_box()["y"] > (
            rows.last.bounding_box()["y"] + rows.last.bounding_box()["height"]
        )
        for row in rows.all():
            assert row.bounding_box()["height"] >= 44


def test_about_uses_full_navigation_and_preserves_learner_state(page, site):
    key = open_exercise(page, site, "methods", "purpose-of-the-methods-section", 1)
    respond(page, key)
    page.locator("button[type=submit]").click()
    storage = page.evaluate("JSON.stringify({...localStorage})")
    # A same-module swap retains the heap probe; About must load a new document.
    page.evaluate("window.publicPageProbe = 23")
    page.get_by_role("link", name="Next", exact=True).click()
    expect(page.locator("h1")).to_have_text("Exercise 2")
    assert page.evaluate("window.publicPageProbe") == 23
    about = page.get_by_role("navigation", name="Site", exact=True).get_by_role(
        "link", name="About", exact=True
    )
    assert about.evaluate("node => node.href") == f"{site[0]}/about/index.html"
    about.click()
    expect(page.locator("h1")).to_have_text("About Academic Writing for Agrarian Sciences")
    assert page.evaluate("window.publicPageProbe") is None
    assert page.evaluate("JSON.stringify({...localStorage})") == storage
    assert page.locator("html").get_attribute("class") is None
    expect(about).to_have_attribute("aria-current", "page")
    expect(page.locator("#exercise-form, .page-navigation")).to_have_count(0)
    expect(page.locator(".course-panel, [data-site-navigation], [data-progress-module]")).to_have_count(0)
    page.locator(".site-name").click()
    expect(page.locator(".course-panel, [data-progress-other-module]")).to_have_count(0)
    assert page.evaluate("JSON.stringify({...localStorage})") == storage
    page.locator(".contents-link").first.click()
    expect(page.locator('[data-progress-module="methods"]')).to_have_text("1/7")
    assert page.evaluate("JSON.stringify({...localStorage})") == storage


def test_public_page_links_and_skip_link_work_without_javascript(browser, site):
    context = browser.new_context(java_script_enabled=False)
    page = context.new_page()
    page.goto(site[0] + "/index.html")
    page.keyboard.press("Tab")
    expect(page.get_by_role("link", name="Skip to content")).to_be_focused()
    page.keyboard.press("Enter")
    assert page.url.endswith("#main")
    page.locator(".contents-link").first.click()
    assert page.url == f"{site[0]}/introduction/index.html"
    expect(page.locator("h1")).to_have_text("The Introduction section")
    expect(page.locator(".course-panel")).to_be_visible()
    page.get_by_role("navigation", name="Site", exact=True).get_by_role("link", name="About", exact=True).click()
    expect(page.locator("h1")).to_have_text("About Academic Writing for Agrarian Sciences")
    expect(page.locator(".course-panel")).to_have_count(0)
    expect(page.get_by_role("link", name="Academic Writing repository")).to_have_attribute(
        "href", "https://github.com/coragrarian/academicwriting"
    )
    page.locator(".site-name").click()
    expect(page.locator("h1")).to_have_text("Academic Writing for Agrarian Sciences")
    navigation = page.get_by_role("navigation", name="Site", exact=True)
    navigation.get_by_role("link", name="Course", exact=True).click()
    assert page.url == f"{site[0]}/index.html#course"
    navigation.get_by_role("link", name="About", exact=True).click()
    expect(page.locator("h1")).to_have_text("About Academic Writing for Agrarian Sciences")
    page.locator(".site-name").click()
    page.get_by_role("link", name="About the research project", exact=True).click()
    assert page.url == f"{site[0]}/about/index.html"
    expect(page.locator("#team .person--pending")).to_have_count(6)
    context.close()


def test_home_contents_keyboard_focus_and_module_entry(page, site):
    for index, module in enumerate(("introduction", "methods", "results")):
        page.goto(site[0] + "/index.html")
        # The skip link and three header links precede the ordered course rows.
        for _ in range(5 + index):
            page.keyboard.press("Tab")
        row = page.locator(".contents-link").nth(index)
        expect(row).to_be_focused()
        assert row.evaluate("node => getComputedStyle(node).outlineStyle") == "solid"
        expect(row.locator(".nav-chevron")).to_be_visible()
        page.keyboard.press("Enter")
        expect(page).to_have_url(f"{site[0]}/{module}/index.html")
        expect(page.locator("h1")).to_have_text(f"The {module.title()} section")


def test_publication_metadata_follows_history_navigation(page, site):
    page.goto(site[0] + "/methods/index.html")
    page.evaluate("window.metadataNavigationProbe = 29")
    for path in (
        "methods/purpose-of-the-methods-section/",
        "methods/purpose-of-the-methods-section/exercise-1/",
        "methods/purpose-of-the-methods-section/exercise-2/",
    ):
        page.locator('.page-navigation a[rel="next"]').click()
        expect(page.locator('link[rel="canonical"]')).to_have_attribute(
            "href", "https://coragrarian.github.io/academicwriting/" + path
        )
        assert page.evaluate("window.metadataNavigationProbe") == 29
        for selector in ('meta[property="og:title"]', 'meta[name="twitter:title"]'):
            expect(page.locator(selector)).to_have_attribute("content", page.title())
        expect(page.locator('link[rel="icon"]')).to_have_attribute(
            "href", site[0] + "/assets/favicon.svg"
        )
    page.go_back()
    expect(page.locator('link[rel="canonical"]')).to_have_attribute(
        "href", "https://coragrarian.github.io/academicwriting/methods/purpose-of-the-methods-section/exercise-1/"
    )
    expect(page.locator('meta[name="description"]')).to_have_attribute(
        "content", "Interactive exercise 1 on “Purpose of the Methods section” in the module “The Methods section”."
    )
    page.go_forward()
    expect(page.locator('meta[property="og:url"]')).to_have_attribute(
        "content", "https://coragrarian.github.io/academicwriting/methods/purpose-of-the-methods-section/exercise-2/"
    )


def serve_not_found_candidate(page, site):
    """Serve the fallback at a missing URL and map production assets locally.

    GitHub Pages retains the missing request's URL when returning 404.html.
    Production links must work there without contacting the deployed site.
    """
    page.route(site[0] + "/missing/**", lambda route: route.fulfill(
        status=404, content_type="text/html", body=(site[1] / "404.html").read_bytes()
    ))

    def production(route):
        relative = route.request.url.removeprefix(renderer.SITE_URL)
        route.fulfill(response=page.request.get(site[0] + "/" + relative))

    page.route(renderer.SITE_URL + "**", production)


@pytest.mark.parametrize("javascript", [True, False])
def test_not_found_keyboard_recovery_at_a_nested_missing_url(browser, site, javascript):
    context = browser.new_context(java_script_enabled=javascript, reduced_motion="reduce")
    page = context.new_page()
    serve_not_found_candidate(page, site)
    response = page.goto(site[0] + "/missing/deep/page")
    assert response.status == 404
    expect(page.locator("h1")).to_have_text("Page not found")
    expect(page.locator("script, .course-panel, #site-data, [aria-current=page]")).to_have_count(0)
    expect(page.locator('meta[name="robots"]')).to_have_attribute("content", "noindex")
    expect(page.locator('link[rel="canonical"], meta[property="og:url"]')).to_have_count(0)
    for selector in (
        ".skip-link", ".site-name", ".course-link", ".about-link",
        ".not-found-actions a:first-child", ".not-found-actions a:last-child",
    ):
        page.keyboard.press("Tab")
        link = page.locator(selector)
        expect(link).to_be_focused()
        assert link.evaluate("node => getComputedStyle(node).outlineStyle") == "solid"
    page.keyboard.press("Enter")
    expect(page).to_have_url(renderer.SITE_URL + "#course")
    expect(page.get_by_role("heading", name="Course contents", exact=True)).to_be_visible()
    page.goto(site[0] + "/missing/deep/page")
    for _ in range(5):
        page.keyboard.press("Tab")
    expect(page.get_by_role("link", name="Return home", exact=True)).to_be_focused()
    page.keyboard.press("Enter")
    expect(page).to_have_url(renderer.SITE_URL)
    expect(page.locator("h1")).to_have_text("Academic Writing for Agrarian Sciences")
    context.close()


@pytest.mark.parametrize("width", [1440, 1280, 1024, 768, 375, 320])
def test_not_found_assets_and_reflow_at_required_widths(page, site, width):
    serve_not_found_candidate(page, site)
    page.set_viewport_size({"width": width, "height": 900})
    requests = []
    page.on("request", lambda request: requests.append(request.url))
    page.goto(site[0] + "/missing/deep/page")
    page.evaluate("document.fonts.ready")
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    for link in page.locator(".not-found-actions a").all():
        assert link.bounding_box()["height"] >= 44
        link.focus()
        assert link.evaluate("node => getComputedStyle(node).outlineStyle") == "solid"
    for image in page.locator(".institution-logo").all():
        image.scroll_into_view_if_needed()
        expect(image).to_have_js_property("complete", True)
        assert image.evaluate("node => node.naturalWidth > 0")
    assert renderer.SITE_URL + "assets/styles.css" in requests
    assert not any(url.endswith(("/exercises.js", "/navigation.js")) for url in requests)
    expect(page.locator(".public-layout")).to_have_count(1)


PUBLICATION_PAGES = (
    "index.html", "about/index.html", "404.html", "methods/index.html",
    "methods/purpose-of-the-methods-section/index.html",
    "methods/purpose-of-the-methods-section/exercise-1/index.html",
    "introduction/indicating-a-research-gap/exercise-1/index.html",
    "methods/grammar-and-vocabulary-in-the-methods-section/exercise-3/index.html",
    "methods/grammar-and-vocabulary-in-the-methods-section/exercise-1/index.html",
    "introduction/the-introduction-section-of-research-papers/exercise-1/index.html",
)


@pytest.mark.parametrize("path", PUBLICATION_PAGES)
def test_publication_headings_accessible_names_and_skip_target(page, site, path):
    serve_not_found_candidate(page, site)
    page.goto(site[0] + "/" + path)
    headings = page.locator("h1,h2,h3,h4,h5,h6").evaluate_all(
        "nodes => nodes.map(node => ({level: +node.tagName[1], text: node.textContent.trim()}))"
    )
    levels = [heading["level"] for heading in headings]
    assert levels.count(1) == 1 and levels[0] == 1
    assert all(heading["text"] for heading in headings)
    assert all(current <= previous + 1 for previous, current in pairwise(levels))
    # Chromium's accessibility tree checks computed names, including native
    # labels/legends and aria-labels, rather than guessing from HTML attributes.
    session = page.context.new_cdp_session(page)
    tree = session.send("Accessibility.getFullAXTree")["nodes"]
    session.detach()
    named_roles = {"link", "button", "textbox", "combobox", "radio", "checkbox", "image"}
    for node in tree:
        if not node.get("ignored") and node.get("role", {}).get("value") in named_roles:
            assert node.get("name", {}).get("value", "").strip(), node
    assert page.locator("[aria-describedby]").evaluate_all(
        r"nodes => nodes.every(node => node.getAttribute('aria-describedby').split(/\s+/).every(id => document.getElementById(id)))"
    )
    expect(page.locator(".github-mark")).to_have_attribute("aria-hidden", "true")
    expect(page.locator(".github-mark")).to_have_attribute("focusable", "false")
    assert page.locator(".nav-chevron").evaluate_all(
        "nodes => nodes.every(node => getComputedStyle(node).transitionDuration === '0s')"
    )
    if page.locator("#exercise-form").count():
        expect(page.locator("#exercise-feedback")).to_have_attribute("role", "status")
        expect(page.locator("#exercise-feedback")).to_have_attribute("aria-live", "polite")
    page.keyboard.press("Tab")
    expect(page.locator(".skip-link")).to_be_focused()
    page.keyboard.press("Enter")
    page.keyboard.press("Tab")
    assert page.locator(":focus").evaluate("node => !!node.closest('main')")


@pytest.mark.parametrize(("width", "text_scale"), [
    (1440, 1), (1280, 1), (1024, 1), (768, 1), (375, 1), (320, 1),
    (1280, 2), (320, 2),
])
def test_publication_reflow_including_enlarged_text(page, site, width, text_scale):
    serve_not_found_candidate(page, site)
    page.set_viewport_size({"width": width, "height": 900})
    for path in PUBLICATION_PAGES:
        page.goto(site[0] + "/" + path)
        if text_scale == 2:
            page.add_style_tag(content="html { font-size: 200%; }")
        page.evaluate("document.fonts.ready")
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), path
        header_links = [link.bounding_box() for link in page.locator(".site-header a").all()]
        for index, first in enumerate(header_links):
            assert first["width"] > 0 and first["height"] > 0, path
            assert first["x"] >= 0 and first["x"] + first["width"] <= width, path
            for second in header_links[index + 1:]:
                assert (
                    first["x"] + first["width"] <= second["x"]
                    or second["x"] + second["width"] <= first["x"]
                    or first["y"] + first["height"] <= second["y"]
                    or second["y"] + second["height"] <= first["y"]
                ), path
        repository = page.locator(".footer-links").bounding_box()
        assert repository["x"] >= 0 and repository["x"] + repository["width"] <= width
        for option in page.locator(".choice-option").all():
            label = option.bounding_box()
            text = option.locator("span").first.bounding_box()
            assert text["x"] + text["width"] <= label["x"] + label["width"] + 1, path


@pytest.mark.parametrize("path", ["/index.html", "/about/index.html"])
def test_public_pages_do_not_load_course_runtime(page, site, path):
    requests = []
    page.on("request", lambda request: requests.append(request.url))
    page.goto(site[0] + path)
    expect(page.locator("script, #site-data, #answer-key")).to_have_count(0)
    assert not any(url.endswith(("/exercises.js", "/navigation.js")) for url in requests)
    assert any(url.endswith("/assets/styles.css") for url in requests)
    assert page.evaluate("JSON.stringify({...localStorage})") == "{}"


@pytest.mark.parametrize("width", [1280, 1024, 768, 375, 320])
def test_project_people_and_typography_at_required_widths(page, site, width):
    page.set_viewport_size({"width": width, "height": 900})
    names = ["Deise Prina Dutra", "Gustavo Leal Teixeira", "Danilo Duarte Costa", "Jhonatan H. Lopes"]
    for path in ("/index.html", "/about/index.html"):
        page.goto(site[0] + path)
        page.evaluate("document.fonts.ready")
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        for portrait in page.locator(".person-portrait").all():
            box = portrait.bounding_box()
            assert box["width"] == pytest.approx(box["height"], abs=1)
            assert box["width"] >= 64
            assert box["x"] >= 0 and box["x"] + box["width"] <= width
            expect(portrait).to_have_attribute("aria-hidden", "true")
        if path == "/index.html":
            expect(page.locator("main .person, main .person-portrait")).to_have_count(0)
            assert not any(name in page.locator("main").inner_text() for name in names)
            expect(page.get_by_role("heading", name="People", exact=True)).to_have_count(0)
            expect(page.get_by_role("heading", name="Project team", exact=True)).to_have_count(0)
            expect(page.locator('[aria-labelledby="project-heading"] .prose p')).to_have_count(2)
            if width >= 1024:
                hero = page.locator(".page-head").bounding_box()
                course = page.locator("#course").bounding_box()
                gap = course["y"] - hero["y"] - hero["height"]
                ordinary_gap = page.locator("html").evaluate(
                    "node => 3 * parseFloat(getComputedStyle(node).fontSize)"
                )
                assert gap > ordinary_gap
        else:
            expect(page.locator("#team > h2")).to_have_text("Research team")
            assert page.locator("#team > h3").all_text_contents() == ["Coordinators", "Members"]
            assert page.locator('#team [aria-labelledby="coordinators-heading"] .person-name').all_text_contents() == names[:3]
            assert page.locator(".person-portrait span").all_text_contents() == ["DPD", "GLT", "DDC", "JHL"]
            expect(page.locator("#team .person--pending")).to_have_count(6)
            assert page.locator(".person--pending .person-name").all_text_contents() == ["Research team member"] * 6
            assert all(not text.strip() for text in page.locator(".person--pending .person-portrait").all_text_contents())
            expect(page.locator("#data-platform .person-name")).to_have_text(names[3])
            expect(page.locator("#data-platform .person-role")).to_have_text("Data processing and web development")
            expect(page.locator("#data-platform .person-information")).to_have_text(
                "Jhonatan H. Lopes Data processing and web development"
            )
            expect(page.locator("#data-platform .person-contribution")).to_have_count(0)
            assert "Jhonatan cleans and organises" not in page.locator("main").inner_text()
            narrative = page.locator(".about-narrative").bounding_box()
            main = page.locator("main").evaluate("node => node.clientWidth - parseFloat(getComputedStyle(node).paddingLeft) - parseFloat(getComputedStyle(node).paddingRight)")
            assert page.locator(".about-narrative").evaluate("node => getComputedStyle(node).maxInlineSize") == "none"
            if width >= 1024:
                assert narrative["width"] / main > 0.65
            paragraph = page.locator(".about-narrative .prose p").first.bounding_box()
            assert 0.75 <= paragraph["width"] / narrative["width"] <= 1


@pytest.mark.parametrize("path", [
    "/introduction/the-introduction-section-of-research-papers/index.html",
    "/methods/grammar-and-vocabulary-in-the-methods-section/exercise-1/index.html",
    "/methods/grammar-and-vocabulary-in-the-methods-section/exercise-2/index.html",
])
def test_course_main_uses_available_grid_width_with_bounded_prose(page, site, path):
    page.set_viewport_size({"width": 1440, "height": 900})
    page.goto(site[0] + path)
    page.evaluate("document.fonts.ready")
    layout = page.locator(".layout").bounding_box()
    sidebar = page.locator(".course-panel").bounding_box()
    main = page.locator("main").bounding_box()
    assert main["width"] == pytest.approx(layout["width"] - sidebar["width"], abs=1)
    usable = page.locator("main").evaluate("node => node.clientWidth - parseFloat(getComputedStyle(node).paddingLeft) - parseFloat(getComputedStyle(node).paddingRight)")
    assert page.locator("h1").bounding_box()["width"] == pytest.approx(usable, abs=1)
    text = page.locator(".lead, .instructions p:not(.eyebrow)").first
    measure = text.evaluate("node => parseFloat(getComputedStyle(node).maxInlineSize)")
    assert text.bounding_box()["width"] <= measure < usable
    for table in page.locator(".matching-sentences").all():
        assert table.bounding_box()["width"] == pytest.approx(usable, abs=1)
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")


def test_optional_portrait_keeps_fallback_geometry_and_profile_access(page, site, documents, tmp_path, monkeypatch):
    assets = tmp_path / "static"
    shutil.copytree(Path(__file__).resolve().parents[1] / "static", assets)
    (assets / "people").mkdir()
    # Local PNG fixture only: no portrait is fetched or published by this test.
    (assets / "people/test.png").write_bytes((assets / "institutions/logo-ufmg-fale.png").read_bytes())
    first = replace(renderer.COORDINATORS[0], portrait="people/test.png", profile_url="https://example.org/profile")
    monkeypatch.setattr(renderer, "COORDINATORS", (first, *renderer.COORDINATORS[1:]))
    monkeypatch.setattr(renderer, "STATIC", assets)
    output = site[1].parent / "portrait-component"
    build_site(documents, output)
    page.goto(site[0].removesuffix("/study") + "/portrait-component/about/index.html")
    fields = page.locator(".person-portrait")
    image = fields.first.locator("img")
    image.scroll_into_view_if_needed()
    expect(image).to_have_js_property("complete", True)
    assert image.evaluate("node => node.naturalWidth > 0")
    expect(image).to_have_attribute("alt", first.name)
    real, fallback = fields.first.bounding_box(), fields.nth(1).bounding_box()
    assert (real["width"], real["height"]) == pytest.approx((fallback["width"], fallback["height"]), abs=1)
    assert fields.first.get_attribute("aria-hidden") is None
    expect(fields.nth(1)).to_have_attribute("aria-hidden", "true")
    profile = page.locator(".person-profile")
    expect(profile).to_have_attribute("href", first.profile_url)
    profile.focus()
    assert profile.evaluate("node => getComputedStyle(node).outlineStyle") == "solid"
    assert profile.bounding_box()["height"] >= 44


def test_footer_survives_enhanced_navigation_with_portable_urls(page, site):
    page.goto(site[0] + "/methods/index.html")
    page.evaluate("window.footerProbe = document.querySelector('.site-footer')")
    footer = page.get_by_role("contentinfo")
    source = footer.get_by_role("link", name="GitHub repository: coragrarian/academicwriting", exact=True)
    expected_source = "https://github.com/coragrarian/academicwriting"
    expect(source).to_have_attribute("href", expected_source)
    expect(footer.get_by_role("link", name="About", exact=True)).to_have_count(0)
    for heading in ("Purpose of the Methods section", "Exercise 1"):
        page.locator('.page-navigation a[rel="next"]').click()
        expect(page.locator("h1")).to_have_text(heading)
        assert page.evaluate("window.footerProbe === document.querySelector('.site-footer')")
        expect(source).to_have_attribute("href", expected_source)
        expect(page.locator(".course-link")).to_have_attribute("href", f"{site[0]}/index.html#course")
    # The footer has remained below the viewport while URL depth changed.
    # Its lazy images must still load from the original site's asset directory.
    for image in footer.locator("img").all():
        image.scroll_into_view_if_needed()
        expect(image).to_have_js_property("complete", True)
        assert image.evaluate("node => node.naturalWidth > 0")
        assert image.evaluate("node => node.currentSrc").startswith(f"{site[0]}/assets/institutions/")
    page.go_back()
    expect(page.locator("h1")).to_have_text("Purpose of the Methods section")
    page.go_forward()
    expect(page.locator("h1")).to_have_text("Exercise 1")
    assert page.evaluate("window.footerProbe === document.querySelector('.site-footer')")
    expect(source).to_have_attribute("href", expected_source)
    page.locator(".about-link").click()
    expect(page.locator("h1")).to_have_text("About Academic Writing for Agrarian Sciences")
    assert page.evaluate("window.footerProbe") is None


@pytest.mark.parametrize("width", [1440, 1280, 1024, 768, 375, 320])
def test_public_pages_and_shared_header_at_required_widths(page, site, width):
    page.set_viewport_size({"width": width, "height": 900})
    for path in (
        "/index.html", "/about/index.html", "/introduction/index.html",
        "/methods/index.html",
        "/results/grammar-and-vocabulary-in-the-results-section/exercise-7/index.html",
    ):
        page.goto(site[0] + path)
        page.evaluate("document.fonts.ready")
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), path
        about = page.locator(".about-link")
        expect(about).to_be_visible()
        assert about.bounding_box()["height"] >= 44
        about.focus()
        assert about.evaluate("node => getComputedStyle(node).outlineStyle") == "solid"
        course = page.locator(".course-link")
        expect(course).to_be_visible()
        assert course.bounding_box()["height"] >= 44
        assert course.evaluate("node => node.href") == f"{site[0]}/index.html#course"
        links = page.locator(".site-header a").all()
        for index, link in enumerate(links):
            box = link.bounding_box()
            assert box["x"] >= 0 and box["x"] + box["width"] <= width
            for other in links[index + 1:]:
                other_box = other.bounding_box()
                assert (
                    box["x"] + box["width"] <= other_box["x"]
                    or other_box["x"] + other_box["width"] <= box["x"]
                    or box["y"] + box["height"] <= other_box["y"]
                    or other_box["y"] + other_box["height"] <= box["y"]
                ), path
        for image in page.locator(".institution-logo").all():
            image.scroll_into_view_if_needed()
            expect(image).to_be_visible()
            expect(image).to_have_js_property("complete", True)
            assert image.evaluate("node => node.naturalWidth > 0")
            box = image.bounding_box()
            natural_ratio = image.evaluate("node => node.naturalWidth / node.naturalHeight")
            assert box["width"] / box["height"] == pytest.approx(natural_ratio, rel=0.01)
            assert box["x"] >= 0 and box["x"] + box["width"] <= width
        footer = page.get_by_role("contentinfo")
        expect(footer).to_have_count(1)
        expect(footer.get_by_role("link", name="About", exact=True)).to_have_count(0)
        expect(footer.locator(".footer-links a")).to_have_count(1)
        institution_group = footer.locator(".footer-institutions").bounding_box()
        provenance = footer.locator(".footer-provenance")
        expect(provenance).to_have_text("Developed at UFMG · Supported by FAPEMIG and CAPES · APQ-01173-22")
        provenance_box = provenance.bounding_box()
        repository = footer.get_by_role("link", name="GitHub repository: coragrarian/academicwriting", exact=True)
        expect(repository).to_have_text("coragrarian/academicwriting")
        expect(footer.get_by_role("link", name="Source code", exact=True)).to_have_count(0)
        expect(repository.locator("svg")).to_have_attribute("aria-hidden", "true")
        source_link = repository.bounding_box()
        assert provenance_box["y"] >= institution_group["y"] + institution_group["height"]
        assert source_link["y"] >= provenance_box["y"] + provenance_box["height"]
        layout = page.locator(".layout").bounding_box()
        assert footer.bounding_box()["y"] >= layout["y"] + layout["height"]
        for name, href in (
            ("Faculdade de Letras da UFMG", "https://www.letras.ufmg.br/site/"),
            ("FAPEMIG", "https://fapemig.br/"),
            ("CAPES", "https://www.gov.br/capes/pt-br/"),
            ("GitHub repository: coragrarian/academicwriting", "https://github.com/coragrarian/academicwriting"),
        ):
            link = footer.get_by_role("link", name=name, exact=True)
            expect(link).to_have_attribute("href", href)
            assert link.get_attribute("target") is None
            assert link.bounding_box()["height"] >= 44
        if width >= 768:
            marks = [mark.bounding_box() for mark in page.locator(".footer-institutions a").all()]
            assert all(
                following["x"] >= current["x"] + current["width"]
                for current, following in pairwise(marks)
            )
            centres = [mark["y"] + mark["height"] / 2 for mark in marks]
            assert centres == pytest.approx([centres[0]] * 3, abs=0.02)
        if path == "/index.html":
            expect(page.locator(".project-actions, .project-start, .page-head a")).to_have_count(0)
            expect(page.get_by_role("link", name="Start the course", exact=True)).to_have_count(0)
            expect(page.get_by_role("link", name="About the project", exact=True)).to_have_count(0)
            expect(page.locator("#course .contents-link")).to_have_count(3)
            assert page.locator(".contents-title").all_text_contents() == [
                "Introduction", "Methods", "Results",
            ]
            expect(page.locator("#course button, #course .action-link, .page-head .eyebrow")).to_have_count(0)
            expect(page.get_by_role("heading", name="Course contents", exact=True)).to_have_count(1)
            expect(page.locator(".page-head .lead")).to_have_text(
                "An interactive self-study resource for students and researchers writing research articles in the Agrarian Sciences."
            )
            expect(page.get_by_role("link", name="About the research project", exact=True)).to_have_attribute(
                "href", "about/index.html"
            )
            assert page.locator(".contents-number").all_text_contents() == ["01", "02", "03"]
            assert page.locator(".contents-counts").all_text_contents() == [
                "6 subsections · 14 exercises", "2 subsections · 7 exercises", "2 subsections · 9 exercises",
            ]
            start = page.locator(".contents-link").first
            expect(start).to_have_attribute("href", "introduction/index.html")
            assert start.bounding_box()["height"] >= 44
            rows = [row.bounding_box() for row in page.locator(".contents-link").all()]
            assert all(
                following["y"] >= current["y"] + current["height"]
                for current, following in pairwise(rows)
            )
            for link in page.locator(".contents-link").all():
                assert link.bounding_box()["height"] >= 44
                link.focus()
                assert link.evaluate("node => getComputedStyle(node).outlineStyle") == "solid"
        if path in {"/index.html", "/about/index.html"}:
            expect(page.locator(".public-layout")).to_have_count(1)
            expect(page.locator("script, #site-data, main .institution-logo")).to_have_count(0)
            expect(page.locator(".course-panel, [data-site-navigation], [data-progress-module], [data-progress-other-module]")).to_have_count(0)
            public_edge = page.locator("main").evaluate("node => node.getBoundingClientRect().x + parseFloat(getComputedStyle(node).paddingLeft)")
            assert page.locator(".site-name").bounding_box()["x"] == pytest.approx(public_edge, abs=0.02)
            if path == "/about/index.html":
                narrative = page.locator(".about-narrative").bounding_box()
                facts = page.locator(".project-facts").bounding_box()
                expect(page.locator(".project-facts dl")).to_have_count(1)
                if width >= 1024:
                    assert facts["x"] >= narrative["x"] + narrative["width"]
                    assert facts["y"] == pytest.approx(narrative["y"])
                else:
                    assert facts["y"] >= narrative["y"] + narrative["height"]
        else:
            expect(page.locator(".course-panel, [data-site-navigation]")).to_have_count(1)
            expect(page.locator(".module-link")).to_be_visible()
            expect(page.locator("#site-data, script[src$='exercises.js'], script[src$='navigation.js']")).to_have_count(3)


def test_authorised_content_changes_preserve_existing_progress(page, site):
    page.goto(site[0] + "/index.html")
    page.evaluate("""() => {
      const previous = 'introduction--further-practice--exercise-1';
      const gap = 'introduction--indicating-a-research-gap--exercise-1';
      localStorage.setItem('agrarian-writing-v2:introduction', JSON.stringify({
        progress: {[previous]: 'completed', [gap]: 'completed'},
        responses: {
          [previous]: {'context-q1': [0], 'context-q2': [2], 'context-q3': [6], 'context-q4': [5], 'context-q5': [4], 'context-q6': [1], 'context-q7': [3]},
          [gap]: {'context-q1': ' HAS  primarily concentrated ', 'context-q2': 'have been found', 'context-q3': 'have only examined'}
        },
        checked: {[previous]: true, [gap]: true}
      }));
    }""")
    page.reload()
    page.locator(".contents-link").first.click()
    expect(page.locator('[data-progress-module="introduction"]')).to_have_text("2/14")
    expect(page.locator('.course-panel [data-progress-section="grammar-and-vocabulary-in-the-introduction-section"]')).to_have_text("1/3")
    saved = page.evaluate("JSON.parse(localStorage.getItem('agrarian-writing-v2:introduction'))")
    current = "introduction--grammar-and-vocabulary-in-the-introduction-section--exercise-1"
    assert saved["progress"][current] == "completed"
    assert len(saved["responses"][current]) == 7
    assert saved["responses"][current]["context-q1"] == [0]
    assert saved["checked"][current] is True
    assert not any("further-practice" in identifier for identifier in saved["progress"])
    open_exercise(page, site, "introduction", "indicating-a-research-gap", 1)
    expect(page.locator("#context-q1")).to_have_value("has concentrated")
    expect(page.locator("#context-q3")).to_have_value("have examined")
    expect(page.locator("[data-current-status]")).to_have_text("Completed")
    page.locator("#reset-exercise").click()
    page.reload()
    expect(page.locator("[data-current-status]")).to_have_text("Not started")
    expect(page.locator('[data-progress-module="introduction"]')).to_have_text("1/14")
    open_exercise(page, site, "introduction", "grammar-and-vocabulary-in-the-introduction-section", 1)
    expect(page.locator("[data-current-status]")).to_have_text("Completed")
    page.locator("#reset-exercise").click()
    page.reload()
    expect(page.locator("[data-current-status]")).to_have_text("Not started")
    expect(page.locator('[data-progress-module="introduction"]')).to_have_text("0/14")


def test_every_sequential_course_page_forward_and_backward(page, site, documents):
    sequence = []
    for document in documents:
        module = f"/{document.slug}"
        sequence.append(f"{module}/index.html")
        for section in document.sections:
            subsection = f"{module}/{section.slug}"
            sequence.append(f"{subsection}/index.html")
            sequence.extend(
                f"{subsection}/{exercise.slug}/index.html" for exercise in section.exercises
            )
    assert len(sequence) == 43
    home = f"{site[0]}/index.html"
    page.goto(site[0] + sequence[0])
    visited = []
    while page.url != home:
        current = page.url.removeprefix(site[0])
        assert current not in visited, f"Repeated sequential page: {current}"
        visited.append(current)
        expect(page.locator('.course-panel [aria-current="page"]')).to_have_count(1)
        forward = page.locator('.page-navigation a[rel="next"], [data-course-terminal]')
        expect(forward).to_have_count(1)
        target = forward.evaluate("node => node.href")
        if current == sequence[-1]:
            expect(forward).to_have_text("Back to contents")
            expect(page.locator('.page-navigation a[rel="next"]')).to_have_count(0)
            assert target == home
        forward.click()
        expect(page).to_have_url(target)
    assert visited == sequence
    expect(page.locator('.page-navigation a[rel="next"]')).to_have_count(0)
    expect(page.locator(".course-panel, [data-site-navigation]")).to_have_count(0)

    page.goto(site[0] + sequence[-1])
    backwards = []
    while page.url != home:
        current = page.url.removeprefix(site[0])
        assert current not in backwards, f"Repeated Previous page: {current}"
        backwards.append(current)
        previous = page.locator('.page-navigation a[rel="prev"]')
        target = previous.evaluate("node => node.href")
        previous.click()
        expect(page).to_have_url(target)
    assert backwards == list(reversed(sequence))


@pytest.mark.parametrize("width", [1280, 1024, 768, 375, 320])
def test_editorial_components_and_contents_at_required_widths(page, site, width):
    page.set_viewport_size({"width": width, "height": 900})
    paths = [
        "/index.html",
        "/about/index.html",
        "/introduction/index.html",
        "/introduction/the-introduction-section-of-research-papers/index.html",
        "/introduction/giving-a-context-background/index.html",
        "/methods/grammar-and-vocabulary-in-the-methods-section/exercise-2/index.html",
        "/methods/purpose-of-the-methods-section/exercise-1/index.html",
        "/results/grammar-and-vocabulary-in-the-results-section/exercise-4/index.html",
        "/introduction/the-introduction-section-of-research-papers/exercise-1/index.html",
    ]
    for path in paths:
        page.goto(site[0] + path)
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), path
        navigator = page.locator("[data-course-navigator]")
        if path in {"/index.html", "/about/index.html"}:
            expect(page.locator(".course-panel, [data-site-navigation], .course-toggle")).to_have_count(0)
            expect(navigator).to_have_count(0)
        else:
            assert navigator.evaluate("node => node.open") == (width > 768)
            if width <= 768:
                page.locator(".course-toggle").click()
                expect(navigator).to_have_attribute("open", "")
                assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), path
        for control in page.locator("select, input[type=text], button").all():
            box = control.bounding_box()
            assert box["x"] >= 0 and box["x"] + box["width"] <= width, path
        expect(page.locator(".content-card, .card-grid, .section-card")).to_have_count(0)

        rows = page.locator(".overview-link")
        if rows.count():
            positions = [row.bounding_box() for row in rows.all()]
            assert all(
                following["y"] >= current["y"] + current["height"]
                for current, following in pairwise(positions)
            )
            rows.first.focus()
            page.keyboard.press("Tab")
            page.keyboard.press("Shift+Tab")
            assert rows.first.evaluate("node => getComputedStyle(node).outlineStyle") == "solid"
        for item in page.locator(".exercise-item").all():
            styles = item.evaluate("""node => {
              const style = getComputedStyle(node);
              return [style.borderLeftWidth, style.borderRightWidth, style.borderBottomWidth,
                style.borderRadius, style.paddingLeft, style.paddingRight, style.backgroundColor];
            }""")
            assert styles == ["0px"] * 6 + ["rgba(0, 0, 0, 0)"]
        for row in page.locator(".choice-option").all():
            assert row.bounding_box()["height"] >= 43.5
        for cue in page.locator(".typed-gap + .response-feedback + em").all():
            styles = cue.evaluate("""node => {
              const style = getComputedStyle(node);
              return [style.fontStyle, style.fontWeight, style.borderWidth, style.backgroundColor];
            }""")
            assert styles == ["italic", "600", "0px", "rgba(0, 0, 0, 0)"]
        if path.endswith("the-introduction-section-of-research-papers/exercise-1/index.html"):
            expect(page.locator(".exercise-head > .eyebrow")).to_have_count(0)
        if path.endswith("methods-section/exercise-2/index.html"):
            expect(page.locator(".exercise-head > .eyebrow")).to_have_text("2 of 4")

    summary = page.locator('.nav-module-group > summary').first
    assert summary.evaluate("node => getComputedStyle(node).listStyleType") == "none"
    assert summary.evaluate("node => getComputedStyle(node, '::before').content") == "none"
    was_open = summary.locator("xpath=..").evaluate("node => node.open")
    summary.focus()
    page.keyboard.press("Space")
    assert summary.locator("xpath=..").evaluate("node => node.open") != was_open
    assert summary.evaluate("node => getComputedStyle(node).outlineStyle") == "solid"
    page.keyboard.press("Enter")
    assert summary.locator("xpath=..").evaluate("node => node.open") == was_open


def test_orientation_matching_order_and_saved_semantic_responses(page, site):
    page.goto(site[0] + "/index.html")
    exercise = "introduction--the-introduction-section-of-research-papers--exercise-1"
    responses = {f"context-q{number}": [number - 1] for number in range(1, 5)}
    # Seed semantic source order before loading reordered controls: restoring
    # by row position could otherwise pass a test using only fresh answers.
    page.evaluate(
        """({exercise, responses}) => {
          localStorage.setItem('agrarian-writing-v2:introduction', JSON.stringify({
            progress: {[exercise]: 'completed'}, responses: {[exercise]: responses},
            checked: {[exercise]: true}
          }));
        }""",
        {"exercise": exercise, "responses": responses},
    )
    key = open_exercise(page, site, "introduction", "the-introduction-section-of-research-papers", 1)
    expect(page.locator("[data-current-status]")).to_have_text("Completed")
    assert page.locator(".matching-question label").all_text_contents() == [
        "State the research objectives.",
        "Review previous research.",
        "Comment on the importance of the topic and/or provide general background.",
        "Introduce a research gap.",
    ]
    assert page.locator(".matching-question select").evaluate_all(
        "nodes => nodes.map(node => node.value)"
    ) == ["3", "1", "0", "2"]
    assert {identifier: question["expected"] for identifier, question in key["questions"].items()} == responses
    page.locator(".matching-question select").first.focus()
    page.keyboard.press("Home")
    page.keyboard.press("ArrowDown")
    page.keyboard.press("Enter")
    expect(page.locator("#context-q4")).to_have_value("0")
    page.locator("button[type=submit]").click()
    expect(page.locator("#context-q4")).to_have_attribute("aria-invalid", "true")
    expect(page.locator("#exercise-feedback")).to_have_text(
        "3 of 4 responses correct. Review Match 1."
    )
    respond(page, key)
    page.locator("button[type=submit]").click()
    expect(page.locator("[data-current-status]")).to_have_text("Completed")
    page.reload()
    expect(page.locator("[data-current-status]")).to_have_text("Completed")
