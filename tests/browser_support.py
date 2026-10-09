"""Native-control helpers and temporary HTTP serving for browser checks."""

import json
import threading
from contextlib import contextmanager
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote, urlsplit

from playwright.sync_api import expect

from agrarian_builder import renderer
from agrarian_builder.renderer import build_site


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, format, *args):
        pass


@contextmanager
def serve_site(documents, root):
    """Serve an isolated build below /study, including its assets."""
    build_site(documents, root / "study")
    server = ThreadingHTTPServer(("127.0.0.1", 0), partial(QuietHandler, directory=str(root)))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/study", root / "study"
    finally:
        server.shutdown()
        thread.join()
        server.server_close()


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



def serve_not_found_candidate(page, site):
    """Serve the fallback at a missing URL and map production assets locally.

    GitHub Pages retains the missing request's URL when returning 404.html.
    Production links must work there without contacting the deployed site.
    """
    page.route(site[0] + "/missing/**", lambda route: route.fulfill(
        status=404, content_type="text/html", body=(site[1] / "404.html").read_bytes()
    ))

    def production(route):
        # Avoid request-context APIResponse objects outliving 404 recovery.
        relative = unquote(urlsplit(route.request.url.removeprefix(renderer.SITE_URL)).path)
        target = (site[1] / relative).resolve()
        assert target.is_relative_to(site[1].resolve())
        if target.is_dir():
            target /= "index.html"
        route.fulfill(path=target)

    page.route(renderer.SITE_URL + "**", production)

