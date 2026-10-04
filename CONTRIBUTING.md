# Contributing

Use Python 3.12 or newer, `uv`, and Node.js. Clone the repository,
enter its directory and install the locked environment:

```sh
uv sync --locked
```

Read `DEVELOPMENT.md` for the architecture, authoring conventions and
maintenance boundaries. Create a branch from `main` before changing files:

```sh
git switch main
git switch -c your-change
```

Keep each change focused and preserve unrelated files. Python parsing,
semantic modelling and rendering live in `agrarian_builder/`; templates and
browser assets live in `templates/` and `static/`. Choose the layer that owns
the behaviour you intend to change. Include regression coverage when changing
behaviour, and keep existing checks meaningful rather than weakening them to
accept a new result.

The canonical teaching content is `exercises/introduction.md`,
`exercises/methods.md` and `exercises/results.md`. When editing content, preserve
response identities and answer mappings unless the change deliberately
requires otherwise. Check the Introduction matching display order separately
from its stored question identities. Verify quotations and scholarly
attribution against their sources, and respect the content scope in
`NOTICE.md`.

Build and verify the source before submitting it:

```sh
uv run python build.py
uv run pytest -q
uv run ruff check . --no-cache
uv run --frozen playwright install --with-deps chromium
uv run --frozen pytest -m browser -q
node --check static/exercises.js
node --check static/navigation.js
git diff --check
```

The ordinary test command excludes browser tests; the explicit browser command
runs the complete browser suite. Use the generated site for local preview and
check representative desktop and mobile pages when presentation changes.
`_site/` is generated output: do not edit or commit it. Make corrections in
the source and rebuild.

Use lightweight Conventional Commit subjects with one of `feat:`, `fix:`,
`docs:`, `test:`, `style:`, `refactor:`, `ci:` or `chore:`. Write a clear,
imperative subject in lowercase after the prefix, with no trailing full stop.
For example: `test: cover course navigation boundaries`.

Push your branch to your fork or the repository when authorised, then open a
pull request against `main`. Explain the problem, the resulting change and
the verification performed. State any unresolved limitation so the reviewer
can assess the change without reconstructing your local work.
