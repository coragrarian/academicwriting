"""Decide which static pages exist and how the parsed course connects.

The parser has already interpreted Markdown and validated authored answers.
Here, semantic blocks become HTML, entity slugs become relative page paths,
and ordered modules become one terminating course sequence. Jinja owns the
page structure; this module supplies its context and browser checking data.

Notes
-----
``exercises.js`` evaluates responses: emitting an answer payload is not
checking an answer. Worked models resolve responses without scoring them.
The orientation matching exercise changes display order only, preserving
semantic IDs and option indices used by saved learner state.

Output is staged in a recognised sibling directory before the previous site
is removed. The marker guards deletion; staging protects against rendering
failures, but the final remove-and-rename is not an atomic directory swap.
"""

import html
import os
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from xml.etree import ElementTree as ET

from jinja2 import Environment, FileSystemLoader, select_autoescape

from .model import Block, Document, Exercise, Feedback, Question, Section
from .people import COORDINATORS, DATA_PLATFORM, RESEARCH_TEAM

ROOT = Path(__file__).resolve().parent.parent
TEMPLATES = ROOT / "templates"
STATIC = ROOT / "static"
SITE_TITLE = "Academic Writing for Agrarian Sciences"
SITE_URL = "https://coragrarian.github.io/academicwriting/"


@dataclass(frozen=True)
class PageMetadata:
    """Publication identity shared by search and social previews."""

    title: str
    description: str
    canonical_url: str | None
    image_url: str
    robots: str | None = None
    image_alt: str = (
        "Academic Writing for Agrarian Sciences. Interactive self-study activities "
        "for academic writing in the Agrarian Sciences. UFMG · FAPEMIG · CAPES."
    )


def _page_metadata(
    path: Path,
    *,
    page_title: str | None,
    document: Document | None,
    section: Section | None,
    exercise: Exercise | None,
) -> PageMetadata:
    """Describe semantic page content without inspecting rendered HTML.

    Canonicals always name the production deployment, including local builds.
    Index pages use their directory URL; exercise titles include their section
    so repeated exercise numbers remain meaningful outside the course UI.
    """
    not_found = path == Path("404.html")
    if not_found:
        description = "The page you requested does not exist or may have moved."
    elif exercise and section and document:
        page_title = f"{exercise.title}: {section.title}"
        description = (
            f"Interactive {exercise.title.lower()} on “{section.title}” "
            f"in the module “{document.title}”."
        )
    elif section and document:
        description = (
            f"Academic-writing activities on “{section.title}” "
            f"in the module “{document.title}”."
        )
    elif document:
        description = (
            f"{document.title}: interactive academic-writing activities "
            "for Agrarian Sciences research articles."
        )
    elif path == Path("about/index.html"):
        description = (
            "Research, CorAgrarian, pedagogical materials, project information and "
            "the research team behind Academic Writing for Agrarian Sciences."
        )
    else:
        description = (
            "Interactive self-study activities for academic writing in research "
            "articles in the Agrarian Sciences."
        )
    return PageMetadata(
        title=f"{page_title} · {SITE_TITLE}" if page_title else SITE_TITLE,
        description=description,
        # A fallback can be served at any missing URL; none is canonical content.
        canonical_url=None if not_found else SITE_URL + path.as_posix().removesuffix("index.html"),
        image_url=SITE_URL + "assets/social-preview.png",
        robots="noindex" if not_found else None,
    )


def _home_module_title(title: str) -> str:
    """Shorten the recognised module-title pattern for Home only."""
    match = re.fullmatch(r"The (.+) section", title)
    return match.group(1) if match else title


def _plain(value: str) -> str:
    """Extract label text from project-generated HTML fragments.

    Semantic option and prompt text can contain inline HTML, whereas native
    select options and accessible labels need plain text. Tag removal followed
    by entity decoding is sufficient for those generated fragments; this is
    not a general-purpose HTML parser or a sanitiser for arbitrary input.
    """
    return html.unescape(re.sub(r"<[^>]*>", "", value))


def _select(question: Question) -> str:
    """Render an inline response control with its accessibility hooks.

    Typed gaps use a text input; other inline responses use a select whose
    values are semantic option indices. Both retain the question ID and an
    initially hidden feedback region linked by ``aria-describedby``.
    Correctness data is emitted separately by ``_answer_data``.
    """
    label = question.label or _plain(question.prompt_html) or "Choose an answer"
    attributes = (
        f'id="{question.id}" data-question="{question.id}" '
        f'aria-label="{html.escape(label)}" aria-describedby="{question.id}-feedback"'
    )
    feedback = (
        f'<span class="response-feedback sr-only" id="{question.id}-feedback" '
        "data-response-feedback hidden></span>"
    )
    if question.kind == "typed-gap":
        return (
            f'<input class="typed-gap" type="text" {attributes} '
            'autocomplete="off" autocapitalize="off" spellcheck="false">' + feedback
        )
    options = ['<option value="">Select an answer</option>']
    for index, option in enumerate(question.options):
        options.append(
            f'<option value="{index}">{html.escape(_plain(option.text_html))}</option>'
        )
    return (
        f'<select class="inline-select" {attributes}>' + "".join(options) + "</select>" + feedback
    )


def _render_block(
    env: Environment, block: Block, questions: dict[str, Question], *, example: bool = False
) -> str:
    """Resolve one semantic block for an exercise or a worked model.

    Instruction blocks receive their shared wrapper; standalone questions use
    ``question.html``. Prose can contain ``@@question-id@@`` placeholders left
    by the parser. These become inline controls in scored content, or authored
    answers in a worked model. Question lookup uses semantic IDs, independent
    of the order in which blocks are displayed.

    Parameters
    ----------
    questions
        Response lookup for this container, including worked-model questions
        when ``example`` is true.
    example
        Resolve correct answers for display without creating response controls.
    """
    if block.kind == "instruction":
        return (
            '<div class="instructions"><p class="eyebrow">Instructions</p>'
            f"<p>{block.html}</p></div>"
        )
    if block.kind == "question":
        question = questions[block.question_id]
        return env.get_template("question.html").render(question=question, example=example)

    def replace(match: re.Match[str]) -> str:
        question_id = match.group(1)
        question = questions[question_id]
        if example:
            return (
                html.escape(question.answer)
                if question.answer
                else next(option.text_html for option in question.options if option.correct)
            )
        return _select(question)

    return re.sub(r"@@([a-z0-9-]+-q\d+)@@", replace, block.html)


def _feedback_data(feedback: Feedback) -> dict:
    return {"correct": feedback.correct, "incorrect": feedback.incorrect}


def _answer_data(exercise: Exercise) -> dict:
    """Prepare the JSON-serialisable checking contract for ``exercises.js``.

    Returns
    -------
    dict
        ``questions`` maps scored response IDs to kinds, expected answers and
        response-specific feedback. ``groups`` preserves exercise-level and
        Item scopes, with the responses that must all be correct together.
        ``feedback`` supplies the exercise-level correct/incorrect fallback.

    Notes
    -----
    Expected typed-gap answers are strings; other answers are lists of option
    indices. Item option/gap feedback overrides matching exercise entries.
    Worked models are excluded. Feedback is authored metadata: the renderer
    neither invents explanations nor evaluates learner responses.
    """
    questions = {}
    groups = []
    scopes = [("exercise", None, exercise.direct_questions, exercise.metadata)] + [
        (item.id, item.title, item.questions, item.metadata) for item in exercise.items
    ]
    for group_id, title, responses, metadata in scopes:
        if not responses:
            continue
        groups.append(
            {
                "id": group_id,
                "title": title,
                "questions": [question.id for question in responses],
                "feedback": _feedback_data(metadata.feedback),
            }
        )
        option_feedback = exercise.metadata.feedback.options | metadata.feedback.options
        gap_feedback = exercise.metadata.feedback.gaps | metadata.feedback.gaps
        for question in responses:
            questions[question.id] = {
                "kind": question.kind,
                "expected": question.answer
                if question.kind == "typed-gap"
                else question.correct_indices,
                "label": question.label,
                "gap_feedback": gap_feedback.get(question.source_label),
                "option_feedback": {
                    str(index): option_feedback[option.key]
                    for index, option in enumerate(question.options)
                    if option.key in option_feedback
                },
            }
    return {
        "questions": questions,
        "groups": groups,
        "feedback": _feedback_data(exercise.metadata.feedback),
    }


def _path_for(
    document: Document, section: Section | None = None, exercise: Exercise | None = None
) -> Path:
    """Return ``module/section/exercise/index.html`` relative to the site root.

    Omitting the exercise or both optional levels selects an overview page.
    """
    path = Path(document.slug)
    if section is not None:
        path /= section.slug
    if exercise is not None:
        path /= exercise.slug
    return path / "index.html"


def _display_blocks(exercise: Exercise) -> list[Block]:
    """Hide the orientation answer pattern through presentation order only.

    The Introduction orientation matching rows would reveal their A–B–C–D
    mapping if displayed in canonical order. Display them as D, B, A, C while
    retaining the same blocks, question IDs, option indices and answer keys.
    Saved responses therefore still refer to the same semantic questions.

    Notes
    -----
    This exercise-specific transformation belongs to presentation, not source
    interpretation. Canonical Markdown and the model are unchanged. Apply it
    only when the recognised exercise contains the expected matching labels;
    alternative sources otherwise retain their authored order.
    """
    if exercise.id != (
        "introduction--the-introduction-section-of-research-papers--exercise-1"
    ):
        return exercise.blocks
    if any(question.kind != "matching" for question in exercise.direct_questions):
        return exercise.blocks
    questions = {question.id: question for question in exercise.direct_questions}
    purpose_blocks = {}
    for block in exercise.blocks:
        if block.kind == "question":
            question = questions[block.question_id]
            label = _plain(question.options[question.correct_indices[0]].text_html)
            purpose_blocks[label] = block
    if set(purpose_blocks) != {"A", "B", "C", "D"}:
        return exercise.blocks
    # Keep the source table, answer keys and positional IDs intact. Only the
    # displayed purposes change order, so existing learner state stays valid.
    ordered = iter(purpose_blocks[label] for label in ("D", "B", "A", "C"))
    return [next(ordered) if block.kind == "question" else block for block in exercise.blocks]


def _page_navigation(documents: list[Document], root: Path) -> dict[Path, dict[str, str | bool]]:
    """Derive Previous/Next context from one ordered, terminating course.

    Parameters
    ----------
    documents
        Modules already sorted into course order. Each module overview is
        followed by its subsection overviews and their exercises.
    root
        Build root used to calculate links relative to each generated page.

    Returns
    -------
    dict
        Page paths mapped to relative targets, contextual labels and a
        terminal flag for Jinja. Home and About are outside the learning
        sequence; its first Previous and final Next links lead to Home.

    Notes
    -----
    Next must never wrap to a module or subsection overview. Such a fallback
    would revisit a learning node instead of terminating at Home / contents.
    """
    # Informational pages stay outside this sequence; its final link explicitly
    # terminates at Home / contents.
    course_sequence = []
    module_paths = set()
    section_paths = set()
    for document in documents:
        module_path = _path_for(document)
        module_paths.add(module_path)
        course_sequence.append(module_path)
        for section in document.sections:
            section_path = _path_for(document, section)
            section_paths.add(section_path)
            course_sequence.append(section_path)
            course_sequence.extend(
                _path_for(document, section, exercise) for exercise in section.exercises
            )

    page_navigation = {}
    home_path = Path("index.html")
    for index, current in enumerate(course_sequence):
        previous = course_sequence[index - 1] if index else home_path
        terminal = index + 1 == len(course_sequence)
        following = home_path if terminal else course_sequence[index + 1]
        if terminal:
            next_label = "Back to contents"
        elif following in module_paths:
            next_label = "Next module"
        elif current in module_paths:
            next_label = "Begin module"
        elif following in section_paths:
            next_label = "Next subsection"
        elif current in section_paths:
            next_label = "Begin exercises"
        else:
            next_label = "Next"
        page_navigation[current] = {
            "previous_url": link_for(root, current, previous),
            "previous_label": "Home" if index == 0 else "Previous",
            "next_url": link_for(root, current, following),
            "next_label": next_label,
            "next_terminal": terminal,
        }
    return page_navigation


def build_site(documents: list[Document] | Document, output: Path) -> None:
    """Stage a complete portable site, then replace recognised output.

    Parameters
    ----------
    documents
        Parsed modules, or one module for a standalone build. Modules are
        ordered by ``(order, slug)`` before paths and navigation are derived.
    output
        Generated site directory. An existing directory must contain the
        ``.agrarian-built`` marker; the same rule protects its ``.building``
        sibling from deletion on a subsequent attempt.

    Raises
    ------
    ValueError
        No modules, duplicate/reserved module slugs, or unrecognised output/staging
        directories that the builder refuses to replace.
    OSError
        Assets or generated pages cannot be copied, written or replaced.
    jinja2.TemplateError
        A template cannot be loaded or rendered.

    Notes
    -----
    The pipeline copies assets, derives global navigation, renders semantic
    blocks and checking payloads, then supplies page-specific Jinja context.
    Normal content pages use relative asset/page links, including single-module builds.
    Home, About and the 404 fallback use the public shell without course runtime
    data. Only normal content URLs enter the sitemap. Home terminates the course
    rather than becoming another learning node.

    Rendering occurs in a marked sibling directory, leaving an existing site
    intact if rendering fails. Only after every page is written is recognised
    output removed and staging renamed. That final replacement has no rollback
    and is not a filesystem-atomic swap. The marker is a deletion safety
    contract, not evidence that a partially staged build finished successfully.
    """
    if isinstance(documents, Document):
        documents = [documents]
    if not documents or len({document.slug for document in documents}) != len(documents):
        raise ValueError("Expected at least one module with unique module IDs")
    for document in documents:
        if document.slug == "about":
            raise ValueError(
                f"{document.source_path}: module id 'about' conflicts with the public About page"
            )
    documents = sorted(documents, key=lambda document: (document.order, document.slug))
    env = Environment(loader=FileSystemLoader(TEMPLATES), autoescape=select_autoescape(["html"]))
    output = output.resolve()
    temp = output.with_name(output.name + ".building")
    if output.exists() and not (output / ".agrarian-built").exists():
        raise ValueError(f"Refusing to replace unrecognised output directory: {output}")
    if temp.exists():
        if not (temp / ".agrarian-built").exists():
            raise ValueError(f"Refusing to replace unrecognised temporary directory: {temp}")
        shutil.rmtree(temp)
    # The marker authorises deletion on a later attempt, even if rendering fails.
    temp.mkdir(parents=True)
    (temp / ".agrarian-built").write_text("Generated by agrarian_builder.\n")
    shutil.copytree(STATIC, temp / "assets")

    module_ids = {
        document.slug: [
            exercise.id for section in document.sections for exercise in section.exercises
        ]
        for document in documents
    }
    page_navigation = _page_navigation(documents, temp)
    content_urls: list[str] = []

    def write_page(
        path: Path,
        template: str,
        document: Document | None = None,
        *,
        page_title: str | None = None,
        section: Section | None = None,
        exercise: Exercise | None = None,
        **content: object,
    ) -> None:
        """Combine shared course context with page-specific semantic content.

        Link callbacks are relative to this destination, so templates need no
        knowledge of deployment prefixes or their depth in the page tree.
        ``site_data`` supplies progress/navigation identities; exercise pages
        separately receive the checking payload as ``answers``.
        """
        destination = temp / path
        destination.parent.mkdir(parents=True, exist_ok=True)

        def link(target: Path) -> str:
            # GitHub Pages serves 404.html at the requested missing path, which
            # may be nested. Its assets and recovery links need a fixed base.
            if path == Path("404.html"):
                return SITE_URL + target.as_posix().removesuffix("index.html")
            return os.path.relpath(temp / target, destination.parent).replace(os.sep, "/")

        # Course templates distinguish absent levels from defined objects when
        # marking the current overview. Preserve that undefined-variable contract.
        if section is not None:
            content["section"] = section
        if exercise is not None:
            content["exercise"] = exercise
        metadata = _page_metadata(
            path, page_title=page_title, document=document,
            section=section, exercise=exercise,
        )
        rendered = env.get_template(template).render(
            document=document,
            documents=documents,
            public_page=document is None,
            is_home=path == Path("index.html"),
            site_title=SITE_TITLE,
            metadata=metadata,
            module_exercise_counts={slug: len(ids) for slug, ids in module_ids.items()},
            home_module_title=_home_module_title,
            coordinators=COORDINATORS,
            research_team=RESEARCH_TEAM,
            data_platform=DATA_PLATFORM,
            site_data={
                "module": document.slug,
                "sections": {
                    section.slug: [exercise.id for exercise in section.exercises]
                    for section in document.sections
                },
                "modules": module_ids,
                "course_sections": {
                    module.slug: {
                        section.slug: [exercise.id for exercise in section.exercises]
                        for section in module.sections
                    }
                    for module in documents
                },
            }
            if document
            else None,
            total_exercises=len(module_ids[document.slug])
            if document
            else sum(map(len, module_ids.values())),
            asset_css=link(Path("assets/styles.css")),
            asset_js=link(Path("assets/exercises.js")),
            asset_navigation=link(Path("assets/navigation.js")),
            asset_favicon=link(Path("assets/favicon.svg")),
            asset_touch_icon=link(Path("assets/apple-touch-icon.png")),
            institution_asset=lambda filename: link(Path("assets/institutions") / filename),
            person_asset=lambda filename: link(Path("assets") / filename),
            module_url=link(_path_for(document)) if document else None,
            module_link=lambda module: link(_path_for(module)),
            course_section_url=lambda module, section: link(_path_for(module, section)),
            course_exercise_url=lambda module, section, exercise: link(
                _path_for(module, section, exercise)
            ),
            home_url=link(Path("index.html")),
            course_url=link(Path("index.html")) + "#course",
            about_url=link(Path("about/index.html")),
            repository_url="https://github.com/coragrarian/academicwriting",
            section_url=lambda section: link(_path_for(document, section)),
            exercise_url=lambda section, exercise: link(_path_for(document, section, exercise)),
            **page_navigation.get(path, {}),
            **content,
        )
        destination.write_text(rendered, encoding="utf-8")
        if metadata.canonical_url:
            content_urls.append(metadata.canonical_url)

    write_page(Path("index.html"), "home.html")
    write_page(Path("about/index.html"), "about.html", page_title="About", is_about=True)
    write_page(Path("404.html"), "not_found.html", page_title="Page not found")

    for document in documents:
        write_page(_path_for(document), "module.html", document, page_title=document.title)
        for section in document.sections:
            write_page(
                _path_for(document, section),
                "section.html",
                document,
                section=section,
                page_title=section.title,
                active_section=section,
            )
            for position, exercise in enumerate(section.exercises, start=1):
                question_map = {question.id: question for question in exercise.questions}
                display_blocks = _display_blocks(exercise)
                answers = _answer_data(exercise)
                # Review messages refer to displayed matching rows. Stable
                # response IDs continue to identify the original source keys.
                matching_rows = [
                    block for block in display_blocks
                    if block.kind == "question"
                    and question_map[block.question_id].kind == "matching"
                ]
                for row_number, block in enumerate(matching_rows, start=1):
                    answers["questions"][block.question_id]["label"] = f"Match {row_number}"
                rendered_items = [
                    {
                        "title": item.title,
                        "id": item.id,
                        "blocks": [
                            _render_block(env, block, question_map) for block in item.blocks
                        ],
                    }
                    for item in exercise.items
                ]
                rendered_examples = [
                    {
                        "title": item.title,
                        "blocks": [
                            _render_block(
                                env, block, {q.id: q for q in item.questions}, example=True
                            )
                            for block in item.blocks
                        ],
                    }
                    for item in exercise.examples
                ]
                write_page(
                    _path_for(document, section, exercise),
                    "exercise.html",
                    document,
                    section=section,
                    exercise=exercise,
                    page_title=exercise.title,
                    active_section=section,
                    rendered_items=rendered_items,
                    rendered_blocks=[
                        _render_block(env, block, question_map)
                        for block in display_blocks
                    ],
                    rendered_examples=rendered_examples,
                    answers=answers,
                    position=position,
                    total=len(section.exercises),
                )

    sitemap = ET.Element("urlset", xmlns="http://www.sitemaps.org/schemas/sitemap/0.9")
    for url in content_urls:
        ET.SubElement(ET.SubElement(sitemap, "url"), "loc").text = url
    ET.indent(sitemap, space="  ")
    ET.ElementTree(sitemap).write(temp / "sitemap.xml", encoding="utf-8", xml_declaration=True)

    if output.exists():
        shutil.rmtree(output)
    temp.rename(output)


def link_for(root: Path, current: Path, target: Path) -> str:
    """Link between site-relative page paths using portable URL separators."""
    return os.path.relpath(root / target, (root / current).parent).replace(os.sep, "/")
