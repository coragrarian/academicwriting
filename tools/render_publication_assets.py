"""Render publication PNGs using the existing local Playwright Chromium runtime.

Run from the repository root:
    uv run --frozen python tools/render_publication_assets.py

These committed assets do not require a browser during the production build.
"""

from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    """Wait for local fonts, then capture each asset at its production size."""
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(
            viewport={"width": 1200, "height": 630}, device_scale_factor=1
        )
        page.goto((ROOT / "tools/social-preview.html").as_uri())
        page.evaluate("document.fonts.ready")
        page.screenshot(path=str(ROOT / "static/social-preview.png"))
        page.set_viewport_size({"width": 180, "height": 180})
        page.goto((ROOT / "static/favicon.svg").as_uri())
        page.screenshot(path=str(ROOT / "static/apple-touch-icon.png"))
        browser.close()


if __name__ == "__main__":
    main()
