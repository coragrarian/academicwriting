"""Homepage progress must use the same stored completion contract as the course."""

import json

import pytest
from browser_support import open_exercise, respond
from playwright.sync_api import expect

pytestmark = [pytest.mark.browser, pytest.mark.canonical]


def seed_progress(page, counts):
    """Seed saved completion, retaining stale and draft records to test counting."""
    modules = json.loads(page.locator("#site-data").text_content())["modules"]
    records = {}
    for (module, ids), count in zip(modules.items(), counts, strict=True):
        progress = dict.fromkeys(ids[:count], "completed")
        progress["removed--exercise"] = "completed"
        if count < len(ids):
            progress[ids[count]] = "in-progress"
        records[f"agrarian-writing-v2:{module}"] = json.dumps({
            "progress": progress, "responses": {}, "checked": {},
        })
    records["unrelated-preference"] = "completed"
    page.evaluate("records => Object.entries(records).forEach(([key, value]) => localStorage.setItem(key, value))", records)
    return modules


@pytest.mark.parametrize(("counts", "label", "destination"), [
    ([0, 0, 0], "Begin with Introduction", "introduction/index.html"),
    ([2, 0, 0], "Continue with Introduction", "introduction/index.html"),
    ([14, 2, 0], "Continue with Methods", "methods/index.html"),
    ([14, 7, 0], "Continue with Results", "results/index.html"),
    ([14, 7, 9], "Review the course", "#course"),
    ([0, 1, 0], "Continue with Introduction", "introduction/index.html"),
])
def test_home_progress_states_entry_and_course_agreement(page, site, counts, label, destination):
    page.goto(site[0] + "/index.html")
    modules = seed_progress(page, counts)
    storage = page.evaluate("JSON.stringify({...localStorage})")
    for _ in range(2):
        page.reload()
        entry = page.locator("[data-home-entry]")
        expect(entry).to_have_text(label)
        expect(entry).to_have_attribute("href", destination)
        for (module, ids), count in zip(modules.items(), counts, strict=True):
            region = page.locator(f'[data-home-module="{module}"] .contents-progress')
            expect(region).to_be_visible()
            status = "Completed" if count == len(ids) else f"{count} of {len(ids)} exercises completed" if count else "Not started"
            expect(region.locator(".contents-progress-status")).to_have_text(status)
            ratio = region.locator(".contents-progress-fill").evaluate("node => parseFloat(node.style.width)")
            assert ratio == pytest.approx(count / len(ids) * 100)
            expect(region.locator(".contents-progress-track")).to_have_attribute("aria-hidden", "true")
        assert page.evaluate("JSON.stringify({...localStorage})") == storage
    entry.focus()
    page.keyboard.press("Enter")
    expect(page).to_have_url(site[0] + "/index.html#course" if destination == "#course" else f"{site[0]}/{destination}")
    page.goto(site[0] + "/introduction/index.html")
    for (module, ids), count in zip(modules.items(), counts, strict=True):
        expect(page.locator(f'[data-progress-module="{module}"]')).to_have_text(f"{count}/{len(ids)}")


def test_home_fresh_browser_and_actual_checked_attempts(page, site):
    page.goto(site[0] + "/index.html")
    expect(page.locator("[data-home-entry]")).to_have_text("Begin with Introduction")
    assert page.locator(".contents-progress-status").all_text_contents() == ["Not started"] * 3
    assert page.evaluate("JSON.stringify({...localStorage})") == "{}"
    key = open_exercise(page, site, "introduction", "the-introduction-section-of-research-papers", 1)
    respond(page, key)
    # Correct responses are still a draft until the learner checks them.
    page.locator(".nav-home").click()
    expect(page.locator("[data-home-entry]")).to_have_text("Begin with Introduction")
    expect(page.locator(".contents-progress-status").first).to_have_text("Not started")
    key = open_exercise(page, site, "introduction", "the-introduction-section-of-research-papers", 1)
    respond(page, key)
    page.locator("button[type=submit]").click()
    expect(page.locator("[data-current-status]")).to_have_text("Completed")
    expect(page.locator('[data-progress-module="introduction"]')).to_have_text("1/14")
    page.locator(".nav-home").click()
    expect(page.locator("[data-home-entry]")).to_have_text("Continue with Introduction")
    expect(page.locator(".contents-progress-status").first).to_have_text("1 of 14 exercises completed")
    page.reload()
    expect(page.locator(".contents-progress-status").first).to_have_text("1 of 14 exercises completed")
    open_exercise(page, site, "introduction", "the-introduction-section-of-research-papers", 1)
    page.locator("select").first.select_option("")
    page.locator(".nav-home").click()
    expect(page.locator("[data-home-entry]")).to_have_text("Begin with Introduction")
    expect(page.locator(".contents-progress-status").first).to_have_text("Not started")


@pytest.mark.parametrize("value", [
    "{invalid", "null", "[]", '"completed"',
    '{"progress": [], "responses": false, "checked": "invalid"}',
])
def test_home_malformed_storage_is_read_only_and_unstarted(page, site, value):
    page.goto(site[0] + "/index.html")
    page.evaluate("value => localStorage.setItem('agrarian-writing-v2:introduction', value)", value)
    page.reload()
    expect(page.locator("[data-home-entry]")).to_have_text("Begin with Introduction")
    expect(page.locator("[data-home-entry]")).to_have_attribute("href", "introduction/index.html")
    expect(page.locator(".contents-progress-status").first).to_have_text("Not started")
    assert page.evaluate("localStorage.getItem('agrarian-writing-v2:introduction')") == value
    assert page.locator(".contents-progress-fill").evaluate_all("nodes => nodes.every(n => parseFloat(n.style.width) === 0)")
    expect(page.locator(".contents-link")).to_have_count(3)
    page.locator(".contents-link").first.click()
    expect(page.locator('[data-progress-module="introduction"]')).to_have_text("0/14")


def test_home_inconsistent_records_count_only_literal_current_completion(page, site):
    page.goto(site[0] + "/index.html")
    ids = json.loads(page.locator("#site-data").text_content())["modules"]["introduction"]
    saved = json.dumps({
        "progress": {ids[0]: "completed", ids[1]: True, ids[2]: -1, ids[3]: "Completed", "obsolete": "completed"},
        "responses": [], "checked": None,
    })
    page.evaluate("saved => localStorage.setItem('agrarian-writing-v2:introduction', saved)", saved)
    page.reload()
    expect(page.locator(".contents-progress-status").first).to_have_text("1 of 14 exercises completed")
    assert page.evaluate("localStorage.getItem('agrarian-writing-v2:introduction')") == saved
    page.locator(".contents-link").first.click()
    expect(page.locator('[data-progress-module="introduction"]')).to_have_text("1/14")


def test_home_existing_introduction_repair_does_not_write_storage(page, site):
    page.goto(site[0] + "/index.html")
    saved = json.dumps({
        "progress": {"introduction--further-practice--exercise-1": "completed"},
        "responses": {}, "checked": {},
    })
    page.evaluate("saved => localStorage.setItem('agrarian-writing-v2:introduction', saved)", saved)
    page.reload()
    expect(page.locator(".contents-progress-status").first).to_have_text("1 of 14 exercises completed")
    assert page.evaluate("localStorage.getItem('agrarian-writing-v2:introduction')") == saved
    page.locator(".contents-link").first.click()
    expect(page.locator('[data-progress-module="introduction"]')).to_have_text("1/14")
    repaired = page.evaluate("JSON.parse(localStorage.getItem('agrarian-writing-v2:introduction'))")
    assert repaired["progress"] == {"introduction--grammar-and-vocabulary-in-the-introduction-section--exercise-1": "completed"}


def test_home_storage_unavailable_falls_back_without_errors(page, site):
    page.add_init_script("""Object.defineProperty(window, 'localStorage', {
      get() { throw new Error('Storage unavailable'); }
    });""")
    page.goto(site[0] + "/index.html")
    expect(page.locator("[data-home-entry]")).to_have_text("Begin with Introduction")
    assert page.locator(".contents-progress-status").all_text_contents() == ["Not started"] * 3


def test_home_without_javascript_preserves_static_entry_and_contents(browser, site, documents):
    context = browser.new_context(java_script_enabled=False)
    try:
        page = context.new_page()
        page.goto(site[0] + "/index.html")
        entry = page.get_by_role("link", name="Begin with Introduction", exact=True)
        expect(entry).to_be_visible()
        expect(entry).to_have_attribute("href", "introduction/index.html")
        assert page.locator(".contents-title").all_text_contents() == ["Introduction", "Methods", "Results"]
        assert page.locator(".contents-summary").all_text_contents() == [doc.summary for doc in documents]
        assert page.locator(".contents-counts").all_text_contents() == [
            "6 subsections · 14 exercises", "2 subsections · 7 exercises", "2 subsections · 9 exercises",
        ]
        assert page.locator(".contents-link").evaluate_all("nodes => nodes.map(n => n.getAttribute('href'))") == [
            f"{doc.slug}/index.html" for doc in documents
        ]
        expect(page.locator(".contents-progress:visible")).to_have_count(0)
        assert page.locator(".contents-progress-status").all_text_contents() == [""] * 3
        entry.focus()
        page.keyboard.press("Enter")
        expect(page).to_have_url(site[0] + "/introduction/index.html")
    finally:
        context.close()
