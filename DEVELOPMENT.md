# Development guide

This project is a static GitHub Pages site built from structured Markdown.

The important split is simple:

```text
exercises/*.md
    ↓
parser.py
    ↓
model.py
    ↓
renderer.py + templates/
    ↓
_site/
```

The Markdown files contain the teaching material. The parser decides what that
Markdown means, the model carries that meaning between stages, and the renderer
turns it into the pages that are published.

On learning pages, JavaScript adds the interactive behaviour: answer checking,
feedback, saved responses, progress and partial navigation.

Home, About and the generated 404 fallback use ordinary links and only the shared
stylesheet. They do not receive course scripts or learner-state JSON.

There is no backend or database.

## Project structure

| Location | Responsibility |
| --- | --- |
| `exercises/` | Canonical teaching content, answers and authored feedback |
| `agrarian_builder/parser.py` | Interprets and validates the Markdown conventions |
| `agrarian_builder/model.py` | Semantic representation of modules, exercises, questions and feedback |
| `agrarian_builder/people.py` | Public directory entries, roles and optional portrait/profile metadata |
| `agrarian_builder/renderer.py` | Generates paths, pages, navigation and browser checking data |
| `templates/` | HTML structure |
| `static/styles.css` | Visual presentation |
| `static/exercises.js` | Answer checking, feedback, persistence and progress |
| `static/navigation.js` | Progressive navigation and browser history |
| `static/fonts/` | Locally served font assets |
| `tests/` | Parser, build and browser regression tests |
| `_site/` | Generated website; do not edit it directly |

Public directory entries use the shared `_person.html` component. Portrait paths
are relative to `static/`; unverified fields remain absent.

## Content and authoring

Each Markdown file in `exercises/` represents one course module.

The current modules are:

- `introduction.md`
- `methods.md`
- `results.md`

A module uses front matter for its identity and course order:

```yaml
---
id: methods
title: The Methods section
order: 2
---
```

The main heading structure is:

```text
# Module
## Subsection
### Exercise N
#### Item A
```

`#### Model` is used for worked examples. Models are displayed to learners but
are not scored and do not contribute to progress.

A paragraph beginning with:

```md
**Instructions:**
```

is rendered as an instruction block.

Correct answers, answer banks, typed gaps, matching tasks and feedback are also
declared in the Markdown. Some interactions use small YAML metadata blocks in
HTML comments, for example:

```text
<!-- agrarian
interaction: typed-gap
feedback:
  correct: The forms agree with their subjects.
  incorrect: Review subject–verb agreement.
-->
```

The parser validates these conventions rather than trying to guess ambiguous
answers. If the source is incomplete or contradictory, the build should fail
with context instead of silently inventing an interpretation.

For the exact authoring syntax, the existing files in `exercises/` are the most
useful examples.

## How the site is generated

`build.py` discovers the Markdown modules and passes them through the parser.

The parser converts the authored structure into the dataclasses defined in
`model.py`. The renderer then uses that semantic representation to:

- generate the page hierarchy;
- prepare the Jinja template context;
- create Previous/Next navigation;
- render interactive controls;
- embed the answer and feedback data used by the browser.

The browser performs the actual answer checking. Python prepares the checking
data; `static/exercises.js` evaluates learner responses.

Normal content pages use relative links, so the site works under a GitHub Pages
project path.

`renderer.py` owns `SITE_URL`, the production identity for canonical URLs,
Open Graph metadata and `sitemap.xml`. Normal `index.html` pages use directory
canonicals with a trailing slash, including in local builds. The 404 fallback
uses absolute production links so assets and recovery actions work from nested
missing URLs; it has `noindex` and no canonical. The sitemap lists normal content
only. No project-local `robots.txt` is generated: crawlers read it at the host root.

The AW favicon is a browser identity, not a project logo. The social card and
touch icon are committed PNGs; the production build only copies them. To render
them again with local fonts and the existing development toolchain, run:

```sh
uv run --frozen python tools/render_publication_assets.py
```

## Things that are easy to break

A few implementation details are deliberately unusual and should not be
simplified without understanding why they exist.

### Response identities and saved state

Responses and progress are stored in `localStorage`.

Exercise and question identities are derived from the authored structure.
Renaming or reordering modules, subsections, exercises, questions or options
can therefore change the meaning of saved browser data.

Presentation changes should preserve semantic IDs whenever possible.

### The Introduction matching order

One matching exercise in the Introduction module is deliberately displayed in
the order:

```text
D, B, A, C
```

The source order would make the A–B–C–D answer pattern too obvious.

This is a presentation-only change. The source table, question identities,
option order and answer keys remain unchanged.

### Course navigation must not wrap

The learning sequence contains module overviews, subsection overviews and
exercise pages.

Home, About and the 404 fallback are outside that sequence.

Previous and Next move through the sequence once. The final Results exercise
returns to Home rather than linking back to an earlier learning page.

Do not add a convenient fallback that sends the final page back to a module
overview: that would recreate a cycle.

### Generated output is protected

The builder only removes an existing output directory if it contains the
`.agrarian-built` marker.

It renders the new site in a sibling staging directory first. If rendering
fails, the existing site is left intact.

The final removal and rename are separate filesystem operations, so this is
failure-resistant rather than a fully atomic filesystem swap.

Do not manually edit `_site/`, staging directories or the marker file.

### Typed-gap checking is intentionally conservative

Typed answers are normalised by:

- trimming surrounding whitespace;
- lowercasing;
- collapsing repeated internal spaces.

Punctuation, wording and grammatical form remain significant.

There is no fuzzy matching or synonym expansion.

### Normal links remain the foundation

`navigation.js` progressively enhances eligible links within a module.

Direct URLs, reloads, new tabs and ordinary navigation should still work
without that enhancement. If partial navigation fails, the browser falls back
to a normal page load.

The shared header and footer remain mounted during these page swaps. Their
links are resolved against the initial URL so changing course-page depth does
not change their destinations.

## Where to make changes

| Change | Start here |
| --- | --- |
| Exercise wording, answers or authored feedback | `exercises/*.md` |
| Markdown interpretation or validation | `agrarian_builder/parser.py` |
| Semantic entities and relationships | `agrarian_builder/model.py` |
| Generated paths, course order or Previous/Next targets | `agrarian_builder/renderer.py` |
| Page structure | `templates/` |
| Public people, roles and optional portraits | `agrarian_builder/people.py` |
| Typography, spacing or visual appearance | `static/styles.css` |
| Checking, typed gaps, retry, persistence or progress | `static/exercises.js` |
| Partial navigation or browser history | `static/navigation.js` |
| Parser behaviour | `tests/test_parser.py` |
| Generated structure or course navigation | `tests/test_build.py` |
| Browser interaction and persistence | `tests/test_browser.py` |

## Build and verification

The project requires Python 3.12 or newer and `uv`.

Install the environment and build the site with:

```sh
uv sync
uv run python build.py
```

Preview it locally with:

```sh
uv run python -m http.server 8000 --directory _site
```

Then open:

```text
http://localhost:8000/
```

Run the ordinary test suite with:

```sh
uv run pytest -q
```

Run the browser tests with Playwright-managed Chromium:

```sh
uv run --frozen playwright install --with-deps chromium
uv run --frozen pytest -m browser -q
```

Other useful checks are:

```sh
ruff check . --no-cache
node --check static/exercises.js
node --check static/navigation.js
git diff --check
```

Before trusting a structural change, check that it has not unintentionally
altered:

- generated page paths;
- Previous/Next targets;
- response IDs;
- answer keys or response groups;
- matching display order;
- saved-state identities.

The canonical build currently produces 3 modules, 10 subsections, 30 exercises
and 43 learning pages, plus Home and About (45 content pages in the sitemap).
The generated `404.html` fallback brings the total to 46 HTML files; it is outside
course traversal and progress.
