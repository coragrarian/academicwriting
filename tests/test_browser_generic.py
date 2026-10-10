"""Browser contracts exercised independently of the canonical course."""

import json
import re
from itertools import pairwise

import pytest
from browser_support import respond, serve_not_found_candidate
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


def contrast_ratio(first, second):
    """WCAG relative luminance for opaque computed CSS rgb colours."""
    def luminance(colour):
        channels = [int(value) / 255 for value in re.findall(r"\d+", colour)[:3]]
        linear = [
            value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4
            for value in channels
        ]
        return sum(weight * value for weight, value in zip((0.2126, 0.7152, 0.0722), linear))

    dark, light = sorted((luminance(first), luminance(second)))
    return (light + 0.05) / (dark + 0.05)


def test_shell_tonal_regions_keep_local_text_and_focus_legible(page, synthetic_site):
    page.goto(f"{synthetic_site[0]}/index.html")
    header = page.locator(".site-header")
    footer = page.locator(".site-footer")
    header_surface = header.evaluate("n => getComputedStyle(n).backgroundColor")
    footer_surface = footer.evaluate("n => getComputedStyle(n).backgroundColor")
    paper = page.locator("body").evaluate("n => getComputedStyle(n).backgroundColor")
    assert header_surface != paper
    # The footer supplies neutral dark closure, with its own light focus colour.
    assert len(set(re.findall(r"\d+", footer_surface))) == 1
    assert contrast_ratio(header_surface, footer_surface) >= 7
    for selector, surface in (
        (".site-name, .site-name span, .site-links a", header_surface),
        (".footer-provenance, .footer-links a", footer_surface),
    ):
        for text in page.locator(selector).all():
            colour = text.evaluate("n => getComputedStyle(n).color")
            assert contrast_ratio(colour, surface) >= 4.5
    for selector, surface in ((".about-link", header_surface), (".footer-links a", footer_surface)):
        link = page.locator(selector)
        link.focus()
        colour, outline = link.evaluate("n => [getComputedStyle(n).outlineColor, getComputedStyle(n).outlineStyle]")
        assert outline == "solid" and contrast_ratio(colour, surface) >= 3
    for image in footer.locator(".institution-logo").all():
        filter_, opacity = image.evaluate("n => [getComputedStyle(n).filter, +getComputedStyle(n).opacity]")
        assert "grayscale(1)" in filter_ and "brightness(0)" in filter_ and "invert(" in filter_
        assert 0.9 <= opacity < 1
        image.locator("xpath=..").hover()
        assert image.evaluate("n => +getComputedStyle(n).opacity") == 1


def test_interaction_colours_distinguish_neutral_hover_current_and_primary(page, synthetic_site, synthetic_documents):
    def colours(node):
        return node.evaluate("""n => {
          const style = getComputedStyle(n);
          let parent = n;
          while (getComputedStyle(parent).backgroundColor === 'rgba(0, 0, 0, 0)') parent = parent.parentElement;
          return [style.color, getComputedStyle(parent).backgroundColor, style.borderColor];
        }""")

    def neutral(colour):
        return len(set(re.findall(r"\d+", colour))) == 1

    hover_surfaces = []
    document = synthetic_documents[0]
    for path, selector, metadata in (
        ("index.html", ".contents-link", ".contents-number, .contents-counts"),
        (f"{document.slug}/index.html", ".overview-link", ".overview-number, .overview-progress"),
        (f"{document.slug}/{document.sections[0].slug}/index.html", ".exercise-list a", None),
    ):
        page.goto(f"{synthetic_site[0]}/{path}")
        page.mouse.move(0, 0)
        row = page.locator(selector).first
        original = colours(row)
        assert neutral(row.locator(".nav-chevron").evaluate("n => getComputedStyle(n).color"))
        row.hover()
        ink, surface, _ = colours(row)
        assert neutral(ink) and surface != original[1]
        assert contrast_ratio(ink, surface) >= 4.5
        if metadata:
            for text in row.locator(metadata).all():
                assert contrast_ratio(colours(text)[0], surface) >= 4.5
        hover_surfaces.append(surface)

    page.goto(f"{synthetic_site[0]}/{exercise_path(synthetic_documents, 'single-choice')}")
    current = page.locator('.course-panel a[aria-current="page"]')
    current_ink, current_surface, _ = colours(current)
    assert not neutral(current_ink) and current_surface != hover_surfaces[0]
    assert contrast_ratio(current_ink, current_surface) >= 4.5
    current.hover()
    assert colours(current)[:2] == [current_ink, current_surface]
    inactive = page.locator(".nav-home")
    assert neutral(colours(inactive)[0])
    inactive.hover()
    hover_surfaces.append(colours(inactive)[1])
    for link in page.locator(".page-navigation a").all():
        assert neutral(colours(link)[0])

    primary = page.locator(".button-primary")
    ink, surface, _ = colours(primary)
    assert not neutral(surface) and contrast_ratio(ink, surface) >= 4.5
    primary.hover()
    assert colours(primary)[1] != surface
    assert contrast_ratio(*colours(primary)[:2]) >= 4.5
    secondary = page.locator(".button-secondary")
    ink, surface, border = colours(secondary)
    assert neutral(ink) and neutral(border) and contrast_ratio(border, surface) >= 3
    secondary.hover()
    ink, surface, border = colours(secondary)
    hover_surfaces.append(surface)
    assert neutral(ink) and contrast_ratio(ink, surface) >= 4.5
    assert contrast_ratio(border, surface) >= 3
    option = page.locator(".choice-option").first
    option.hover()
    hover_surfaces.append(colours(option)[1])
    option.locator("input").check()
    assert colours(option)[1] == current_surface
    serve_not_found_candidate(page, synthetic_site)
    page.goto(f"{synthetic_site[0]}/404.html")
    tertiary = page.locator(".action-link--tertiary")
    assert neutral(colours(tertiary)[0])
    tertiary.hover()
    hover_surfaces.append(colours(tertiary)[1])
    assert neutral(colours(tertiary)[0]) and contrast_ratio(*colours(tertiary)[:2]) >= 4.5
    assert len(set(hover_surfaces)) == 1


def test_directional_actions_share_styles_without_sharing_position(page, synthetic_site, synthetic_documents):
    def styles(link):
        return link.evaluate("""node => {
          const properties = ['fontFamily', 'fontSize', 'fontWeight', 'lineHeight',
            'color', 'gap', 'minHeight', 'padding', 'borderWidth', 'backgroundColor',
            'textDecorationLine', 'outlineColor', 'outlineStyle', 'outlineWidth',
            'outlineOffset', 'transitionProperty', 'transitionDuration', 'transitionTimingFunction'];
          const style = getComputedStyle(node);
          const chevron = getComputedStyle(node.querySelector('.nav-chevron'));
          return [properties.map(key => style[key]),
            ['width', 'height', 'color', 'transform', 'strokeWidth'].map(key => chevron[key])];
        }""")

    for motion in ("reduce", "no-preference"):
        page.emulate_media(reduced_motion=motion)
        actions = []
        for path, selector in (
            ("index.html", ".project-detail-link"),
            (f"{synthetic_documents[0].slug}/index.html", '.page-navigation a[rel="next"]'),
        ):
            page.goto(f"{synthetic_site[0]}/{path}")
            page.evaluate("document.fonts.ready")
            page.mouse.move(0, 0)
            link = page.locator(selector)
            expect(link).to_have_class(re.compile(r"\bdirectional-link\b"))
            assert link.bounding_box()["height"] >= 44
            assert link.evaluate("n => getComputedStyle(n).borderWidth") == "0px"
            assert link.evaluate("n => getComputedStyle(n).backgroundColor") == "rgba(0, 0, 0, 0)"
            if path == "index.html":
                section = link.locator("xpath=..")
                assert link.bounding_box()["x"] == pytest.approx(section.bounding_box()["x"])
            states = [styles(link)]
            link.hover()
            expect(link).to_have_css("color", "rgb(24, 75, 64)")
            states.append(styles(link))
            page.mouse.move(0, 0)
            page.keyboard.press("Tab")
            link.focus()
            expect(link).to_have_css("outline-style", "solid")
            expect(link).to_have_css("color", "rgb(24, 75, 64)")
            states.append(styles(link))
            actions.append(states)
        assert actions[0] == actions[1]


def test_control_boundaries_and_progress_have_contrast_and_distinct_shapes(page, synthetic_site, synthetic_documents):
    for kind in ("typed-gap", "matching"):
        page.goto(f"{synthetic_site[0]}/{exercise_path(synthetic_documents, kind)}")
        for control in page.locator("select, .typed-gap").all():
            border, inside, outside = control.evaluate("""node => {
              let parent = node.parentElement;
              while (getComputedStyle(parent).backgroundColor === 'rgba(0, 0, 0, 0)') parent = parent.parentElement;
              const style = getComputedStyle(node);
              return [style.borderColor, style.backgroundColor, getComputedStyle(parent).backgroundColor];
            }""")
            assert min(contrast_ratio(border, inside), contrast_ratio(border, outside)) >= 3

    page.goto(f"{synthetic_site[0]}/{exercise_path(synthetic_documents, 'single-choice')}")
    exercise = page.locator("#exercise-form").get_attribute("data-exercise-id")
    dot = page.locator(f'[data-exercise-link="{exercise}"] .state-dot')
    shapes = []
    key = json.loads(page.locator("#answer-key").text_content())
    for status in ("not-started", "in-progress", "completed"):
        if status != "not-started":
            respond(page, key, wrong_id=next(iter(key["questions"])) if status == "in-progress" else None)
            page.locator("button[type=submit]").click()
        expect(dot.locator("xpath=..")).to_have_attribute("data-status", status)
        border, background, image, adjacent = dot.evaluate("""node => {
          const style = getComputedStyle(node);
          const link = getComputedStyle(node.parentElement);
          return [style.borderColor, style.backgroundColor, style.backgroundImage,
            link.backgroundColor === 'rgba(0, 0, 0, 0)' ? getComputedStyle(document.body).backgroundColor : link.backgroundColor];
        }""")
        assert contrast_ratio(border, adjacent) >= 3
        shapes.append((background == "rgba(0, 0, 0, 0)", image == "none"))
    assert len(set(shapes)) == 3


@pytest.mark.parametrize("motion", ["reduce", "no-preference"])
def test_partial_navigation_and_chevrons_remain_visually_stable(page, synthetic_site, synthetic_documents, motion):
    page.emulate_media(reduced_motion=motion)
    document = synthetic_documents[0]
    page.goto(f"{synthetic_site[0]}/{document.slug}/index.html")
    page.evaluate("""() => {
      window.navigationFrames = [];
      const sample = () => {
        const style = getComputedStyle(document.querySelector('[data-page-content]'));
        navigationFrames.push([style.opacity, style.transform]);
        if (navigationFrames.length < 35) requestAnimationFrame(sample);
      };
      requestAnimationFrame(sample);
    }""")
    page.locator('.page-navigation a[rel="next"]').click()
    expect(page.locator("h1")).to_have_text(document.sections[0].title)
    expect(page.locator("h1")).to_be_focused()
    page.wait_for_function("navigationFrames.length >= 35")
    assert all(frame == ["1", "none"] for frame in page.evaluate("navigationFrames"))
    assert page.locator("h1").evaluate("n => getComputedStyle(n).outlineStyle") == "none"
    forward = page.locator('.page-navigation a[rel="next"]')
    forward.scroll_into_view_if_needed()
    chevron = forward.locator("svg")
    before = chevron.bounding_box()
    forward.hover()
    assert chevron.evaluate("n => getComputedStyle(n).transform") == "none"
    assert chevron.bounding_box() == pytest.approx(before, abs=0.5)
    if motion == "reduce":
        assert page.locator("a, button, summary, .choice-option, .institution-logo").evaluate_all(
            "nodes => nodes.every(n => getComputedStyle(n).transitionDuration.split(',').every(d => parseFloat(d) === 0))"
        )
        assert page.locator(".course-link, .about-link").evaluate_all(
            "nodes => nodes.every(n => parseFloat(getComputedStyle(n, '::after').transitionDuration) === 0)"
        )


def test_a_late_aborted_response_cannot_replace_the_newer_destination(page, synthetic_site, synthetic_documents):
    document = synthetic_documents[0]
    section = document.sections[0]
    exercise = section.exercises[0]
    section_path = f"{document.slug}/{section.slug}/index.html"
    page.goto(f"{synthetic_site[0]}/{document.slug}/index.html")
    page.locator(f'[data-nav-node="section:{document.slug}:{section.slug}"] > summary').click()
    page.evaluate("""({slow, html}) => {
      const ordinaryFetch = window.fetch.bind(window);
      window.fetch = (url, options) => {
        if (url !== slow) return ordinaryFetch(url, options);
        window.slowSignal = options.signal;
        return new Promise(resolve => {
          // Deliberately deliver despite abort to exercise the sequence guard.
          window.releaseSlowResponse = () => resolve({ok: true,
            headers: new Headers({'content-type': 'text/html'}),
            text: async () => { window.slowResponseConsumed = true; return html; }});
        });
      };
    }""", {"slow": f"{synthetic_site[0]}/{section_path}", "html": (synthetic_site[1] / section_path).read_text()})
    page.get_by_role("link", name="Overview", exact=True).click()
    page.wait_for_function("window.releaseSlowResponse !== undefined")
    page.locator(f'[data-exercise-link="{exercise.id}"]').click()
    expect(page.locator("h1")).to_have_text(exercise.title)
    assert page.evaluate("slowSignal.aborted")
    page.evaluate("releaseSlowResponse()")
    page.wait_for_function("window.slowResponseConsumed === true")
    expect(page).to_have_url(f"{synthetic_site[0]}/{document.slug}/{section.slug}/{exercise.slug}/index.html")
    expect(page.locator("h1")).to_have_text(exercise.title)


def test_mobile_disclosures_touch_targets_and_skip_focus(page, synthetic_site, synthetic_documents):
    page.set_viewport_size({"width": 320, "height": 900})
    page.goto(f"{synthetic_site[0]}/{synthetic_documents[0].slug}/index.html")
    page.keyboard.press("Tab")
    expect(page.locator(".skip-link")).to_be_focused()
    page.keyboard.press("Enter")
    expect(page.locator("main")).to_be_focused()
    page.keyboard.press("Tab")
    assert page.locator(":focus").evaluate("n => !!n.closest('main')")
    expect(page.locator(".course-link, .module-link")).to_have_count(2)
    assert page.locator(".course-link, .module-link").evaluate_all(
        "nodes => nodes.every(n => n.getAttribute('aria-current') === 'true')"
    )
    toggle = page.locator(".course-toggle")
    assert not toggle.evaluate("n => n.parentElement.open")
    toggle.focus()
    page.keyboard.press("Enter")
    assert toggle.evaluate("n => n.parentElement.open")
    page.locator(".course-tree details").evaluate_all("nodes => nodes.forEach(n => n.open = true)")
    for target in page.locator(".course-panel a:visible, .course-panel summary:visible, .page-navigation a").all():
        assert target.bounding_box()["height"] >= 44
        target.focus()
        assert target.evaluate("n => getComputedStyle(n).outlineStyle") == "solid"
    assert "0 of" in page.locator(".nav-module-group > summary").first.aria_snapshot()

    page.goto(f"{synthetic_site[0]}/{exercise_path(synthetic_documents, 'single-choice')}")
    trail = page.get_by_role("navigation", name="Breadcrumb")
    expect(trail.locator("ol > li")).to_have_count(4)
    expect(trail.locator('[aria-current="page"]')).to_have_text(
        "/ " + page.locator("h1").text_content()
    )
    expect(page.locator('.course-panel a[aria-current="page"]')).to_have_count(1)
    option = page.locator(".choice-option").first
    option.locator("input").focus()
    assert option.evaluate("n => getComputedStyle(n).outlineStyle") == "solid"
    assert option.locator("input").evaluate("n => getComputedStyle(n).outlineStyle") == "none"


@pytest.mark.parametrize("kind", ["single-choice", "multi-select"])
def test_checking_choice_results_preserves_horizontal_geometry(page, synthetic_site, synthetic_documents, kind):
    for width in (1280, 320):
        page.set_viewport_size({"width": width, "height": 900})
        page.goto(f"{synthetic_site[0]}/{exercise_path(synthetic_documents, kind)}")
        page.locator("#reset-exercise").click()
        page.evaluate("document.fonts.ready")
        geometry = "nodes => nodes.map(n => [n.getBoundingClientRect().x, n.getBoundingClientRect().width])"
        selector = ".choice-option, .choice-option input, .choice-option > span"
        before = page.locator(selector).evaluate_all(geometry)
        key = json.loads(page.locator("#answer-key").text_content())
        for wrong in (next(iter(key["questions"])), None):
            respond(page, key, wrong_id=wrong)
            page.locator("button[type=submit]").click()
            after = page.locator(selector).evaluate_all(geometry)
            for original, checked in zip(before, after, strict=True):
                assert checked == pytest.approx(original, abs=0.5)
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")


def test_short_public_shell_and_about_follow_natural_document_order(page, synthetic_site):
    serve_not_found_candidate(page, synthetic_site)
    for width in (1280, 320):
        page.set_viewport_size({"width": width, "height": 1200})
        page.goto(synthetic_site[0] + "/404.html")
        page.evaluate("document.fonts.ready")
        footer = page.locator(".site-footer").bounding_box()
        assert footer["y"] + footer["height"] == pytest.approx(1200, abs=1)
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        page.goto(synthetic_site[0] + "/about/index.html")
        page.evaluate("document.fonts.ready")
        source = page.locator(".about-layout > *").evaluate_all(
            "nodes => nodes.map(n => [n.id || n.className, n.getBoundingClientRect().y])"
        )
        assert [name for name, _ in source[:4]] == ["about-narrative", "project-information", "team", "data-platform"]
        assert all(second[1] >= first[1] for first, second in pairwise(source))


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
    assert f"1 of {len(site_data['modules'][module])} exercises completed" in page.locator(
        f'[data-progress-module="{module}"]'
    ).locator("xpath=..").aria_snapshot()
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
    expect(page.locator("#exercise-feedback")).to_have_text("Exercise reset.")
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
    review = page.locator('#exercise-feedback a[href="#item-b"]')
    review.focus()
    page.keyboard.press("Enter")
    expect(page.locator("#item-b")).to_be_focused()
    page.keyboard.press("Tab")
    expect(page.locator('[data-question="item-b-q1"]')).to_be_focused()
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
        if path == "index.html":
            action = page.locator(".project-detail-link")
            assert action.bounding_box()["height"] >= 44
            project = page.locator('[aria-labelledby="project-heading"]')
            assert action.bounding_box()["x"] == pytest.approx(project.bounding_box()["x"])
            action.focus()
            expect(action).to_be_focused()
            expect(action).to_have_css("outline-style", "solid")
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
