"""Browser contracts exercised independently of the canonical course."""

import json
from itertools import pairwise

import pytest
from browser_support import respond
from playwright.sync_api import expect
from site_support import PRODUCTION_URL, course_sequence

pytestmark = pytest.mark.browser


def exercise_path(documents, kind):
    for doc in documents:
        for section in doc.sections:
            for exercise in section.exercises:
                if any(question.kind == kind for question in exercise.questions):
                    return f"{doc.slug}/{section.slug}/{exercise.slug}/index.html"
    raise AssertionError(f"Fixture does not exercise {kind}")


def assert_accessible_structure(page):
    headings = page.locator("h1,h2,h3,h4,h5,h6").evaluate_all(
        "nodes => nodes.map(n => [+n.tagName[1], n.textContent.trim()])"
    )
    assert [level for level, _ in headings].count(1) == 1 and headings[0][0] == 1
    assert all(text for _, text in headings)
    assert all(current[0] <= previous[0] + 1 for previous, current in pairwise(headings))
    assert page.locator("[id]").evaluate_all("nodes => new Set(nodes.map(n => n.id)).size === nodes.length")
    assert page.locator("[aria-describedby]").evaluate_all(
        r"nodes => nodes.every(n => n.getAttribute('aria-describedby').split(/\s+/).every(id => document.getElementById(id)))"
    )
    session = page.context.new_cdp_session(page)
    try:
        nodes = session.send("Accessibility.getFullAXTree")["nodes"]
    finally:
        session.detach()
    for node in nodes:
        if not node.get("ignored") and node.get("role", {}).get("value") in {
            "link", "button", "textbox", "combobox", "radio", "checkbox", "image",
        }:
            assert node.get("name", {}).get("value", "").strip(), node


@pytest.mark.parametrize("kind", ["single-choice", "multi-select", "inline-choice", "gap", "typed-gap", "matching"])
def test_interaction_retry_feedback_reset_and_saved_response_contract(page, synthetic_site, synthetic_documents, kind):
    path = exercise_path(synthetic_documents, kind)
    page.goto(f"{synthetic_site[0]}/{path}")
    expect(page.locator("#exercise-form")).to_have_attribute("data-exercise-initialised", "true")
    assert_accessible_structure(page)
    key = json.loads(page.locator("#answer-key").text_content())
    site_data = json.loads(page.locator("#site-data").text_content())
    module = site_data["module"]
    exercise = page.locator("#exercise-form").get_attribute("data-exercise-id")
    wrong = next(iter(key["questions"]))
    respond(page, key, wrong_id=wrong)
    expect(page.locator("[data-current-status]")).to_have_text("In progress")
    page.locator("button[type=submit]").click()
    expect(page.locator(f'[data-question="{wrong}"]')).to_have_attribute("aria-invalid", "true")
    feedback = page.locator("#exercise-feedback").text_content()
    assert "Review" in feedback
    if kind == "single-choice":
        expect(page.locator("[data-item-feedback]")).to_contain_text("This is the other label.")
        expect(page.locator("[data-item-feedback]")).not_to_contain_text("requested label")
    page.reload()
    expect(page.locator("#exercise-feedback")).to_have_text(feedback)
    expect(page.locator(f'[data-question="{wrong}"]')).to_have_attribute("aria-invalid", "true")
    respond(page, key, normalised=True)
    expect(page.locator("#exercise-feedback")).to_be_empty()
    page.locator("button[type=submit]").click()
    expect(page.locator("[data-current-status]")).to_have_text("Completed")
    expect(page.locator(f'[data-progress-module="{module}"]')).to_have_text(f"1/{len(site_data['modules'][module])}")
    expect(page.locator(".worked-model [data-question]")).to_have_count(0)
    if kind == "single-choice":
        expect(page.locator("[data-item-feedback]")).to_contain_text("This is the requested label.")
    if kind == "multi-select":
        question = next(q for q in key["questions"].values() if q["kind"] == kind)
        control = page.locator('[data-question="item-a-q1"]')
        control.locator(f'input[value="{question["expected"][0]}"]').uncheck()
        page.locator("button[type=submit]").click()
        expect(page.locator("[data-current-status]")).to_have_text("In progress")
        respond(page, key)
        control.locator('input[value="1"]').check()
        page.locator("button[type=submit]").click()
        expect(page.locator("[data-current-status]")).to_have_text("In progress")
        respond(page, key)
    if kind == "typed-gap":
        control = page.locator(f'[data-question="{wrong}"]')
        control.fill(key["questions"][wrong]["expected"] + ".")
        page.locator("button[type=submit]").click()
        expect(control).to_have_attribute("aria-invalid", "true")
        respond(page, key, normalised=True)
    page.locator("button[type=submit]").click()
    saved = page.evaluate("module => JSON.parse(localStorage.getItem(`agrarian-writing-v2:${module}`))", module)
    assert set(saved["responses"][exercise]) == set(key["questions"])
    assert saved["checked"][exercise] is True
    page.reload()
    expect(page.locator("[data-current-status]")).to_have_text("Completed")
    assert page.evaluate("module => JSON.parse(localStorage.getItem(`agrarian-writing-v2:${module}`))", module) == saved
    page.locator("#reset-exercise").click()
    expect(page.locator("[data-current-status]")).to_have_text("Not started")
    expect(page.locator("[data-result], input:checked")).to_have_count(0)
    expect(page.locator("[data-item-feedback]:visible, #shared-feedback:visible")).to_have_count(0)
    assert page.locator("select, input[type=text]").evaluate_all("nodes => nodes.every(n => n.value === '')")
    page.reload()
    expect(page.locator("[data-current-status]")).to_have_text("Not started")


def test_entire_synthetic_sequence_from_home_and_back_with_generic_shell(page, synthetic_site, synthetic_documents):
    sequence = course_sequence(synthetic_documents)
    base = synthetic_site[0]
    home = f"{base}/index.html"
    page.goto(home)
    assert page.locator(".contents-link").evaluate_all("nodes => nodes.map(n => n.getAttribute('href'))") == [
        f"{doc.slug}/index.html" for doc in synthetic_documents
    ]
    page.locator(".contents-link").first.click()
    visited = []
    while page.url != home:
        current = page.url.removeprefix(base + "/")
        assert current not in visited, current
        visited.append(current)
        assert current == sequence[len(visited) - 1].as_posix()
        expect(page.locator('.course-panel [aria-current="page"]')).to_have_count(1)
        expect(page.locator(".nav-module-group")).to_have_count(len(synthetic_documents))
        expect(page.locator('script[src$="exercises.js"], script[src$="navigation.js"]')).to_have_count(2)
        assert page.locator('link[rel="stylesheet"]').evaluate("node => node.sheet.href") == f"{base}/assets/styles.css"
        expect(page.locator('link[rel="canonical"]')).to_have_attribute("href", PRODUCTION_URL + current.removesuffix("index.html"))
        module = json.loads(page.locator("#site-data").text_content())["module"]
        page.evaluate("window.navigationProbe = document.querySelector('.site-footer')")
        forward = page.locator('.page-navigation a[rel="next"], [data-course-terminal]')
        target = forward.evaluate("node => node.href")
        assert target != page.url
        if current == sequence[-1].as_posix():
            expect(forward).to_have_text("Back to contents")
            assert target == home
        forward.click()
        expect(page).to_have_url(target)
        if target != home and target.removeprefix(base + "/").split("/")[0] == module:
            assert page.evaluate("window.navigationProbe === document.querySelector('.site-footer')")
            expect(page.locator("h1")).to_be_focused()
        else:
            assert page.evaluate("window.navigationProbe") is None
    assert visited == [path.as_posix() for path in sequence]
    expect(page.locator(".course-panel, .page-navigation, #site-data")).to_have_count(0)
    page.goto(f"{base}/{sequence[-1].as_posix()}")
    backwards = []
    while page.url != home:
        current = page.url.removeprefix(base + "/")
        assert current not in backwards, current
        backwards.append(current)
        previous = page.locator('.page-navigation a[rel="prev"]')
        target = previous.evaluate("node => node.href")
        previous.click()
        expect(page).to_have_url(target)
    assert backwards == [path.as_posix() for path in reversed(sequence)]


@pytest.mark.parametrize("mode", ["navigation-disabled", "javascript-disabled", "file-preview"])
def test_fourth_module_direct_reload_new_tab_and_ordinary_links(browser, synthetic_site, synthetic_documents, mode):
    context = browser.new_context(java_script_enabled=mode != "javascript-disabled", reduced_motion="reduce")
    errors = []
    context.on("page", lambda page: page.on("pageerror", lambda error: errors.append(str(error))))
    try:
        if mode == "navigation-disabled":
            context.route("**/navigation.js", lambda route: route.abort())
        page = context.new_page()
        path = exercise_path(synthetic_documents, "matching")
        url = (synthetic_site[1] / path).as_uri() if mode == "file-preview" else f"{synthetic_site[0]}/{path}"
        page.goto(url)
        assert "enhanced-navigation" not in (page.locator("html").get_attribute("class") or "")
        expect(page.locator("h1")).to_have_text("Exercise 1")
        if mode != "javascript-disabled":
            key = json.loads(page.locator("#answer-key").text_content())
            respond(page, key)
            page.locator("button[type=submit]").click()
            expect(page.locator("[data-current-status]")).to_have_text("Completed")
        else:
            # Playwright's text matcher excludes noscript even with JS disabled.
            assert "pages and navigation remain available" in page.locator("noscript").text_content()
            expect(page.locator("noscript p")).to_be_visible()
        page.reload()
        tab = context.new_page()
        tab.goto(url)
        expect(tab.locator("h1")).to_have_text("Exercise 1")
        if mode != "javascript-disabled":
            expect(page.locator("[data-current-status]")).to_have_text("Completed")
            expect(tab.locator("[data-current-status]")).to_have_text("Completed")
        tab.close()
        page.locator('.page-navigation a[rel="prev"]').click()
        expect(page.locator("h1")).to_have_text(synthetic_documents[-1].sections[0].title)
        assert not errors, errors
    finally:
        context.close()


def test_feedback_local_overrides_shared_and_obsolete_progress_does_not_count(page, synthetic_site, synthetic_documents):
    page.goto(synthetic_site[0] + "/index.html")
    page.evaluate("""() => localStorage.setItem('agrarian-writing-v2:gamma', JSON.stringify({
      progress: {'removed--exercise-1': 'completed'}, responses: {}, checked: {}
    }))""")
    page.goto(f"{synthetic_site[0]}/{exercise_path(synthetic_documents, 'typed-gap')}")
    expect(page.locator('[data-progress-module="gamma"]')).to_have_text("0/1")
    key = json.loads(page.locator("#answer-key").text_content())
    respond(page, key, wrong_id="item-b-q1")
    page.locator("button[type=submit]").click()
    expect(page.locator("#exercise-feedback")).to_have_text("1 of 2 items correct. Review Item B.")
    expect(page.locator("#item-a-feedback")).to_contain_text("first local label agrees")
    expect(page.locator("#item-a-feedback .gap-feedback")).to_contain_text("local explanation replaces")
    expect(page.locator("#item-b-feedback .gap-feedback")).to_contain_text("Use the second label.")
    expect(page.locator("#shared-feedback")).to_have_text("Review the labels.")
    respond(page, key)
    page.locator("button[type=submit]").click()
    expect(page.locator("#shared-feedback")).to_have_text("The labels agree.")
    expect(page.locator('[data-progress-module="gamma"]')).to_have_text("1/1")
    page.locator('.course-panel [data-module-overview="delta"]').evaluate("node => location.assign(node.href)")
    expect(page.locator("h1")).to_have_text(synthetic_documents[-1].title)
    expect(page.locator('[data-progress-module="gamma"]')).to_have_text("1/1")
    expect(page.locator('[data-progress-module="delta"]')).to_have_text("0/1")


@pytest.mark.parametrize(("width", "text_scale"), [(1280, 1), (768, 1), (375, 1), (320, 1), (1280, 2), (320, 2)])
def test_synthetic_reflow_controls_navigation_and_accessibility(page, synthetic_site, synthetic_documents, width, text_scale):
    page.set_viewport_size({"width": width, "height": 900})
    paths = ["index.html", "about/index.html"] + [path.as_posix() for path in course_sequence(synthetic_documents)]
    for path in paths:
        page.goto(f"{synthetic_site[0]}/{path}")
        if text_scale == 2:
            page.add_style_tag(content="html { font-size: 200%; }")
        page.evaluate("document.fonts.ready")
        if page.locator("#exercise-form").count():
            respond(page, json.loads(page.locator("#answer-key").text_content()), normalised=True)
            page.locator("button[type=submit]").click()
            expect(page.locator("[data-current-status]")).to_have_text("Completed")
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), (path, width, text_scale)
        assert_accessible_structure(page)
        if page.locator(".course-toggle").is_visible():
            page.locator(".course-toggle").focus()
            page.keyboard.press("Enter")
            expect(page.locator("[data-course-navigator]")).to_have_attribute("open", "")
        for control in page.locator("select, input[type=text], button, .site-header a").all():
            box = control.bounding_box()
            assert box["x"] >= 0 and box["x"] + box["width"] <= width + 1, (path, box)
            control.focus()
            expect(control).to_be_focused()
        for row in page.locator(".matching-question").all():
            assert row.locator("label").bounding_box()["width"] >= row.bounding_box()["width"] / 2
