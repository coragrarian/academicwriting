"""Interpret authored Markdown structure, answers and metadata as a module.

This layer owns the source hierarchy, exercise/item boundaries, interaction
syntax, scoped feedback and validation. ``markdown-it`` handles Markdown
structure; the project-specific grammar resolves response semantics into
``model.py``. Ordinary prose becomes HTML fragments here, while inline responses
become ``@@question-id@@`` placeholders for the renderer.

One module has a level-one title, level-two subsections and level-three
``Exercise N`` headings. Within exercises, level-four headings introduce
``Item <label>`` or ``Model`` containers. Answer declarations and YAML comments
are gathered before responses are parsed, so a shared bank may follow its gaps.

The parser rejects unsupported or ambiguous answer structures with source
context rather than guessing. It does not rewrite teaching content, choose
page paths or presentation order, or check learner attempts in the browser.
"""

import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from markdown_it import MarkdownIt
from markdown_it.token import Token

from .model import (
    Block,
    Document,
    Exercise,
    ExerciseItem,
    Feedback,
    Metadata,
    Option,
    Question,
    Section,
)


class SourceError(ValueError):
    """Authored structure, answers or metadata violate the source contract.

    Messages carry file, subsection, exercise and item context when available,
    so a failed build identifies the authoring boundary that needs attention.
    """


MARK = r'<mark\s+class=["\']correct-answer["\']\s*>(.*?)</mark>'
MARK_RE = re.compile(MARK, re.IGNORECASE | re.DOTALL)
LABEL = r"(?:[0-9]+|[A-Za-z]+)"
# Prefer a label after the blank when both sides contain brackets: a citation
# such as "Reddy et al. [8] __________ [B]" is not a gap labelled 8.
GAP_RE = re.compile(rf"_{{3,}}\s*\[({LABEL})\]|\[({LABEL})\]\s*_{{3,}}(?!_)(?!\s*\[{LABEL}\])")
TASK_RE = re.compile(r"^\s*\[([ xX])\]\s*(.+)$", re.DOTALL)
ITEM_RE = re.compile(rf"Item\s+({LABEL})", re.IGNORECASE)
DECLARATIONS = {
    "answer bank": "bank",
    "answer key": "key",
    "purposes": "matching",
    "endings": "matching",
}
WORD = r"[\w][\w'’/-]*"
# Unmarked alternatives in the canonical inline syntax are one word or
# an auxiliary plus a word. A longer unmarked phrase has no explicit boundary.
PLAIN = rf"(?:(?:was|were|has|have|had)\s+)?{WORD}"
INLINE_RE = re.compile(
    rf"(?P<left>{MARK})\s*\|\s*(?P<right_plain>{PLAIN})"
    rf"|(?P<left_plain>{PLAIN})\s*\|\s*(?P<right>{MARK})",
    re.IGNORECASE | re.DOTALL,
)
INSTRUCTION_RE = re.compile(r"^\*\*Instructions:\*\*\s*", re.IGNORECASE)
AGRARIAN_RE = re.compile(r"\s*<!--\s*agrarian\s*\n(.*?)-->\s*", re.DOTALL)


class _UniqueSafeLoader(yaml.SafeLoader):
    """Keep SafeLoader's restricted types and reject silently overwritten keys."""


def _unique_mapping(loader: _UniqueSafeLoader, node: yaml.MappingNode) -> dict:
    """Reject duplicate YAML fields before a later value can hide an earlier one."""
    result = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node)
        try:
            duplicate = key in result
        except TypeError as error:
            raise yaml.constructor.ConstructorError(
                None,
                None,
                "mapping keys must be scalar",
                key_node.start_mark,
            ) from error
        if duplicate:
            raise yaml.constructor.ConstructorError(
                None,
                None,
                f"duplicate YAML key {key!r}",
                key_node.start_mark,
            )
        result[key] = loader.construct_object(value_node)
    return result


_UniqueSafeLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    _unique_mapping,
)


def _yaml_mapping(source: str, context: str) -> dict:
    """Read restricted YAML mappings and report errors in the author's scope."""
    try:
        value = yaml.load(source, Loader=_UniqueSafeLoader)
    except yaml.YAMLError as error:
        raise SourceError(f"{context}: malformed YAML: {error}") from error
    if not isinstance(value, dict):
        raise SourceError(f"{context}: YAML must be a mapping")
    return value


def _metadata(raw: str, context: str) -> Metadata:
    """Validate one ``agrarian`` comment without deciding where it applies.

    Notes
    -----
    Only ``interaction: typed-gap`` and authored feedback are recognised.
    Option keys and gap labels are retained for later validation against the
    questions in the chosen scope. Numeric gap labels must be quoted in YAML
    so they remain strings, matching the labels extracted from Markdown.
    """
    match = AGRARIAN_RE.fullmatch(raw)
    if match is None:
        raise SourceError(f"{context}: malformed agrarian metadata comment")
    data = _yaml_mapping(match.group(1), f"{context}, agrarian metadata")
    unknown = set(data) - {"interaction", "feedback"}
    if unknown:
        raise SourceError(f"{context}: unsupported metadata keys {list(unknown)!r}")
    interaction = data.get("interaction")
    if interaction is not None and interaction != "typed-gap":
        raise SourceError(f"{context}: unsupported interaction {interaction!r}")
    feedback = data.get("feedback", {})
    if not isinstance(feedback, dict) or set(feedback) - {"correct", "incorrect", "options", "gaps"}:
        raise SourceError(f"{context}: feedback requires correct, incorrect, options or gaps")
    messages = {}
    for key in ("correct", "incorrect"):
        if key in feedback:
            if not isinstance(feedback[key], str) or not feedback[key].strip():
                raise SourceError(f"{context}: feedback.{key} must be nonempty text")
            messages[key] = feedback[key].strip()
    options = feedback.get("options", {})
    if not isinstance(options, dict) or any(
        not isinstance(key, str) or not isinstance(value, str) or not value.strip()
        for key, value in options.items()
    ):
        raise SourceError(f"{context}: feedback.options must map option labels to text")
    gaps = feedback.get("gaps", {})
    if not isinstance(gaps, dict) or any(
        not isinstance(key, str)
        or not re.fullmatch(LABEL, key)
        or not isinstance(value, str)
        or not value.strip()
        for key, value in gaps.items()
    ):
        raise SourceError(f"{context}: feedback.gaps must map quoted gap labels to text")
    return Metadata(
        interaction,
        Feedback(
            **messages,
            options={key: value.strip() for key, value in options.items()},
            gaps={key: value.strip() for key, value in gaps.items()},
        ),
    )


def _merge_metadata(target: Metadata, incoming: Metadata, context: str) -> None:
    """Combine declarations in one scope without silently overriding a field.

    Separate comments may supply different fields, but repeating a populated
    interaction or feedback field is an authoring error. Shared/local precedence
    is a separate concern: local metadata is kept on its own item.
    """
    for key in ("interaction",):
        value = getattr(incoming, key)
        if value is not None:
            if getattr(target, key) is not None:
                raise SourceError(f"{context}: duplicate metadata {key}")
            setattr(target, key, value)
    for key in ("correct", "incorrect", "options", "gaps"):
        value = getattr(incoming.feedback, key)
        if value:
            if getattr(target.feedback, key):
                raise SourceError(f"{context}: duplicate feedback.{key}")
            setattr(target.feedback, key, value)


def slugify(value: str) -> str:
    """Derive an ASCII path component, using ``untitled`` for an empty result.

    Accent folding and punctuation removal can produce collisions. The callers
    that assemble modules, subsections and exercises validate their own scopes.
    """
    normal = unicodedata.normalize("NFKD", value)
    ascii_text = normal.encode("ascii", "ignore").decode("ascii").lower()
    return re.sub(r"[^a-z0-9]+", "-", ascii_text).strip("-") or "untitled"


@dataclass(frozen=True)
class Heading:
    """A heading boundary with a zero-based, half-open source-line range.

    The range comes from Markdown tokens after front matter has been removed;
    slicing at these boundaries keeps module and exercise bodies separate.
    """

    level: int
    title: str
    start: int
    end: int


def _headings(tokens: list[Token]) -> list[Heading]:
    result = []
    for index, token in enumerate(tokens):
        if token.type == "heading_open":
            assert token.map is not None
            title = re.sub(r"<[^>]+>", "", tokens[index + 1].content).strip()
            result.append(Heading(int(token.tag[1]), title, *token.map))
    return result


def _chunks(tokens: list[Token]) -> list[list[Token]]:
    """Keep each top-level Markdown block intact, including nested list tokens.

    Declarations and item boundaries are recognised between these chunks;
    splitting a list into individual tokens would lose its response semantics.
    """
    chunks = []
    start = depth = 0
    for index, token in enumerate(tokens):
        depth += token.nesting
        if depth == 0:
            chunks.append(tokens[start : index + 1])
            start = index + 1
    return chunks


def _list_entries(tokens: list[Token], context: str) -> list[str]:
    """Require one inline paragraph per entry before recognising a response list.

    This gives banks and task lists unambiguous option boundaries. Nested lists
    or multiple paragraphs cannot be reduced to one answer string.
    """
    entries = []
    for chunk in _chunks(tokens[1:-1]):
        inline = [token.content for token in chunk if token.type == "inline"]
        if len(inline) != 1 or any(token.type.endswith("list_open") for token in chunk):
            raise SourceError(f"{context}: answer lists require one paragraph per entry")
        entries.append(inline[0])
    return entries


def _table_rows(tokens: list[Token]) -> list[list[str]]:
    rows = []
    row = []
    for token in tokens:
        if token.type == "tr_open":
            row = []
        elif token.type == "inline":
            row.append(token.content)
        elif token.type == "tr_close":
            rows.append(row)
    return rows


def _declaration(chunk: list[Token]) -> str | None:
    if chunk[0].type == "heading_open" and chunk[0].tag == "h4":
        return DECLARATIONS.get(chunk[1].content.casefold())
    if chunk[0].type == "paragraph_open":
        match = re.fullmatch(r"\*\*(.+?):\*\*", chunk[1].content.strip())
        if match:
            return DECLARATIONS.get(match.group(1).casefold())
    return None


@dataclass
class _Bank:
    """Shared labelled mappings, plus any unlabelled bank distractors.

    ``answers`` keeps original source labels. ``choices`` removes repeated
    answer text while retaining first-occurrence order; several gaps may map
    to one displayed choice without acquiring different meanings.
    """

    kind: str
    entries: list[tuple[str | None, str]]

    @property
    def answers(self) -> dict[str, str]:
        return {label: text for label, text in self.entries if label is not None}

    @property
    def choices(self) -> list[str]:
        # Different gaps may intentionally share the same answer. Render that
        # answer once and validate by its text, never by the duplicate row ID.
        return list(dict.fromkeys(text for _, text in self.entries))


def _answer_bank(markdown: MarkdownIt, chunk: list[Token], kind: str, context: str) -> _Bank:
    """Separate canonical label mappings from learner-visible bank text.

    A ``correct-answer`` marker encloses the target label here, not the answer
    wording. Labelled entries must be unique. An answer bank can include
    unlabelled distractors, while an answer key requires every entry to be
    labelled. Matching's stricter requirements are checked with its source table.
    """
    if chunk[0].type != "bullet_list_open":
        raise SourceError(
            f"{context}: answer bank/key or matching mappings require a bullet list"
        )
    entries = []
    labels = set()
    for raw in _list_entries(chunk, context):
        match = MARK_RE.match(raw.strip())
        if match:
            label = match.group(1).strip()
            label_match = re.fullmatch(rf"\[({LABEL})\]|({LABEL})", label)
            if label_match is None:
                raise SourceError(f"{context}: invalid answer label {label!r}")
            label = label_match.group(1) or label_match.group(2)
            text = raw.strip()[match.end() :].strip()
            if label in labels:
                raise SourceError(f"{context}: duplicate answer mapping [{label}]")
            labels.add(label)
        else:
            label, text = None, raw.strip()
            if kind == "key":
                raise SourceError(
                    f"{context}: invalid typed-gap answer key; every entry needs a label"
                )
        if not text or "correct-answer" in text:
            raise SourceError(f"{context}: malformed or empty answer-bank entry")
        # This explicit authoring hint identifies a distractor, not visible
        # answer text. Preserve other parenthetical wording in bank entries.
        if label is None:
            text = re.sub(r"\s*\*\(not used\)\*\s*$", "", text, flags=re.IGNORECASE)
        entries.append((label, text))
    if not labels:
        raise SourceError(f"{context}: answer bank has no canonical mappings")
    return _Bank(kind, entries)


@dataclass
class _Container:
    """Collect a shared exercise scope, named item or model before parsing it.

    ``title=None`` identifies shared content; ``id`` gives questions their
    exercise-local namespace. Delaying response parsing allows declarations
    and metadata elsewhere in the exercise to apply to these chunks.
    """

    title: str | None
    id: str
    chunks: list[list[Token]] = field(default_factory=list)
    metadata: Metadata = field(default_factory=Metadata)


class _ContentParser:
    """Resolve responses within one already-delimited content scope.

    Parameters
    ----------
    markdown
        Markdown engine shared by the module, with raw HTML and tables enabled.
    context
        Source location used for author-facing validation errors.
    container
        Shared exercise content, named item or worked model collected by
        ``_exercise`` before this parser runs.
    bank
        Exercise-wide answer bank, typed key or matching mappings, if present.
    interaction
        Container declaration, falling back to the exercise's declaration.
    seen_gaps
        Labels already used in scored containers. Models receive a separate
        set so their demonstrations do not consume scored gap labels.
    item_labels
        Source labels mapped to item anchors for gaps answered by named items.

    Notes
    -----
    ``parse`` returns reading-order blocks and accumulates semantic questions
    on this instance. It embeds placeholders, not controls, in prose. Scoring
    eligibility is decided by ``_exercise``, which keeps models separate.
    """

    def __init__(
        self,
        markdown: MarkdownIt,
        context: str,
        container: _Container,
        bank: _Bank | None,
        interaction: str | None,
        seen_gaps: set[str],
        item_labels: dict[str, str],
    ):
        self.markdown = markdown
        self.context = context
        self.container = container
        self.bank = bank
        self.interaction = interaction
        self.seen_gaps = seen_gaps
        self.item_labels = item_labels
        self.questions: list[Question] = []
        self.linked_gaps: set[str] = set()

    def _add(
        self,
        kind: str,
        options: list[Option] | None = None,
        prompt_html: str = "",
        label: str = "",
        answer: str | None = None,
        source_label: str | None = None,
    ) -> Question:
        """Allocate a container-local response ID and require a canonical answer.

        Non-typed responses must identify at least one correct option. Typed
        answers have already been resolved from the labelled key by the caller.
        The ordinal is assigned during parsing, before display order is chosen.
        """
        options = options or []
        if kind != "typed-gap" and not any(option.correct for option in options):
            raise SourceError(f"{self.context}: {kind} has no correct answer")
        question = Question(
            f"{self.container.id}-q{len(self.questions) + 1}",
            kind,
            options,
            prompt_html,
            label,
            answer,
            source_label,
        )
        self.questions.append(question)
        return question

    def _paragraph(self, raw: str) -> str:
        """Replace supported inline answer syntax before rendering its prose.

        A marked alternative next to ``|`` supplies the correct option.
        Inline alternatives become option-based questions. Labelled blanks
        resolve through the shared bank/key, or link to an existing named item
        when that item owns the answer. Each created response leaves a generated
        ``@@question-id@@`` placeholder for the renderer; authors do not write
        those placeholders themselves.
        """

        def replace_inline(match: re.Match[str]) -> str:
            correct_left = match.group("left") is not None
            marked = match.group("left") if correct_left else match.group("right")
            correct = MARK_RE.fullmatch(marked)
            assert correct is not None
            alternatives = (
                [correct.group(1), match.group("right_plain")]
                if correct_left
                else [
                    match.group("left_plain"),
                    correct.group(1),
                ]
            )
            question = self._add(
                "inline-choice",
                [
                    Option(self.markdown.renderInline(text), index == (0 if correct_left else 1))
                    for index, text in enumerate(alternatives)
                ],
                label=f"Choice {len(self.questions) + 1}",
            )
            return f"@@{question.id}@@"

        raw = INLINE_RE.sub(replace_inline, raw)
        if "correct-answer" in raw:
            raise SourceError(f"{self.context}: malformed inline choice or stray answer marker")

        def replace_gap(match: re.Match[str]) -> str:
            label = match.group(1) or match.group(2)
            if label in self.seen_gaps:
                raise SourceError(f"{self.context}: duplicate gap [{label}]")
            self.seen_gaps.add(label)
            if self.bank is None and label in self.item_labels:
                # A shared passage can point to Item A/B instead of using a
                # bank. The response lives in that item, not in a second input.
                self.linked_gaps.add(label)
                return (
                    f'<a class="item-gap" href="#{self.item_labels[label]}" '
                    f'aria-label="Answer gap {label} in Item {label}">__________ [{label}]</a>'
                )
            if self.bank is None or label not in self.bank.answers:
                raise SourceError(f"{self.context}: gap [{label}] has no canonical answer")
            answer = self.bank.answers[label]
            if self.interaction == "typed-gap":
                if self.bank.kind != "key":
                    raise SourceError(f"{self.context}: typed-gap requires an Answer key")
                question = self._add(
                    "typed-gap", label=f"Gap {label}", answer=answer, source_label=label
                )
            else:
                if self.bank.kind != "bank":
                    raise SourceError(
                        f"{self.context}: Answer key requires interaction: typed-gap"
                    )
                question = self._add(
                    "gap",
                    [
                        Option(self.markdown.renderInline(text), text == answer)
                        for text in self.bank.choices
                    ],
                    label=f"Gap {label}",
                    source_label=label,
                )
            return f"@@{question.id}@@"

        raw = GAP_RE.sub(replace_gap, raw)
        return self.markdown.renderInline(raw)

    def _matching(self, chunk: list[Token]) -> list[Block]:
        """Resolve labelled table entries against purpose or ending mappings.

        The table supplies selectable source labels; each mapping supplies a
        prompt and its canonical label. Labels must match exactly between the
        two structures. Questions follow mapping order, and their alternatives
        follow table order. Any learner-facing reorder belongs to the renderer.
        """
        rows = _table_rows(chunk)
        if len(rows) < 2 or len(rows[0]) != 2:
            raise SourceError(
                f"{self.context}: matching requires a labelled two-column source table"
            )
        identifiers = []
        for row in rows[1:]:
            identifier, text = row
            if not re.fullmatch(LABEL, identifier) or not text.strip():
                raise SourceError(
                    f"{self.context}: invalid labelled matching entry {identifier!r}"
                )
            if identifier in identifiers:
                raise SourceError(f"{self.context}: duplicate matching entry {identifier}")
            identifiers.append(identifier)
        assert self.bank is not None
        unknown = set(self.bank.answers) - set(identifiers)
        if unknown:
            raise SourceError(
                f"{self.context}: matching mapping references unknown entry {sorted(unknown)}"
            )
        missing = set(identifiers) - set(self.bank.answers)
        if missing:
            raise SourceError(f"{self.context}: matching entry has no mapping {sorted(missing)}")
        table_html = self.markdown.renderer.render(chunk, self.markdown.options, {})
        blocks = [
            Block(
                "html", html=table_html.replace("<table>", '<table class="matching-sentences">')
            )
        ]
        for index, (answer, text) in enumerate(self.bank.entries, 1):
            if answer is None:
                raise SourceError(f"{self.context}: matching mappings require labelled entries")
            question = self._add(
                "matching",
                [
                    Option(self.markdown.renderInline(identifier), identifier == answer)
                    for identifier in identifiers
                ],
                self.markdown.renderInline(text),
                label=f"Match {index}",
            )
            blocks.append(Block("question", question_id=question.id))
        return blocks

    def parse(self) -> list[Block]:
        """Distinguish instructions, standalone questions and prose blocks.

        Checked task-list entries define correct alternatives: one selects
        ``single-choice``, several select ``multi-select``. Matching uses a
        labelled table and shared mappings. Other inline prose, including list
        and quotation content, passes through the same response grammar.

        Notes
        -----
        Token children are replaced with rendered inline fragments in place.
        These collected chunks are consumed once. Metadata comments have already
        been assigned to scopes and must not leak into rendered teaching content.
        """
        blocks = []
        matching_tables = 0
        for chunk in self.container.chunks:
            kind = chunk[0].type
            if kind == "html_block" and chunk[0].content.lstrip().startswith("<!--"):
                continue
            if kind == "bullet_list_open":
                entries = _list_entries(chunk, self.context)
                tasks = [TASK_RE.fullmatch(entry) for entry in entries]
                if any(tasks):
                    if not all(tasks):
                        raise SourceError(f"{self.context}: mixed task and ordinary list entries")
                    options = []
                    for task in tasks:
                        assert task is not None
                        text = task.group(2)
                        key = re.match(r"([a-zA-Z])\)\s+", text)
                        options.append(
                            Option(
                                self.markdown.renderInline(text),
                                task.group(1).lower() == "x",
                                key.group(1) if key else None,
                            )
                        )
                    correct_count = sum(option.correct for option in options)
                    if not correct_count:
                        raise SourceError(f"{self.context}: choice list has no correct answer")
                    question = self._add(
                        "single-choice" if correct_count == 1 else "multi-select",
                        options,
                        label=self.container.title or "Answer",
                    )
                    blocks.append(Block("question", question_id=question.id))
                    continue
            if kind == "table_open" and self.bank and self.bank.kind == "matching":
                matching_tables += 1
                blocks.extend(self._matching(chunk))
                continue
            if kind == "paragraph_open" and INSTRUCTION_RE.match(chunk[1].content):
                blocks.append(
                    Block(
                        "instruction",
                        html=self.markdown.renderInline(
                            INSTRUCTION_RE.sub("", chunk[1].content, count=1),
                        ),
                    )
                )
                continue
            # Apply response syntax to all inline tokens, so blockquotes and
            # numbered/bulleted passages share exactly the same gap grammar.
            for token in chunk:
                if token.type == "inline":
                    replacement = Token("html_inline", "", 0)
                    replacement.content = self._paragraph(token.content)
                    token.children = [replacement]
            rendered = self.markdown.renderer.render(chunk, self.markdown.options, {})
            if "correct-answer" in rendered or "<!-- agrarian" in rendered:
                raise SourceError(f"{self.context}: unsupported answer/metadata structure")
            blocks.append(Block("html", html=rendered))
        if matching_tables > 1:
            raise SourceError(f"{self.context}: multiple matching source tables are ambiguous")
        return blocks


def _validate_option_feedback(
    metadata: Metadata, questions: list[Question], context: str
) -> None:
    """Require option letters to identify one labelled choice in this scope.

    Repeated ``a)``/``b)`` labels across several questions cannot determine which
    response an explanation addresses. Gap feedback uses source labels instead.
    """
    if not metadata.feedback.options:
        return
    labelled = [
        question for question in questions if any(option.key for option in question.options)
    ]
    if len(labelled) != 1:
        raise SourceError(
            f"{context}: option feedback requires one labelled choice question in its scope"
        )
    keys = {option.key for option in labelled[0].options}
    unknown = set(metadata.feedback.options) - keys
    if unknown:
        raise SourceError(f"{context}: feedback references unknown option {sorted(unknown)}")


def _validate_gap_feedback(metadata: Metadata, questions: list[Question], context: str) -> None:
    """Require explanations to refer to scored source gaps in this scope."""
    labels = {question.source_label for question in questions if question.source_label}
    unknown = set(metadata.feedback.gaps) - labels
    if unknown:
        raise SourceError(f"{context}: feedback references unknown gap {sorted(unknown)}")


def _exercise(
    markdown: MarkdownIt, source: str, title: str, identifier: str, context: str
) -> Exercise:
    """Resolve shared declarations and scoped content into one scored exercise.

    The first scan establishes containers, the shared bank and metadata scope;
    the second parses each container with those declarations available. This
    keeps answer-bank placement independent of gap resolution.

    Notes
    -----
    Root comments and comments immediately after a declaration/list are shared.
    A lone final item comment is also shared; other item comments apply to the
    preceding item. This placement rule is part of the current authoring grammar.

    ``Model`` containers use the same response syntax as items but live in
    ``examples``, outside scoring and scored gap-label uniqueness. Every scored
    item needs a question; every bank/key mapping must refer to a scored gap.
    A passage linked to an item requires that item to contain one single-choice
    response, avoiding a duplicate control for the same answer.

    Raises
    ------
    SourceError
        Boundaries, metadata scope, mappings or response structures cannot be
        interpreted according to the supported exercise conventions.
    """
    exercise = Exercise(title, slugify(title), identifier)
    root = _Container(None, "context")
    containers = [root]
    current = root
    comments: list[tuple[_Container, Metadata, bool, int]] = []
    bank = None
    after_declaration = False
    chunks = _chunks(markdown.parse(source))
    index = 0
    while index < len(chunks):
        chunk = chunks[index]
        declaration = _declaration(chunk)
        if declaration:
            if bank is not None:
                raise SourceError(f"{context}: multiple answer banks/keys/mapping lists")
            if index + 1 >= len(chunks):
                raise SourceError(f"{context}: {declaration} declaration has no list")
            bank = _answer_bank(markdown, chunks[index + 1], declaration, context)
            index += 2
            after_declaration = True
            continue
        if chunk[0].type == "heading_open":
            heading = chunk[1].content
            if chunk[0].tag != "h4" or not (ITEM_RE.fullmatch(heading) or heading == "Model"):
                raise SourceError(f"{context}: unsupported item heading {heading!r}")
            container_id = slugify(heading)
            if any(container.id == container_id for container in containers):
                raise SourceError(f"{context}: duplicate item heading {heading}")
            current = _Container(heading, container_id)
            containers.append(current)
            after_declaration = False
        elif chunk[0].type == "html_block" and "<!--" in chunk[0].content:
            if re.match(r"\s*<!--\s*agrarian\b", chunk[0].content):
                comments.append(
                    (
                        current,
                        _metadata(chunk[0].content, f"{context}, {current.title or 'exercise'}"),
                        after_declaration,
                        index,
                    )
                )
        else:
            current.chunks.append(chunk)
            after_declaration = False
        index += 1

    item_comments = [entry for entry in comments if entry[0] != root and not entry[2]]
    for container, metadata, shared, position in comments:
        # The canonical sources use one trailing comment for shared feedback;
        # repeated comments between items are local to the preceding item.
        trailing_shared = len(item_comments) == 1 and position == len(chunks) - 1
        target = (
            exercise.metadata
            if container == root or shared or trailing_shared
            else container.metadata
        )
        _merge_metadata(target, metadata, context)

    item_labels = {
        ITEM_RE.fullmatch(container.title).group(1): container.id
        for container in containers
        if container.title and ITEM_RE.fullmatch(container.title)
    }
    seen_gaps: set[str] = set()
    linked_gaps: set[str] = set()
    for container in containers:
        is_model = container.title == "Model"
        parser = _ContentParser(
            markdown,
            f"{context}, {container.title or 'exercise'}",
            container,
            bank,
            container.metadata.interaction or exercise.metadata.interaction,
            set() if is_model else seen_gaps,
            item_labels,
        )
        blocks = parser.parse()
        linked_gaps |= parser.linked_gaps
        if container == root:
            exercise.blocks, exercise.direct_questions = blocks, parser.questions
        else:
            item = ExerciseItem(
                container.title, container.id, blocks, parser.questions, container.metadata
            )
            if is_model:
                exercise.examples.append(item)
            else:
                if not item.questions:
                    raise SourceError(
                        f"{context}, {item.title}: item contains no supported question"
                    )
                _validate_option_feedback(
                    item.metadata, item.questions, f"{context}, {item.title}"
                )
                _validate_gap_feedback(item.metadata, item.questions, f"{context}, {item.title}")
                exercise.items.append(item)
    if bank and bank.kind in {"bank", "key"}:
        missing = set(bank.answers) - seen_gaps
        if missing:
            raise SourceError(f"{context}: mapped answer for nonexistent gap {sorted(missing)}")
    if (
        bank
        and bank.kind == "matching"
        and not any(q.kind == "matching" for q in exercise.questions)
    ):
        raise SourceError(f"{context}: matching mappings require a labelled source table")
    for label in linked_gaps:
        item = next(item for item in exercise.items if item.id == item_labels[label])
        if len(item.questions) != 1 or item.questions[0].kind != "single-choice":
            raise SourceError(
                f"{context}, gap [{label}]: linked item must contain one single-choice question"
            )
    _validate_option_feedback(exercise.metadata, exercise.questions, context)
    _validate_gap_feedback(exercise.metadata, exercise.questions, context)
    if exercise.metadata.interaction == "typed-gap" and not any(
        question.kind == "typed-gap" for question in exercise.questions
    ):
        raise SourceError(f"{context}: typed-gap metadata has no labelled gaps")
    if not exercise.questions:
        raise SourceError(f"{context}: exercise contains no supported questions")
    return exercise


def _front_matter(source: str, context: str) -> tuple[dict, str]:
    """Remove and validate an optional leading YAML module declaration.

    Present front matter requires ``id`` and ``title``; ``order`` is optional.
    It is removed before heading analysis so YAML is never mistaken for teaching
    content. Without front matter, the caller derives identity and title from
    its fallback name and the level-one heading.
    """
    lines = source.splitlines(keepends=True)
    if not lines or lines[0].strip() != "---":
        return {}, source
    end = next((index for index in range(1, len(lines)) if lines[index].strip() == "---"), None)
    if end is None:
        raise SourceError(f"{context}: unterminated front matter")
    data = _yaml_mapping("".join(lines[1:end]), f"{context}, front matter")
    unknown = set(data) - {"id", "title", "order"}
    if unknown:
        raise SourceError(f"{context}: unsupported front matter fields {list(unknown)!r}")
    for key in ("id", "title"):
        if key not in data or not isinstance(data[key], str) or not data[key].strip():
            raise SourceError(f"{context}: front matter requires nonempty {key}")
    if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", data["id"]):
        raise SourceError(f"{context}: module id must be a lowercase URL-safe slug")
    if type(data.get("order", 0)) is not int:
        raise SourceError(f"{context}: front matter order must be an integer")
    return data, "".join(lines[end + 1 :])


def parse_document(
    source: str, document_slug: str | None = None, *, source_path: str = "document"
) -> Document:
    """Interpret one module's hierarchy and validate its exercise semantics.

    Parameters
    ----------
    source
        Complete authored Markdown, including optional front matter.
    document_slug
        Fallback module name, normally the source filename stem. Front matter
        ``id`` takes precedence; otherwise this value or the title is slugified.
    source_path
        File label included in validation errors, independent of generated URLs.

    Returns
    -------
    Document
        Module with subsections and exercises in authored order, rendered prose
        fragments and explicit scored/worked-model response data.

    Raises
    ------
    SourceError
        Required hierarchy is missing, identities collide within a source scope,
        or an exercise's answers or metadata violate the authoring contract.

    Notes
    -----
    Exactly one level-one title and at least one level-two subsection are
    required. Level-three headings must be ``Exercise N``; their numbers can
    repeat across subsections because IDs include the subsection slug.
    Level-four boundaries inside an exercise are interpreted by ``_exercise``.
    """
    data, source = _front_matter(source, source_path)
    markdown = MarkdownIt("commonmark", {"html": True}).enable("table")
    headings = _headings(markdown.parse(source))
    lines = source.splitlines(keepends=True)
    if not headings or headings[0].level != 1:
        raise SourceError(f"{source_path}: expected a level-one title")
    if sum(heading.level == 1 for heading in headings) != 1:
        raise SourceError(f"{source_path}: expected exactly one level-one title")
    title = data.get("title", headings[0].title)
    slug = data.get("id", slugify(document_slug or title))
    first_section = next(
        (heading.start for heading in headings if heading.level == 2), len(lines)
    )
    document = Document(
        title,
        slug,
        markdown.render("".join(lines[headings[0].end : first_section])),
        order=data.get("order", 0),
        source_path=source_path,
    )
    current_section = None
    exercise_started = False
    seen_sections = set()
    for index, heading in enumerate(headings):
        if heading.level == 2:
            section_slug = slugify(heading.title)
            if section_slug in seen_sections:
                raise SourceError(f"{source_path}: duplicate subsection slug {section_slug}")
            seen_sections.add(section_slug)
            end = next(
                (later.start for later in headings[index + 1 :] if later.level <= 3), len(lines)
            )
            current_section = Section(
                heading.title, section_slug, markdown.render("".join(lines[heading.end : end]))
            )
            document.sections.append(current_section)
            exercise_started = False
        elif heading.level == 3:
            if current_section is None:
                raise SourceError(
                    f"{source_path}, {heading.title}: exercise without a subsection"
                )
            if not re.fullmatch(r"Exercise\s+\d+", heading.title):
                raise SourceError(
                    f"{source_path}: unsupported exercise heading {heading.title!r}"
                )
            end = next(
                (later.start for later in headings[index + 1 :] if later.level <= 3), len(lines)
            )
            identifier = f"{slug}--{current_section.slug}--{slugify(heading.title)}"
            context = f"{source_path}, {current_section.title}, {heading.title}"
            if any(exercise.id == identifier for exercise in current_section.exercises):
                raise SourceError(f"{context}: duplicate exercise title within subsection")
            current_section.exercises.append(
                _exercise(
                    markdown,
                    "".join(lines[heading.end : end]),
                    heading.title,
                    identifier,
                    context,
                )
            )
            exercise_started = True
        elif heading.level >= 4 and not exercise_started:
            raise SourceError(f"{source_path}, {heading.title}: item without an exercise")
    if not document.sections:
        raise SourceError(f"{source_path}: no level-two subsections")
    return document


def discover_documents(source: Path) -> list[Document]:
    """Load modules and establish their deterministic course order.

    Parameters
    ----------
    source
        One Markdown file or a directory searched recursively for ``*.md``.

    Returns
    -------
    list of Document
        Parsed modules sorted by ``(order, slug)`` after checking unique module
        IDs across files. Each source path is retained for diagnostics.

    Raises
    ------
    SourceError
        A directory contains no Markdown modules, two files share a module ID,
        or a module violates the source contract.
    """
    paths = sorted(source.rglob("*.md")) if source.is_dir() else [source]
    if not paths:
        raise SourceError(f"{source}: no Markdown modules found")
    documents = []
    seen_ids = {}
    for path in paths:
        document = parse_document(
            path.read_text(encoding="utf-8"), path.stem, source_path=str(path)
        )
        if document.slug in seen_ids:
            raise SourceError(
                f"{path}: duplicate module id {document.slug!r}; also in {seen_ids[document.slug]}"
            )
        seen_ids[document.slug] = path
        documents.append(document)
    return sorted(documents, key=lambda document: (document.order, document.slug))
