"""Real-browser regression checks. Run explicitly with pytest -m browser."""

import json
import os
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from itertools import pairwise
from pathlib import Path

import pytest
from playwright.sync_api import expect, sync_playwright

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


def test_progress_is_independent_between_modules_and_visible_on_home(page, site):
    for module, section, number in [CASES[0], CASES[3], CASES[-1]]:
        key = open_exercise(page, site, module, section, number)
        respond(page, key)
        page.locator("button[type=submit]").click()
    page.evaluate("window.fullNavigationProbe = 21")
    page.locator(".nav-home").click()
    expect(page.locator("h1")).to_have_text("Academic Writing for Agrarian Sciences")
    assert page.evaluate("window.fullNavigationProbe") is None
    for module, total in [("introduction", 14), ("methods", 7), ("results", 9)]:
        expect(page.locator(f'[data-progress-other-module="{module}"]')).to_have_text(
            f"1/{total}"
        )
    page.locator(".feature-link").first.click()
    expect(page.locator("h1")).to_have_text("The Introduction section")
    expect(page.locator('[data-progress-module="introduction"]')).to_have_text("1/14")


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
    expect(page.locator(".nav-module-group")).to_have_count(3)
    expect(page.locator(".nav-section-group")).to_have_count(10)
    expect(page.locator(".course-panel [data-exercise-link]")).to_have_count(30)
    expect(page.locator('.course-panel [aria-current="page"]')).to_have_count(0 if level == "about" else 1)
    expect(page.locator('[aria-current="page"]')).to_have_count(1)
    assert page.locator(".nav-module-group[open]").count() == (0 if level in {"home", "about"} else 1)
    assert page.locator(".nav-section-group[open]").count() == (1 if level in {"section", "exercise"} else 0)
    if level not in {"home", "about"}:
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
    page.locator('[data-nav-node="module:results"] > summary').click()
    page.locator('[data-nav-node="section:results:grammar-and-vocabulary-in-the-results-section"] > summary').click()
    page.locator('.course-panel [data-exercise-link="results--grammar-and-vocabulary-in-the-results-section--exercise-3"]').click()
    expect(page.locator("h1")).to_have_text("Exercise 3")
    expect(page.locator(".worked-model")).to_be_visible()
    context.close()


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
    expect(page.locator('[data-progress-module="methods"]')).to_have_text("1/7")
    page.locator(".site-name").click()
    expect(page.locator('[data-progress-other-module="methods"]')).to_have_text("1/7")
    assert page.evaluate("JSON.stringify({...localStorage})") == storage


def test_public_page_links_and_skip_link_work_without_javascript(browser, site):
    context = browser.new_context(java_script_enabled=False)
    page = context.new_page()
    page.goto(site[0] + "/index.html")
    page.keyboard.press("Tab")
    expect(page.get_by_role("link", name="Skip to content")).to_be_focused()
    page.keyboard.press("Enter")
    assert page.url.endswith("#main")
    page.get_by_role("link", name="Explore the course", exact=True).click()
    assert page.url.endswith("#course")
    expect(page.locator("#course")).to_be_in_viewport()
    page.get_by_role("link", name="About the project", exact=True).click()
    expect(page.locator("h1")).to_have_text("About Academic Writing for Agrarian Sciences")
    expect(page.get_by_role("link", name="Academic Writing repository")).to_have_attribute(
        "href", "https://github.com/coragrarian/academicwriting"
    )
    page.locator(".site-name").click()
    expect(page.locator("h1")).to_have_text("Academic Writing for Agrarian Sciences")
    context.close()


@pytest.mark.parametrize("width", [1280, 768, 375, 320])
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
        if path == "/index.html":
            for action in page.locator(".project-actions a").all():
                assert action.bounding_box()["height"] >= 44
            expect(page.locator("#course .overview-link")).to_have_count(3)
        if path not in {"/index.html", "/about/index.html"}:
            expect(page.locator(".module-link")).to_be_visible()


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
    expect(page.locator('[data-progress-module="introduction"]')).to_have_text("2/14")
    expect(page.locator('[data-progress-section="grammar-and-vocabulary-in-the-introduction-section"]')).to_have_text("1/3")
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


@pytest.mark.parametrize("width", [1280, 768, 375, 320])
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
