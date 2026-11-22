# Authoring contract

This document is the normative reference for authoring course Markdown in `exercises/`. Every syntax example marked `markdown agrarian` below is parsed by the compiler and checked against publication policy in `tests/test_authoring.py`, and the error catalogue in Section 10 is checked against every `SourceError` raised by `agrarian_builder/parser.py` and `agrarian_builder/policy.py`.

---

## 1. How pages arise

Pages are never created manually; every learning page is derived from Markdown files and headings in `exercises/`.

| Source element | Generated path | Role |
| --- | --- | --- |
| Module file (`exercises/**/*.md`) | `/<module-id>/` | Module overview page |
| Level-two heading (`## ...`) | `/<module-id>/<subsection-id>/` | Subsection overview page |
| Level-three heading (`### ...`) | `/<module-id>/<subsection-id>/<exercise-id>/` | Interactive exercise page |
| Always generated (public) | `/`, `/about/`, `/404.html`, `/sitemap.xml` | Home, About, fallback page and sitemap |

Module discovery searches `exercises/` recursively for `*.md` files. Filenames do not determine URLs or course order: modules are ordered by `(order, id)`, with integer `order` first and the module `id` slug breaking ties. Within each module, reading order follows the headings in sequence: the module overview, then each subsection overview followed by its exercises in authored order. Previous and Next links traverse that linear sequence once and terminate at Home without wrapping back to an earlier learning page.

---

## 2. Module files

Each Markdown file in `exercises/` defines one module. Publication requires leading YAML front matter delimited by `---` lines.

| Field | Type | Required | Default | Constraints |
| --- | --- | --- | --- | --- |
| `id` | string | Yes | None | Non-empty lowercase ASCII URL-safe slug (`[a-z0-9]+(?:-[a-z0-9]+)*`), unique across modules, not in the reserved site IDs (`about`, `assets`) |
| `title` | string | Yes | None | Non-empty string after trimming; must equal the module's `#` heading under publication rules |
| `order` | integer | No | `0` | Integer only (YAML booleans such as `true` or `false` are rejected); controls module sequence |
| `summary` | string | No | Absent | Plain-text summary shown on the homepage module row; when present, must be a non-empty string after trimming |

Front matter must be a YAML mapping using safe YAML types only. Duplicate YAML keys and unsupported field names are rejected.

Every module must contain **exactly one** level-one heading (`# ...`), which must be the first heading in the file. Under publication rules, the `#` heading text must equal the front-matter `title`.

**Module overview prose** is the content between `#` and the first `##` heading. It may contain ordinary Markdown prose, lists, quotations, links, code spans, code blocks and ordinary HTML comments. Answer syntax — answer markers (`<mark class="correct-answer">`), labelled gaps, task-list items, answer declarations and unconsumed `<!-- agrarian` comments — is rejected outside exercises. Fenced code blocks, indented code blocks and inline code spans are ignored when checking overview prose.

### Valid module file

```markdown agrarian module valid
---
id: example
title: Example module
order: 1
summary: >-
  Short plain-text overview shown on the homepage module row.
---

# Example module

Module overview prose may include ordinary formatting, links and inline code such as `___ [1]`.

## Example subsection

<!-- agrarian
id: example-subsection
-->

Subsection overview prose introduces the exercises that follow.

### Exercise 1

<!-- agrarian
id: exercise-1
-->

**Instructions:** Select the best answer.

- [x] a) First option
- [ ] b) Second option
```

### Invalid module examples

Missing front matter is rejected by publication policy:

```markdown agrarian module invalid="publication requires front matter with id and title"
# Example module

## Example subsection

<!-- agrarian
id: example-subsection
-->

### Exercise 1

<!-- agrarian
id: exercise-1
-->

- [x] Yes
- [ ] No
```

A level-one heading that disagrees with the front-matter `title` is rejected by publication policy:

```markdown agrarian module invalid="level-one title 'Different heading' must equal front matter title 'Example module'"
---
id: example
title: Example module
order: 1
---

# Different heading

## Example subsection

<!-- agrarian
id: example-subsection
-->

### Exercise 1

<!-- agrarian
id: exercise-1
-->

- [x] Yes
- [ ] No
```

Reserved site module IDs (`about` and `assets`) are rejected so a module cannot collide with the public About page or static assets directory:

```markdown agrarian module invalid="module id 'assets' is reserved for the generated site"
---
id: assets
title: Example module
order: 1
---

# Example module

## Example subsection

<!-- agrarian
id: example-subsection
-->

### Exercise 1

<!-- agrarian
id: exercise-1
-->

- [x] Yes
- [ ] No
```

Answer markers are not allowed in module overview prose:

```markdown agrarian module invalid="answer marker outside an exercise; move it under a ### exercise heading"
---
id: example
title: Example module
order: 1
---

# Example module

An answer <mark class="correct-answer">marker</mark> belongs inside an exercise.

## Example subsection

<!-- agrarian
id: example-subsection
-->

### Exercise 1

<!-- agrarian
id: exercise-1
-->

- [x] Yes
- [ ] No
```

---

## 3. Subsections and exercises

A module must contain at least one `##` subsection heading. Every `###` exercise heading must belong to a preceding `##` subsection, and every `####` heading must belong to a preceding `###` exercise.

| Level | Meaning | Identity comment | Uniqueness scope |
| --- | --- | --- | --- |
| `#` | Module title | None (front matter `id` supplies the module slug) | Exactly one per file |
| `##` | Subsection title | `<!-- agrarian\nid: <slug>\n-->` immediately after `##` | Unique within the module |
| `###` | Exercise title | `<!-- agrarian\nid: <slug>\n-->` immediately after `###` | Unique within the subsection |
| `####` | `Item <label>` or `Model` (or legacy `Answer bank`) | Not allowed | Unique container slug within the exercise |

**Identity comments.** Place a dedicated HTML comment immediately after every `##` and `###` heading:

```text
## Subsection title

<!-- agrarian
id: subsection-slug
-->
```

Blank lines are permitted between the heading and the identity comment, but no prose, list, ordinary comment or other block may intervene. The comment must contain only the `id` key; do not mix `id` with `interaction` or `feedback`. Every `id` value must be a non-empty lowercase ASCII URL-safe slug matching `[a-z0-9]+(?:-[a-z0-9]+)*`. Quote numeric-only slugs (for example `id: "123"`) so YAML keeps them as strings rather than integers.

Under publication rules, every subsection and every exercise requires an explicit `id` comment. Under grammar-only checks without an explicit `id`, the parser derives a slug by accent-folding and lowercasing the heading text.

**Exercise titles and numbering.** Without an explicit `id` comment, a `###` heading must have the form `Exercise N` (where `N` is a positive integer). With an explicit `id` comment, free wording such as `### Identifying research gaps` is permitted. Under publication rules, every title of the form `Exercise N` must match its one-based position within its subsection; free titles permitted by explicit IDs are exempt from this numbering rule. Exercise numbers may repeat in different subsections because full exercise IDs include the subsection slug.

**Subsection overview prose** (between `##` and its first `###`, or the end of a prose-only subsection) obeys the same rules as module overviews: ordinary Markdown and ordinary comments are allowed, code spans and code blocks are ignored, and answer markers, labelled blanks, task-list items, answer declarations and unconsumed `<!-- agrarian` comments are rejected. A subsection may contain overview prose without exercises.

### Valid free exercise title with explicit identity

```markdown agrarian module valid
---
id: example
title: Example module
order: 1
---

# Example module

## Example subsection

<!-- agrarian
id: example-subsection
-->

### Identifying research gaps

<!-- agrarian
id: identifying-gaps
-->

- [x] First choice
- [ ] Second choice

### Exercise 2

<!-- agrarian
id: exercise-2
-->

- [ ] First choice
- [x] Second choice
```

### Invalid subsection and exercise examples

Omitting an explicit subsection `id` comment fails publication checks:

```markdown agrarian module invalid="publication requires an explicit subsection id"
---
id: example
title: Example module
order: 1
---

# Example module

## Example subsection

### Exercise 1

<!-- agrarian
id: exercise-1
-->

- [x] Yes
- [ ] No
```

Omitting an explicit exercise `id` comment fails publication checks:

```markdown agrarian module invalid="publication requires an explicit exercise id"
---
id: example
title: Example module
order: 1
---

# Example module

## Example subsection

<!-- agrarian
id: example-subsection
-->

### Exercise 1

- [x] Yes
- [ ] No
```

An `Exercise N` title whose number does not match its one-based position in the subsection fails publication checks:

```markdown agrarian module invalid="exercise number must equal its position 1"
---
id: example
title: Example module
order: 1
---

# Example module

## Example subsection

<!-- agrarian
id: example-subsection
-->

### Exercise 2

<!-- agrarian
id: exercise-2
-->

- [x] Yes
- [ ] No
```

Labelled blanks, task-list answers, answer declarations and metadata comments are rejected in subsection overviews:

```markdown agrarian module invalid="labelled gap outside an exercise; move it under a ### exercise heading"
---
id: example
title: Example module
order: 1
---

# Example module

## Example subsection

<!-- agrarian
id: example-subsection
-->

Complete __________ [1] before starting.

### Exercise 1

<!-- agrarian
id: exercise-1
-->

- [x] Yes
- [ ] No
```

```markdown agrarian module invalid="task-list answer outside an exercise; move it under a ### exercise heading"
---
id: example
title: Example module
order: 1
---

# Example module

## Example subsection

<!-- agrarian
id: example-subsection
-->

- [x] Checked in overview
- [ ] Unchecked in overview

### Exercise 1

<!-- agrarian
id: exercise-1
-->

- [x] Yes
- [ ] No
```

```markdown agrarian module invalid="answer declaration outside an exercise; move it under a ### exercise heading"
---
id: example
title: Example module
order: 1
---

# Example module

## Example subsection

<!-- agrarian
id: example-subsection
-->

**Answer bank:**

### Exercise 1

<!-- agrarian
id: exercise-1
-->

- [x] Yes
- [ ] No
```

```markdown agrarian module invalid="metadata comment outside an exercise; move it under a ### exercise heading"
---
id: example
title: Example module
order: 1
---

# Example module

## Example subsection

<!-- agrarian
id: example-subsection
-->

<!-- agrarian
feedback:
  correct: Well done.
-->

### Exercise 1

<!-- agrarian
id: exercise-1
-->

- [x] Yes
- [ ] No
```

---

## 4. Inside an exercise

Every `###` exercise must contain at least one scored question. Content inside an exercise is organised into containers and declarations:

| Construct | Syntax | Meaning |
| --- | --- | --- |
| Shared scope | Content before the first `####` heading | Exercise-wide context, instructions and direct questions (`context-q1`, `context-q2`, …) |
| Instruction block | Paragraph beginning with `**Instructions:**` (case-insensitive) | Rendered as a styled instruction callout rather than ordinary prose |
| Named scored item | `#### Item <label>` (`<label>` is letters or digits, e.g. `Item A`, `Item 1`) | Separate response group (`item-a-q1`, …); must contain at least one supported question |
| Worked model | `#### Model` | Displayed worked example outside scoring and progress; may contain prose only or resolved response syntax in its own unscored gap namespace |
| Answer bank | `**Answer bank:**` (or legacy `#### Answer bank`) followed by a bullet list | Labelled canonical mappings and optional unlabelled distractors for `gap` dropdowns |
| Answer key | `**Answer key:**` followed by a bullet list | Labelled canonical text answers for `interaction: typed-gap` (every entry must be labelled) |
| Matching mappings | `**Purposes:**` or `**Endings:**` followed by a bullet list | Labelled prompts paired one-to-one with a two-column source table |

Container slugs (`slugify(heading)`) must be unique within an exercise; duplicate `#### Item A` or duplicate `#### Model` headings are rejected. Only one bank, key or matching mapping list is allowed per exercise, and it may appear before or after the prose that references it.

**Answer declarations and near misses.** The canonical declaration forms are the bold paragraphs `**Answer bank:**`, `**Answer key:**`, `**Purposes:**` and `**Endings:**` (with the colon inside the bold asterisks). The legacy heading `#### Answer bank` remains supported for answer banks only. Any other paragraph or `####` heading whose plain text (after removing `*`, `_`, surrounding whitespace and one trailing `:`) matches `answer bank`, `answer key`, `answers`, `purposes`, `purpose`, `endings` or `ending` is rejected as a near miss with the canonical suggestion.

**Allowed ordinary Markdown.** Exercises may use ordinary paragraphs, emphasis, links, inline code, fenced or indented code blocks, blockquotes, tables, ordered lists and ordinary bullet lists. Response syntax is also parsed inside blockquotes and ordinary lists (for example numbered passages containing gaps), with two strict boundaries:

- **Task-list answers must be a top-level bullet list.** Task items (`[x]` / `[ ]`) inside ordered lists, blockquotes or lists nested inside another list are rejected so answers can never render literally on the page.
- **No mixed HTML comment blocks.** Pure ordinary HTML comments (`<!-- note -->`) are dropped silently in exercise scope, and HTML blocks without comments are rendered as written, but an HTML block that mixes `<!--` with other markup is rejected.

### Valid exercise with shared scope, instructions, worked model and items

```markdown agrarian exercise valid
Contextual prose shared across all items.

**Instructions:** Complete each item below.

#### Model

- [x] Worked answer shown to learners
- [ ] Distractor shown in the model

#### Item A

First item prompt.

- [x] a) Correct option
- [ ] b) Incorrect option

#### Item B

Second item prompt.

- [ ] a) Incorrect option
- [x] b) Correct option
```

The legacy `#### Answer bank` heading remains valid:

```markdown agrarian exercise valid
Complete ___ [1] with a term from the bank.

#### Answer bank

- <mark class="correct-answer">[1]</mark> yield
- moisture
```

### Invalid exercise-structure examples

A near-miss declaration (colon outside the bold markers, missing asterisks, wrong word or non-legacy `####` heading) is diagnosed directly:

```markdown agrarian exercise invalid="unrecognised declaration '**Answer bank**:'; write **Answer bank:**"
Complete ___ [1].

**Answer bank**:

- <mark class="correct-answer">[1]</mark> yield
```

Task-list items inside ordered lists, blockquotes or nested lists are rejected:

```markdown agrarian exercise invalid="task-list answers must be a top-level bullet list"
1. [x] First choice
2. [ ] Second choice

- [x] Valid fallback choice
- [ ] Other choice
```

An HTML block that mixes markup with a comment is rejected instead of being discarded silently:

```markdown agrarian exercise invalid="HTML block containing a comment is not supported; remove the comment or the block"
<div>
<!-- note -->
</div>

- [x] Yes
- [ ] No
```

---

## 5. Response kinds

Every exercise uses one or more of six supported response kinds:

| Response kind | Authoring syntax | Learner sees | Stored value |
| --- | --- | --- | --- |
| `single-choice` | Top-level bullet task list with one `[x]` entry; optional unique `a)` letters | Radio-button group ("Choose one answer") | Response ID → `[index]` (zero-based authored option index) |
| `multi-select` | Top-level bullet task list with two or more `[x]` entries | Checkbox group ("Select all that apply") | Response ID → `[index, ...]` (zero-based authored option indices) |
| `inline-choice` | Two alternatives separated by `\|`, one wrapped in `<mark class="correct-answer">...</mark>` | Inline `<select>` dropdown in prose | Response ID → `[0]` (left) or `[1]` (right) |
| `gap` | Three or more underscores beside `[label]` plus `**Answer bank:**` (or linked `#### Item <label>`) | Inline `<select>` of deduplicated bank choices (or anchor link to Item) | Response ID → `[index]` into deduplicated bank choices |
| `typed-gap` | Same labelled blank, `interaction: typed-gap` metadata, and `**Answer key:**` with all entries labelled | Inline text `<input>` checked after trimming, lowercasing and collapsing spaces | Response ID → raw typed string |
| `matching` | Two-column labelled table (`\|` escaped in cells) plus `**Purposes:**` or `**Endings:**` list | Source table followed by one prompt and `<select>` per mapping | Response ID → `[index]` into the table's label order |

Every bullet entry in a choice list, bank, key or matching list must contain exactly one paragraph and no nested list. Response IDs are assigned in container-local parsing order (`context-q1`, `context-q2`, `item-a-q1`, …).

### Single choice

One checked task item (`[x]` or `[X]`) in a top-level bullet list creates a `single-choice` question. Optional letter prefixes such as `a)` must be unique within the question and allow option-level feedback.

```markdown agrarian exercise valid
**Instructions:** Choose the correct statement.

- [ ] a) Results repeat every raw measurement.
- [x] b) Results highlight key patterns in the data.
```

The learner sees radio buttons labelled with each option; the browser stores `[1]` under `context-q1`.

### Multi-select

Two or more checked task items in a top-level bullet list create a `multi-select` question. Learners must select the exact set of checked options.

```markdown agrarian exercise valid
**Instructions:** Select all features belonging to the Methods section.

- [x] Experimental design
- [ ] Speculation on future policy
- [x] Statistical analysis
```

The learner sees checkboxes; the browser stores the array of selected zero-based option indices (for example `[0, 2]`) under `context-q1`.

### Inline choice

Two alternatives separated by `|` inside prose, with exactly one side wrapped in `<mark class="correct-answer">...</mark>`, create an `inline-choice` question.

**Boundary limit.** The unmarked side is restricted to **one word** (`[\w][\w'’/-]*`), or one of the five auxiliaries `was`, `were`, `has`, `have`, `had` followed by **one word**. Validation does not detect a longer unmarked phrase: the parser takes only the first word (or auxiliary plus word) as the alternative and leaves the remaining words in the sentence, so authors must always put the longer phrase on the marked side. For example, writing `Yield <mark class="correct-answer">declined</mark> | remained relatively stable.` parses without error into a dropdown offering `declined` and `remained`, leaving `relatively stable.` in the sentence after the control.

```markdown agrarian exercise valid
> Soil moisture <mark class="correct-answer">was measured daily</mark> | declined.
```

The learner sees an inline `<select>` offering the two alternatives in left-to-right order; the browser stores `[0]` (left) or `[1]` (right) under `context-q1`.

### Bank gaps and Item-linked gaps

A blank of three or more underscores beside a bracketed alphanumeric label (`__________ [A]` or `[A] __________`) creates a `gap` question resolved from `**Answer bank:**`. Gap labels must be unique across scored containers (worked models use a separate namespace). Citations before a blank such as `Reddy et al. [8] __________ [B]` keep `[B]` as the gap label.

Every labelled bank entry must match a scored gap. Repeated answer text collapses into one selectable option in first-occurrence order. Unlabelled entries act as distractors, and an optional trailing `*(not used)*` hint on a distractor is stripped before rendering.

```markdown agrarian exercise valid
**Instructions:** Choose the best word for each gap.

> Reddy et al. [8] __________ [A] that yield __________ [B] under drought.

**Answer bank:**

- <mark class="correct-answer">[A]</mark> reported
- <mark class="correct-answer">[B]</mark> declined
- increased *(not used)*
```

The learner sees an inline `<select>` at each blank containing the deduplicated bank choices (`reported`, `declined`, `increased`); the browser stores `[0]` for `context-q1` and `[1]` for `context-q2`.

When an exercise has no answer bank and a shared-scope blank's label matches a named `#### Item <label>` containing **one `single-choice` question**, the blank links to that Item instead of creating a duplicate control:

```markdown agrarian exercise valid
Read the excerpt and complete __________ [A] in the item below.

#### Item A

- [ ] a) decreased
- [x] b) remained stable
```

The learner sees an anchor link (`__________ [A]`) jumping to `#item-a`, and the browser stores only the Item's response (`[1]` under `item-a-q1`).

### Typed gaps

Typed gaps reuse the labelled blank syntax together with `interaction: typed-gap` in a metadata comment and `**Answer key:**` where every bullet entry carries a marked label.

```markdown agrarian exercise valid
<!-- agrarian
interaction: typed-gap
-->

**Instructions:** Type the verb form for each gap.

> Previous work __________ [1] on irrigated plots.

**Answer key:**

- <mark class="correct-answer">[1]</mark> has concentrated
```

The learner sees a text `<input>`. Checking trims surrounding whitespace, lowercases text and collapses repeated internal spaces; punctuation, wording and grammatical form remain exact. The browser stores the learner's raw typed text string under `context-q1`.

### Matching

Matching pairs a two-column Markdown source table with a `**Purposes:**` or `**Endings:**` bullet list. Every body row of the source table must have exactly two cells (escape literal pipe characters in cell text as `\|`), a unique alphanumeric label in the first column and non-empty text in the second. Every mapping entry must carry a marked label matching a table row, and every table row must be mapped.

```markdown agrarian exercise valid
**Instructions:** Match each sentence with its purpose.

| Label | Sentence |
| --- | --- |
| A | Soils were sampled at 0–20 cm (n = 12 \| three blocks). |
| B | Mean grain yield increased by 14%. |

**Purposes:**

- <mark class="correct-answer">B</mark> Report a primary finding.
- <mark class="correct-answer">A</mark> Describe a field procedure.
```

The learner sees the source table followed by one prompt and `<select>` dropdown ("Select a sentence") per mapping entry, offering the table labels in table order (`A`, `B`). The browser stores `[1]` under `context-q1` and `[0]` under `context-q2`.

### Invalid response examples

Inline choices accept exactly two alternatives:

```markdown agrarian exercise invalid="inline choices require exactly two alternatives"
> The treatment <mark class="correct-answer">increased</mark> | reduced | changed biomass.
```

A typed gap declared with `interaction: typed-gap` requires `**Answer key:**` rather than `**Answer bank:**`:

```markdown agrarian exercise invalid="typed-gap requires an Answer key"
<!-- agrarian
interaction: typed-gap
-->

> Yield __________ [1] sharply.

**Answer bank:**

- <mark class="correct-answer">[1]</mark> increased
```

---

## 6. Metadata comments

Exercise metadata uses HTML comment blocks starting with `<!-- agrarian` on its own line, containing a YAML mapping and ending with `-->`.

| Key | Allowed values | Scope notes |
| --- | --- | --- |
| `interaction` | `typed-gap` | Sets typed-gap checking for the exercise or Item; Items inherit the exercise's `interaction` when unset |
| `feedback.correct` | Non-empty string | Message shown when all responses in the scope are correct |
| `feedback.incorrect` | Non-empty string | Message shown when any response in the scope is incorrect |
| `feedback.options` | Mapping `{letter: text}` | Requires exactly one labelled choice question (`a)`, `b)`, …) in scope; every key must exist on that question |
| `feedback.gaps` | Mapping `{"label": text}` | Keys must match scored gap labels in scope; **quote numeric labels** (for example `"1": ...`) so YAML keeps them as strings |

**YAML restrictions.** The body of every metadata comment must parse as a YAML mapping using `SafeLoader` (custom YAML tags such as `!!python/object:...` are rejected), with no duplicate keys and no unsupported top-level or feedback keys. Separate comments within the same scope may supply different fields, but repeating an already populated field (`interaction` or any `feedback.*` field) in the same scope is rejected.

**Misspelt metadata comments.** Any block or inline HTML comment that starts with `<!--` followed by `agrarian` in any case or spacing, or whose body contains a line matching `^\s*(id|interaction|feedback)\s*:`, is treated as metadata-like. If it does not match the exact `<!-- agrarian\n...\n-->` form, it is rejected in every scope. In particular, an ordinary author note whose body has a line starting `id:`, `interaction:` or `feedback:` (after optional leading whitespace) is treated as metadata-like and rejected. Ordinary HTML comments without that prefix or those leading line keys remain allowed.

**Scoping rules (including the trailing-comment rule).** The parser assigns each metadata comment inside an exercise as follows:

1. A comment in the shared scope (before the first `####` heading) applies to the **exercise**.
2. A comment placed immediately after a declaration and its bullet list (`**Answer bank:**`, `**Answer key:**`, `**Purposes:**`, `**Endings:**` or `#### Answer bank`) applies to the **exercise**.
3. Any other comment under `#### Item X` or `#### Model` is collected as an item-scope comment — **except** when there is **exactly one** such item-scope comment in the entire exercise **and** it is the **final block** of the exercise, in which case the parser promotes it to **shared exercise metadata**.
4. When there are two or more item-scope comments in the exercise, or when at least one content block follows the comment, each item-scope comment remains local to its own container. Local Item feedback overrides matching exercise-level fields at runtime.

**Safe placements.** To avoid depending on the count of comments in an exercise:

- Put **shared exercise feedback** before the first `#### Item` heading (or immediately after an exercise-level declaration list).
- Put **local Item feedback** before that Item's final content block (for example right beneath `#### Item X`, before its prompt or choices).

### Valid shared and local metadata with safe placement

```markdown agrarian exercise valid
<!-- agrarian
interaction: typed-gap
feedback:
  correct: Both verb forms agree with their subjects.
  incorrect: Check subject–verb agreement in each gap.
  gaps:
    "1": Use singular present perfect for a singular subject.
    "2": Use plural present perfect for a plural subject.
-->

#### Item A

<!-- agrarian
feedback:
  correct: Item A agrees with its singular subject.
  gaps:
    "1": Local explanation for gap 1 overrides the shared gap note.
-->

> Research __________ [1] on rainfed maize.

#### Item B

> Field trials __________ [2] higher retention.

**Answer key:**

- <mark class="correct-answer">[1]</mark> has focused
- <mark class="correct-answer">[2]</mark> have shown
```

### Invalid metadata examples

A misspelt metadata comment (wrong case, missing newline after `agrarian`, or missing `agrarian` keyword) is rejected in every scope:

```markdown agrarian exercise invalid="unrecognised metadata comment; write <!-- agrarian on its own line"
<!-- agrarian feedback: {correct: Well done.} -->

- [x] Yes
- [ ] No
```

Numeric gap feedback labels must be quoted in YAML so they remain strings:

```markdown agrarian exercise invalid="feedback.gaps must map quoted gap labels to text"
<!-- agrarian
interaction: typed-gap
feedback:
  gaps:
    1: Unquoted numeric label.
-->

> Yield __________ [1] significantly.

**Answer key:**

- <mark class="correct-answer">[1]</mark> increased
```

---

## 7. Identity and learner data

Learner progress and responses are stored locally in the browser under `localStorage` key `agrarian-writing-v2:<module-id>`. Each exercise is identified by `<module-id>--<subsection-slug>--<exercise-slug>`, and each scored response inside it is identified by its container-local ordinal (`context-q1`, `item-a-q1`, …).

**Which edits change IDs.**

| Edit | Effect on IDs |
| --- | --- |
| Change front-matter `title`, `#` heading, `order` or `summary` (keeping `id`) | Preserves all module, subsection and exercise IDs |
| Reword a `##` or `###` heading (keeping its `id:` comment) | Preserves URLs and exercise IDs |
| Reorder unchanged subsections or exercises within their existing scope | Preserves exercise IDs (update sequential `Exercise N` titles if used) |
| Change front-matter `id`, a subsection `id:` comment or an exercise `id:` comment | Changes URLs and exercise IDs; previous browser records under the old ID are orphaned and ignored |
| Move an exercise into a different subsection | Changes the exercise ID because the subsection slug is part of the ID |
| Rename `#### Item X`, or insert, delete or reorder questions inside a container | Changes response IDs (`item-x-q1`, `context-q1`, …) or option positions |

**Which edits clear drafts through the fingerprint.** Each exercise embeds a 16-character structural fingerprint derived from its scored responses (`id`, `kind`, `source_label`, plain-text prompt and plain-text options). Consistent with [CONTRIBUTING.md](CONTRIBUTING.md):

- **Clears saved attempts on next visit:** changing the text of any option, answer-bank entry, inline-choice alternative or matching purpose (typo fixes included), renaming `#### Item X` (which changes its response IDs), adding or removing options, questions or Items, reordering options or responses, or changing a response's kind. When a learner revisits that exercise, the browser clears the old attempt, resets existing progress to `in-progress`, updates the stored fingerprint and notifies the learner; Home keeps any stale `completed` count until that exercise page is visited.
- **Never clears drafts:** changing which option, alternative or mapping label is correct, editing typed-gap expected answers, or editing surrounding prose, `**Instructions:**`, authored feedback, `##` and `###` headings that keep their `id:` comments, module titles, module `order`, or worked `#### Model` sections. Existing checked attempts are re-scored against the updated answer key on load.

**When to run `agrarian inspect --write`.** Run `uv run --frozen agrarian inspect --check` after editing `exercises/`. The committed manifest (`course.manifest.json`) records module IDs, titles, `order`, source paths, subsection and exercise IDs/titles/paths, scored response shapes, expected answers, response groups, feedback presence (which keys exist, not prose wording), worked-model counts, fingerprints and the learning sequence. Whenever `inspect --check` reports a diff, review every changed line carefully and regenerate the manifest only when every structural change is intended:

```sh
uv run --frozen agrarian inspect --write
```

Prose-only and feedback-wording edits do not change `course.manifest.json`.

---

## 8. Grammar rules versus publication rules

The compiler separates **grammar rules** (`agrarian_builder/parser.py`, always enforced on every parse) from **publication rules** (`agrarian_builder/policy.py`, enforced whenever the resolved source is the canonical `exercises/` directory).

- **Grammar rules** check what Markdown means: valid YAML syntax, heading hierarchy, overview restrictions, comment syntax, answer declarations, response syntax, uniqueness within a module or discovery directory, and reserved module IDs (`about`, `assets`) during discovery.
- **Publication rules** enforce course-wide identity stability and naming policy: front matter with `id` and `title`, `#` heading equal to front-matter `title`, explicit `id:` comments on every `##` and `###`, and sequential `Exercise N` numbering (exempting free titles).

| Command | Grammar rules | Publication rules | Output |
| --- | --- | --- | --- |
| `agrarian validate` | Yes | Yes (`exercises/`) | Summary to stdout |
| `agrarian validate exercises` | Yes | Yes (`exercises/`) | Summary to stdout |
| `agrarian validate <file-or-other-dir>` | Yes | No | Summary to stdout |
| `agrarian inspect` | Yes | Yes (`exercises/`) | Pure manifest JSON to stdout |
| `agrarian inspect exercises` | Yes | Yes (`exercises/`) | Pure manifest JSON to stdout |
| `agrarian inspect <file-or-other-dir>` | Yes | No | Pure manifest JSON to stdout |
| `agrarian inspect --check` | Yes | Yes (`exercises/`) | Up-to-date notice or unified diff on stderr |
| `agrarian inspect --write` | Yes | Yes (`exercises/`) | Writes `course.manifest.json` |
| `agrarian build` / `python build.py` | Yes | Yes (`exercises/`) | Rebuilds `_site/` |

---

## 9. Recipes

### Add a module

1. Create a new file under `exercises/` (for example `exercises/abstract.md`) with front matter (`id`, `title`, `order`, optional `summary`), a matching `#` heading, at least one `##` subsection with an explicit `id:` comment, and exercises with explicit `id:` comments.
2. Validate, review the manifest diff, update `course.manifest.json` and build:

```sh
uv run --frozen agrarian validate
uv run --frozen agrarian inspect --check
# Review the diff above before writing the manifest.
uv run --frozen agrarian inspect --write
git diff course.manifest.json
uv run --frozen agrarian build
```

### Add a subsection

1. Append a `##` heading with an immediate `<!-- agrarian\nid: <unique-slug>\n-->` comment inside the target `exercises/<module>.md` file.
2. Add optional overview prose and any `###` exercises (each with its own `id:` comment and sequential `Exercise N` title, or a free title).
3. Validate, review the manifest diff, update `course.manifest.json` and build:

```sh
uv run --frozen agrarian validate
uv run --frozen agrarian inspect --check
# Review the diff above before writing the manifest.
uv run --frozen agrarian inspect --write
git diff course.manifest.json
uv run --frozen agrarian build
```

### Add an exercise

1. Add a `### Exercise N` heading (matching its one-based position in the subsection) or a free `###` title under the chosen `##` subsection, followed immediately by `<!-- agrarian\nid: <unique-slug>\n-->`.
2. Add `**Instructions:**`, response syntax and any authored feedback using safe comment placement.
3. Validate, review the manifest diff, update `course.manifest.json` and build:

```sh
uv run --frozen agrarian validate
uv run --frozen agrarian inspect --check
# Review the diff above before writing the manifest.
uv run --frozen agrarian inspect --write
git diff course.manifest.json
uv run --frozen agrarian build
```

### Add an Item

1. Inside an existing `###` exercise, add `#### Item <label>` (using a label unique in that exercise) with at least one supported question. Adding an Item changes the exercise's structural fingerprint and clears learners' saved attempts at that exercise on their next visit.
2. If the exercise uses a shared bank or key, add matching labelled entries for any new gaps.
3. Validate, review the manifest diff, update `course.manifest.json` and build:

```sh
uv run --frozen agrarian validate
uv run --frozen agrarian inspect --check
# Review the diff above before writing the manifest.
uv run --frozen agrarian inspect --write
git diff course.manifest.json
uv run --frozen agrarian build
```

### Edit text safely

- **Prose, instructions, feedback wording or worked models:** edit directly; fingerprints and `course.manifest.json` remain unchanged unless you add or remove a feedback key or a worked model.
- **Correctness flags or typed-gap expected answers:** edit directly; learners' drafts stay intact and re-score on load, and you must update `course.manifest.json`.
- **Option text, bank entries, inline alternatives or matching purposes:** remember that even a typo fix changes the exercise fingerprint and clears learners' saved attempts for that exercise on next visit.
- Validate, review any manifest diff, update `course.manifest.json` when `inspect --check` reports an intended change, and build:

```sh
uv run --frozen agrarian validate
uv run --frozen agrarian inspect --check
# Review the diff above before writing the manifest (skip --write if up to date).
uv run --frozen agrarian inspect --write
git diff course.manifest.json
uv run --frozen agrarian build
```

### Reorder content

- **Modules:** adjust `order` in front matter while keeping `id` unchanged.
- **Subsections:** move the whole `##` block (including its `id:` comment and child exercises) within the same module.
- **Exercises within a subsection:** move each `###` block together with its original `<!-- agrarian\nid: ...\n-->` comment. If the exercises use `Exercise N` titles, renumber those headings to match their new 1-based positions while keeping their `id:` comments unchanged so saved learner state stays attached to each exercise.
- Validate, review the manifest diff, update `course.manifest.json` and build:

```sh
uv run --frozen agrarian validate
uv run --frozen agrarian inspect --check
# Review the diff above before writing the manifest.
uv run --frozen agrarian inspect --write
git diff course.manifest.json
uv run --frozen agrarian build
```

### Remove content

Delete the unwanted module file, subsection block, exercise block or Item. For removed modules, subsections and exercises, orphaned saved state stays harmlessly in learners' browsers and is ignored because progress counts only currently discovered exercise IDs. Removing an Item from an existing exercise changes that exercise's structural fingerprint and clears learners' saved attempts at that exercise on their next visit. Validate, review the manifest diff, update `course.manifest.json` and build:

```sh
uv run --frozen agrarian validate
uv run --frozen agrarian inspect --check
# Review the diff above before writing the manifest.
uv run --frozen agrarian inspect --write
git diff course.manifest.json
uv run --frozen agrarian build
```

### Regenerate and review the manifest

```sh
uv run --frozen agrarian validate
uv run --frozen agrarian inspect --check
# Review the diff above before writing the manifest.
uv run --frozen agrarian inspect --write
git diff course.manifest.json
uv run --frozen agrarian build
```

---

## 10. Error catalogue

Every `SourceError` message template raised by `agrarian_builder/parser.py` and `agrarian_builder/policy.py` is listed below. Each message is prefixed at runtime by its source context (file path, and subsection, exercise or Item title when applicable); `…` stands for a context-specific value.

| Message template | Cause | Fix |
| --- | --- | --- |
| `Answer key requires interaction: typed-gap` | A gap references an `**Answer key:**` list, but neither the exercise nor the Item sets `interaction: typed-gap`. | Add `<!-- agrarian\ninteraction: typed-gap\n-->` in scope, or change `**Answer key:**` to `**Answer bank:**` for dropdown gaps. |
| `HTML block containing a comment is not supported; remove the comment or the block` | An exercise contains a raw HTML block that mixes `<!--` with other markup. | Remove the comment from the HTML block, place ordinary comments on their own separate block, or replace the block with Markdown. |
| `YAML must be a mapping` | Front matter or an `agrarian` metadata comment parsed as a YAML scalar or list rather than key–value pairs. | Write `key: value` pairs inside the front matter or metadata comment. |
| `answer bank has no canonical mappings` | An `**Answer bank:**` or `**Answer key:**` list contains no `<mark class="correct-answer">` label entries. | Mark at least one bullet entry with `<mark class="correct-answer">[label]</mark>` followed by its answer text. |
| `answer bank/key or matching mappings require a bullet list` | The block immediately after `**Answer bank:**`, `**Answer key:**`, `**Purposes:**`, `**Endings:**` or `#### Answer bank` is not a bullet list. | Place a `- ...` bullet list directly after the declaration with no intervening blocks. |
| `answer lists require one paragraph per entry` | A bullet item in a choice list, bank, key or matching list contains multiple paragraphs or a nested list. | Keep each option or mapping entry to a single paragraph with no nested sub-lists. |
| `choice list has no correct answer` | A task list contains only unchecked `[ ]` items. | Mark at least one option as correct with `[x]`. |
| `duplicate answer mapping […]` | Two entries in an answer bank, answer key or matching list map the same label. | Give each mapped label a single entry in the declaration list. |
| `duplicate exercise id … within subsection` | Two `###` exercises in the same subsection resolve to the same slug. | Give each exercise in the subsection a distinct `id:` comment (or distinct `Exercise N` title under grammar-only checks). |
| `duplicate feedback.…` | Two metadata comments in the same scope both set the same feedback field (`correct`, `incorrect`, `options` or `gaps`). | Merge the duplicate feedback field into a single comment in that scope. |
| `duplicate gap […]` | Two scored blanks in the same exercise share the same gap label. | Assign a distinct alphanumeric label to each scored blank (worked `#### Model` blanks use a separate scope). |
| `duplicate item heading …` | Two `####` containers in one exercise resolve to the same slug (for example two `#### Item A` or two `#### Model` headings). | Give every Item a unique label and include at most one `#### Model` per exercise. |
| `duplicate matching entry …` | Two rows in a matching source table share the same label in the first column. | Give every row in the matching source table a unique alphanumeric label. |
| `duplicate metadata …` | Two metadata comments in the same scope both set `interaction`. | Declare `interaction: typed-gap` once in that scope. |
| `duplicate module id …; also in …` | Two discovered Markdown files share the same module `id`. | Set a unique `id` in each module's front matter. |
| `duplicate option labels in choice list` | Two options in one task list share the same letter prefix (such as two `a)` entries). | Give every labelled option in the choice list a distinct letter prefix. |
| `duplicate subsection slug …` | Two `##` subsections in the same module resolve to the same slug. | Give each subsection in the module a distinct `id:` comment. |
| `exercise contains no supported questions` | An exercise has prose or worked models only, with no scored response. | Add at least one supported scored question under the `###` heading. |
| `exercise number must equal its position …` | Under publication rules, a `### Exercise N` heading's number does not match its one-based position in its subsection. | Renumber the `### Exercise N` headings sequentially from 1 while keeping their explicit `id:` comments, or use a free title with an explicit `id:`. |
| `exercise without a subsection` | A `###` heading appears before the first `##` subsection heading. | Add a `##` subsection heading (with its `id:` comment) before the `###` exercise. |
| `expected a level-one title` | The module has no headings, or its first heading is not `#`. | Start the module body (after front matter) with a single `#` level-one heading. |
| `expected exactly one level-one title` | The module contains two or more `#` level-one headings. | Keep one `#` heading for the module title and demote subheadings to `##` or deeper. |
| `feedback references unknown gap …` | `feedback.gaps` names a label that does not appear among scored gaps in that scope. | Match every `feedback.gaps` key to a scored `[label]` blank in the same exercise or Item. |
| `feedback references unknown option …` | `feedback.options` names a letter that does not appear on the labelled choice question in scope. | Match every `feedback.options` key to an `a)`-style option prefix in that scope. |
| `feedback requires correct, incorrect, options or gaps` | `feedback` is not a YAML mapping or contains an unsupported sub-key. | Use only `correct`, `incorrect`, `options` and `gaps` inside `feedback:`. |
| `feedback.gaps must map quoted gap labels to text` | `feedback.gaps` is not a mapping, uses an unquoted numeric or invalid key, or has empty or non-string text. | Map valid quoted string gap labels (for example `"1": Explanation.`) to non-empty strings. |
| `feedback.options must map option labels to text` | `feedback.options` is not a mapping or contains non-string or empty values. | Map each option letter string (for example `a: Explanation.`) to a non-empty string. |
| `feedback.… must be nonempty text` | `feedback.correct` or `feedback.incorrect` is not a string or is blank after trimming. | Provide a non-empty string for `feedback.correct` or `feedback.incorrect`, or remove the key. |
| `front matter order must be an integer` | Front matter `order` is not an integer (for example a string, float or boolean). | Set `order` to a whole number such as `1`, or omit it to use the default `0`. |
| `front matter requires nonempty id` | Front matter omits `id` or sets it to an empty or non-string value. | Add a non-empty string `id` to the module front matter. |
| `front matter requires nonempty title` | Front matter omits `title` or sets it to an empty or non-string value. | Add a non-empty string `title` to the module front matter. |
| `front matter summary must be a nonempty string` | Front matter includes `summary`, but its value is empty, whitespace-only or not a string. | Supply a non-empty plain-text string for `summary`, or remove the `summary` field. |
| `gap […] has no canonical answer` | A labelled blank has no matching entry in an answer bank or key and does not link to a named `#### Item <label>`. | Add a marked mapping for `[label]` in `**Answer bank:**` or `**Answer key:**`, or add a matching `#### Item <label>` when linking. |
| `heading id must be a nonempty lowercase URL-safe slug` | A heading `id:` comment is empty, non-string (for example an unquoted number) or contains uppercase, spaces, underscores, accents or repeated hyphens. | Use a lowercase ASCII string matching `[a-z0-9]+(?:-[a-z0-9]+)*` (quote numeric-only slugs). |
| `heading id requires a separate comment containing only id` | A heading `id:` comment also includes other keys such as `feedback` or `interaction`. | Put `id` in its own `<!-- agrarian\nid: ...\n-->` comment immediately after the heading and move other metadata to a separate comment. |
| `id comment must immediately follow a subsection or exercise heading` | An `id:` comment follows `#`, `####`, prose, an ordinary comment or another `id:` comment instead of directly following `##` or `###`. | Move the `id:` comment directly beneath its `##` or `###` heading (blank lines only between them) and remove any duplicate `id:` comment. |
| `inline choices require exactly two alternatives` | An inline choice has a third alternative separated by `\|` on either side. | Keep exactly two alternatives separated by a single `\|`, with one marked correct. |
| `invalid answer label …` | A marked label in an answer bank, key or matching list is not an alphanumeric `[label]` or `label`. | Put only letters or digits inside `<mark class="correct-answer">[label]</mark>`. |
| `invalid labelled matching entry …` | A row in a matching source table has a non-alphanumeric label or empty text cell. | Put an alphanumeric label in column 1 and non-empty text in column 2 of every body row. |
| `invalid typed-gap answer key; every entry needs a label` | An entry in `**Answer key:**` has no marked `<mark class="correct-answer">[label]</mark>` prefix. | Label every entry in `**Answer key:**` (distractors are only allowed in `**Answer bank:**`). |
| `item contains no supported question` | A scored `#### Item X` container has prose only and no response. | Add a supported question inside the Item, or rename it to `#### Model` if it is a worked example. |
| `item without an exercise` | A `####` (or deeper) heading appears before any `###` exercise heading in the current subsection. | Place `#### Item X` or `#### Model` under a `###` exercise heading. |
| `level-one title … must equal front matter title …` | Under publication rules, the `#` heading text does not match the front-matter `title`. | Make the `#` heading identical to the front-matter `title`. |
| `malformed YAML: …` | Front matter or a metadata comment contains invalid YAML syntax, duplicate YAML keys, non-scalar keys or unsafe YAML tags. | Fix the YAML syntax, remove duplicate keys and use only plain scalar, list and mapping values. |
| `malformed inline choice or stray answer marker` | `<mark class="correct-answer">` appears in prose without forming a valid two-alternative inline choice (for example both sides marked or missing `\|`). | Use one marked side and one unmarked word (or auxiliary plus word) separated by `\|`, or remove the stray `<mark>` tag. |
| `malformed or empty answer-bank entry` | An answer-bank, key or matching bullet entry has empty text after its label or contains a second `correct-answer` marker. | Provide non-empty answer text with at most one leading `<mark class="correct-answer">` label. |
| `mapped answer for nonexistent gap …` | An answer bank or key defines a labelled mapping for a gap that never appears in any scored container. | Add the missing labelled blank in the exercise or remove the unused mapping (or leave it unlabelled as a bank distractor). |
| `matching entry has no mapping …` | A labelled row in the matching source table has no corresponding entry in `**Purposes:**` or `**Endings:**`. | Add a labelled mapping bullet for every source-table row. |
| `matching mapping references unknown entry …` | A mapping entry in `**Purposes:**` or `**Endings:**` refers to a label not present in the source table. | Correct the label in the mapping list or add the matching row to the source table. |
| `matching mappings require a labelled source table` | The exercise has a `**Purposes:**` or `**Endings:**` list but no matching source table. | Add a two-column labelled Markdown table paired with the mappings. |
| `matching mappings require labelled entries` | An unlabelled bullet entry appears in `**Purposes:**` or `**Endings:**`. | Prefix every matching bullet with `<mark class="correct-answer">LABEL</mark>`. |
| `matching requires a labelled two-column source table` | The source table for a matching exercise has fewer than two columns or no body rows. | Use a two-column Markdown table with a header row, separator row and at least one labelled body row. |
| `matching row requires exactly two cells: …` | A body row in a matching source table has fewer or more than two unescaped `\|`-delimited cells. | Ensure every row has exactly two cells and escape literal pipes inside cell text as `\|`. |
| `mixed task and ordinary list entries` | A top-level bullet list in an exercise mixes `[x]`/`[ ]` task entries with plain bullet entries. | Make every entry in the list a task item, or split ordinary prose bullets into a separate list. |
| `module id must be a lowercase URL-safe slug` | Front matter `id` contains uppercase letters, spaces, underscores, accents or invalid punctuation. | Change `id` to lowercase ASCII letters and digits separated by single hyphens. |
| `module id … is reserved for the generated site` | A discovered module uses a reserved site ID (`about` or `assets`). | Rename the module's front-matter `id` (or filename when front matter is absent) so it does not collide with generated routes or `assets/`. |
| `multiple answer banks/keys/mapping lists` | An exercise declares more than one `**Answer bank:**`, `**Answer key:**`, `**Purposes:**`, `**Endings:**` or `#### Answer bank`. | Combine all mappings for the exercise into one declaration list, or split into separate exercises. |
| `multiple matching source tables are ambiguous` | A single container has two or more source tables paired with one matching mapping list. | Keep one matching source table per exercise, or split into separate exercises. |
| `no Markdown modules found` | Directory discovery found no `*.md` files under the given source directory. | Pass a directory containing module `.md` files or add a module under `exercises/`. |
| `no level-two subsections` | A module has a `#` title but no `##` subsection headings. | Add at least one `##` subsection heading with its `id:` comment. |
| `option feedback requires one labelled choice question in its scope` | `feedback.options` is declared in a scope containing zero or multiple choice questions with `a)`-style labels. | Place `feedback.options` in a scope with exactly one labelled choice question (or move choices into separate `#### Item` scopes). |
| `publication requires an explicit exercise id` | Under publication rules, a `###` exercise heading lacks an immediate `<!-- agrarian\nid: ...\n-->` comment. | Add a dedicated `<!-- agrarian\nid: <slug>\n-->` comment directly after the `###` heading. |
| `publication requires an explicit subsection id` | Under publication rules, a `##` subsection heading lacks an immediate `<!-- agrarian\nid: ...\n-->` comment. | Add a dedicated `<!-- agrarian\nid: <slug>\n-->` comment directly after the `##` heading. |
| `publication requires front matter with id and title` | Under publication rules, a module file omits leading YAML front matter. | Add leading `---` front matter specifying at least `id` and `title`. |
| `task-list answers must be a top-level bullet list` | A `[x]`/`[ ]` task item appears inside an ordered list, blockquote or nested list in an exercise. | Move task-list choices to a top-level `- [x]` / `- [ ]` bullet list. |
| `typed-gap metadata has no labelled gaps` | An exercise or Item declares `interaction: typed-gap`, but contains no typed-gap responses. | Add labelled blanks paired with `**Answer key:**`, or remove `interaction: typed-gap`. |
| `typed-gap requires an Answer key` | A blank in a `typed-gap` scope is paired with `**Answer bank:**` or matching mappings instead of `**Answer key:**`. | Rename the declaration to `**Answer key:**` and label every entry. |
| `unrecognised declaration …; write …` | A paragraph or `####` heading in an exercise looks like an answer declaration but does not match a canonical form. | Rewrite it using the suggested canonical form (for example `**Answer bank:**`). |
| `unrecognised metadata comment; write <!-- agrarian on its own line` | A metadata-like HTML comment (block or inline) does not match the exact `<!-- agrarian\n...\n-->` form. | Place `<!-- agrarian` on its own line in a block comment, followed by YAML lines and `-->`. |
| `unsupported answer/metadata structure` | Rendered exercise HTML still contains a `correct-answer` marker or `<!-- agrarian` comment (for example an inline metadata comment or raw markup inside a table/blockquote). | Place metadata comments as top-level blocks on their own lines and use supported answer syntax. |
| `unsupported exercise heading …` | A `###` heading without an explicit `id:` comment does not match `Exercise N`. | Rename the heading to `### Exercise N` or add an immediate `<!-- agrarian\nid: <slug>\n-->` comment. |
| `unsupported front matter fields …` | Front matter contains a key other than `id`, `title`, `order` and `summary`. | Remove or rename the unsupported field so only supported front-matter keys remain. |
| `unsupported interaction …` | A metadata comment sets `interaction` to a value other than `typed-gap`. | Set `interaction: typed-gap` or remove the `interaction` key. |
| `unsupported item heading …` | A `####` (or deeper) heading inside an exercise is neither `Item <label>`, `Model` nor legacy `Answer bank`. | Use `#### Item <label>` for scored items, `#### Model` for worked examples, or bold prose instead of a heading. |
| `unsupported metadata keys …` | A metadata comment contains top-level keys other than `interaction` and `feedback` (after heading `id` comments are consumed). | Keep only `interaction` and `feedback` in exercise metadata comments, and keep `id` in its own comment after `##` or `###`. |
| `unterminated front matter` | A module file starts with `---` but has no closing `---` line. | Add a closing `---` line at the end of the YAML front matter. |
| `… declaration has no list` | `**Answer bank:**`, `**Answer key:**`, `**Purposes:**`, `**Endings:**` or `#### Answer bank` appears at the end of an exercise with no following list. | Follow the declaration immediately with its bullet list of mappings. |
| `… has no correct answer` | A non-typed question was constructed with no option marked correct. | Mark at least one option as correct in the exercise source. |
| `… outside an exercise; move it under a ### exercise heading` | Module or subsection overview prose contains an `answer marker`, `labelled gap`, `task-list answer`, `answer declaration` or unconsumed `metadata comment` outside code spans/blocks. | Move the exercise construct under a `###` exercise heading, or wrap documentation examples in inline code or a fenced code block. |
| `…, gap […]: linked item must contain one single-choice question` | A shared-scope blank links to `#### Item <label>`, but that Item does not contain exactly one `single-choice` question. | Ensure the linked `#### Item <label>` contains one `single-choice` task list, or supply an `**Answer bank:**` instead. |
