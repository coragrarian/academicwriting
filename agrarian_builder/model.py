"""Represent authored exercises between Markdown interpretation and rendering.

``Document`` represents a module and contains ``Section`` objects, which contain
``Exercise`` objects. An exercise keeps shared blocks and direct questions
separate from named items and worked examples. Blocks preserve reading order;
questions preserve response identity and canonical answers.

Prose and option text are already rendered HTML fragments. Inline questions
remain ``@@question-id@@`` placeholders until the renderer supplies controls or
worked answers. These classes do not choose page layout, construct navigation
or check learner responses. The parser validates authored relationships;
the dataclasses themselves do not enforce them.
"""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Option:
    """One alternative whose semantic position becomes its response value.

    ``text_html`` preserves authored inline formatting. ``correct`` records the
    answer key, while optional ``key`` is the authored letter in ``a)``-style
    options used to attach feedback. That letter is distinct from the zero-based
    index submitted by the browser.
    """

    text_html: str
    correct: bool
    key: str | None = None


@dataclass
class Feedback:
    """Authored explanations attached to an exercise or item scope.

    ``correct`` and ``incorrect`` describe the scope's overall result. ``options``
    maps authored option letters to explanations; ``gaps`` maps original gap
    labels to explanations. The renderer combines shared and local feedback,
    and the browser decides which messages apply to the learner's attempt.
    """

    correct: str | None = None
    incorrect: str | None = None
    options: dict[str, str] = field(default_factory=dict)
    gaps: dict[str, str] = field(default_factory=dict)


@dataclass
class Metadata:
    """Keep interaction declarations and feedback alongside their source scope.

    A missing interaction leaves response syntax to determine the question
    type. Currently ``typed-gap`` is the only explicit interaction override;
    an item can inherit that declaration from its exercise.
    """

    interaction: str | None = None
    feedback: Feedback = field(default_factory=Feedback)


@dataclass
class Question:
    """A response with stable identity and an explicit canonical answer.

    Attributes
    ----------
    id
        Container-based identifier such as ``context-q1`` or ``item-a-q1``.
        It is local to an exercise; persistence also uses the exercise ID.
    kind
        ``single-choice``, ``multi-select``, ``inline-choice``, ``gap``,
        ``matching`` or ``typed-gap``. The renderer and browser dispatch on it.
    options
        Alternatives in semantic order. Correct indices refer to this order,
        even when the renderer changes the order of displayed questions.
    prompt_html
        Authored prompt fragment, used for matching rows.
    label
        Response description used by controls and feedback.
    answer
        Canonical text for a typed gap; other kinds use option correctness.
    source_label
        Original gap label, used to associate gap-specific feedback rather
        than to identify the response in saved state.

    Notes
    -----
    IDs are numbered within their container during parsing. Inserting or
    reordering semantic responses can change saved-state meaning, as can
    changing option order. Changing learner-facing presentation must leave
    these identities and response values intact.
    """

    id: str
    kind: str
    options: list[Option] = field(default_factory=list)
    prompt_html: str = ""
    label: str = ""
    answer: str | None = None
    source_label: str | None = None

    @property
    def correct_indices(self) -> list[int]:
        return [index for index, option in enumerate(self.options) if option.correct]


@dataclass
class Block:
    """A reading-order fragment or reference to a standalone question.

    ``html`` and ``instruction`` blocks carry HTML fragments. An ``html``
    fragment can also contain response placeholders for its container. A
    ``question`` block instead carries ``question_id`` for template rendering;
    it does not duplicate the question's answer data.
    """

    kind: str  # html, instruction or question
    html: str = ""
    question_id: str = ""


@dataclass
class ExerciseItem:
    """A named item or worked model with its own blocks and metadata.

    Items form response groups within an exercise. Worked models use the same
    representation but belong to ``Exercise.examples``: their questions explain
    answers and are excluded from scoring. A model may contain only prose,
    whereas the parser requires an ordinary item to contain a supported question.
    """

    title: str
    id: str = ""
    blocks: list[Block] = field(default_factory=list)
    questions: list[Question] = field(default_factory=list)
    metadata: Metadata = field(default_factory=Metadata)


@dataclass
class Exercise:
    """One exercise page with shared content, scored items and worked examples.

    Attributes
    ----------
    id
        Module/subsection/exercise identity used for progress and saved answers.
    slug
        Exercise path component, unique within its subsection.
    blocks, direct_questions
        Shared exercise content and responses outside named items. Blocks keep
        content order; questions are the semantic response catalogue.
    items
        Named scored scopes, each carrying its own content and metadata.
    examples
        Worked models, deliberately outside the scored ``questions`` view.
    metadata
        Shared interaction and feedback declarations; item metadata can supply
        local interaction declarations and feedback.
    """

    title: str
    slug: str
    id: str
    blocks: list[Block] = field(default_factory=list)
    direct_questions: list[Question] = field(default_factory=list)
    items: list[ExerciseItem] = field(default_factory=list)
    examples: list[ExerciseItem] = field(default_factory=list)
    metadata: Metadata = field(default_factory=Metadata)

    @property
    def instructions(self) -> list[Block]:
        return [block for block in self.blocks if block.kind == "instruction"]

    @property
    def context(self) -> list[Block]:
        return [block for block in self.blocks if block.kind == "html"]

    @property
    def questions(self) -> list[Question]:
        """Return scored responses in semantic order, excluding worked models."""
        return self.direct_questions + [
            question for item in self.items for question in item.questions
        ]


@dataclass
class Section:
    """A subsection overview followed by exercises in authored order.

    ``introduction_html`` is prose before the subsection's first exercise.
    ``slug`` supplies its module-relative path component.
    """

    title: str
    slug: str
    introduction_html: str
    exercises: list[Exercise] = field(default_factory=list)


@dataclass
class Document:
    """A module with overview prose, subsections and discovery metadata.

    ``slug`` is the module's URL and persistence identity. Front matter can
    supply it independently of the title. ``order`` controls module sequencing,
    with the slug breaking ties. ``source_path`` is diagnostic context for
    authored-source errors, not a generated page path.
    """

    title: str
    slug: str
    introduction_html: str
    sections: list[Section] = field(default_factory=list)
    order: int = 0
    source_path: str = "document"
