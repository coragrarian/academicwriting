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
| `tests/` | Generic authoring/compiler proofs and explicitly marked canonical regressions |
| `tests/fixtures/course/` | Small four-module authoring examples; never production input |
| `_site/` | Generated website; do not edit it directly |

Public directory entries use the shared `_person.html` component. Portrait paths
are relative to `static/`; unverified fields remain absent.

## Content and authoring

Each Markdown file in `exercises/` represents one course module.

A module uses front matter for its identity and course order:

```yaml
---
id: methods
title: The Methods section
order: 2
---
```

Add a module by creating another `exercises/*.md` file with a unique `id`, title
and integer `order`. Discovery is recursive and ordering is `(order, id)`;
filenames do not determine course order. `about` is reserved for the public page.
Front matter is optional for legacy sources: the filename supplies the ID and
the level-one heading supplies the title. Present front matter requires both
`id` and `title`; duplicate YAML keys and unsupported fields are rejected.

The main heading structure is:

```text
# Module
## Subsection
### Exercise N
#### Item A
```

There must be exactly one level-one heading. Add a subsection with a unique
`##` title; it may contain only overview prose. Add an exercise under it with
`### Exercise N` and a supported response. Subsection slugs and exercise titles
must be unique in their respective scopes. Exercise numbers may repeat across
subsections. Neither addition needs Python or template registration.

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

| Response | Authoring boundary |
| --- | --- |
| Single choice / multi-select | A task list with one / several `[x]` entries; option letters such as `a)` must be unique within a question |
| Inline choice | Exactly two alternatives separated by `\|`, with one `correct-answer` mark; the unmarked alternative is one word, or `was/were/has/have/had` plus one word |
| Bank gap | Three or more underscores beside `[label]`, and an **Answer bank:** list mapping marked labels to answer text |
| Typed gap | The same labelled blank, `interaction: typed-gap`, and an **Answer key:** with every entry labelled |
| Matching | A two-column labelled table and a **Purposes:** or **Endings:** mapping list; escape literal pipes in cells |

Gap labels are unique across scored containers; every bank/key mapping must be
used. Banks may include unlabelled distractors and repeated answer text, which
becomes one selectable option. A shared gap may instead link to a named Item
containing one single-choice response. Models use a separate, unscored scope.

Feedback can supply `correct`, `incorrect`, `options` and `gaps`. Option feedback
requires one labelled choice in its scope; gap feedback refers to scored source
labels (quote numeric YAML labels). Local Item feedback overrides shared fields.
Comments before Items or immediately after a bank/key are exercise-level.
Otherwise comments belong to the current Item, except that a lone final Item
comment supplies shared exercise feedback. Put local feedback before its final
content block to avoid that trailing-comment convention.

The small [synthetic course](tests/fixtures/course/) demonstrates these boundaries
without production prose. `tests/test_parser.py` supplies rejection examples and
checks source-path and structural context in diagnostics.

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

Storage uses `agrarian-writing-v2:<module-id>`. Exercise IDs are
`<module-id>--<subsection-slug>--<exercise-slug>`; response IDs are container-local
ordinals such as `context-q1` or `item-a-q1`. Choices store zero-based authored
option indices; typed gaps store raw text. Progress counts only currently
discovered exercise IDs, so obsolete records do not inflate totals.

Changing a front-matter title or module `order` preserves identity when the
explicit module ID is retained. Moving unchanged subsections/exercises within
their existing scopes also preserves IDs. Renaming a module ID, subsection or
exercise title, moving an exercise between subsections, renaming Items, or
inserting/reordering questions or options can invalidate or reinterpret saved
responses. Gap labels scope feedback but do not independently stabilise ordinal
response IDs. Rebuilding unchanged sources is deterministic and never rewrites
Markdown. Existing Introduction migrations are specific historical compatibility
rules, not a general migration service.

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

Previous and Next move through the sequence once. The final learning page
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
| Generic compiler, additive authoring or build safety | `tests/test_extensibility.py` |
| Browser interaction and persistence | `tests/test_browser.py` |
| Synthetic interaction, navigation, persistence or reflow | `tests/test_browser_generic.py` |

Adding a response kind requires a compiler change: recognise and validate its
syntax in `parser.py`, define its semantic answer shape in `model.py`, render
controls/models and JSON in `renderer.py` / `question.html`, and collect, restore,
check and reset that shape in `exercises.js`. Add parser, build and browser proof.
`navigation.js` needs no kind dispatch when the existing form/DOM hooks suffice.
There is no registration layer.

Feedback follows `Metadata/Feedback` → `_answer_data` → browser question/group
results. A future count- or pattern-sensitive rule would need explicit source
validation, model fields, JSON and runtime selection, preserving existing fields
and saved response shapes. The present question/group results provide that seam;
new pedagogical rules have not been implemented.

Home counts, the course tree, progress, traversal and the sitemap derive from
discovered content. About's curriculum description and README's current-course
snapshot are intentionally authored prose: review them when the curriculum changes.

## Build and verification

The project requires Python 3.12 or newer and `uv`.

Install the environment and build the site with:

```sh
uv sync --locked
uv run --frozen python build.py
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
uv run --frozen pytest -q
```

Canonical regressions carry the `canonical` marker, including canonical cases
of shared build invariants; the existing canonical browser suite has both
markers. Generic tests use artificial input independently of `exercises/`:

```sh
uv run --frozen pytest -m 'not canonical and not browser' -q
uv run --frozen pytest -m 'canonical and not browser' -q
```

Run the browser tests with Playwright-managed Chromium:

```sh
uv run --frozen playwright install --with-deps chromium
uv run --frozen pytest -m browser -q
```

Use `-m 'browser and not canonical'` for the synthetic browser proof. All fixture
builds and additive/removal proofs use temporary directories. CI runs both
ordinary categories together, then the full browser suite. If Playwright's
bundled Node crashes locally, set `PLAYWRIGHT_NODEJS_PATH=/usr/bin/node` after
verifying the installed Node works; this changes only the test environment.

Other useful checks are:

```sh
uv run --frozen ruff check . --no-cache
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
