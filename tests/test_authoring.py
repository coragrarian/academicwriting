"""Execute AUTHORING.md examples and verify error-catalogue completeness."""

import ast
import re
import shlex
from dataclasses import dataclass
from pathlib import Path

import pytest
from conftest import ROOT
from markdown_it import MarkdownIt

from agrarian_builder.parser import SourceError, parse_document
from agrarian_builder.policy import check_publication

AUTHORING_DOC = ROOT / "AUTHORING.md"
CATALOGUE_HEADING = "10. Error catalogue"
NON_EXECUTABLE_FENCES = frozenset({"sh", "text", "yaml"})
EXERCISE_WRAPPER = """\
---
id: example
title: Example module
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

{body}"""


@dataclass(frozen=True)
class ExampleBlock:
    """One fenced executable example extracted from AUTHORING.md."""

    section: str
    line: int
    scope: str
    expectation: str
    expected_message: str | None
    body: str


def parse_fence_info(info: str, line: int) -> tuple[str, str, str | None] | None:
    """Parse a fenced-block info string, rejecting unrecognised forms."""
    stripped = info.strip()
    if stripped in NON_EXECUTABLE_FENCES:
        return None
    try:
        parts = shlex.split(stripped)
    except ValueError as error:
        raise ValueError(f"AUTHORING.md:{line}: malformed fence info {info!r}: {error}") from error
    if len(parts) != 4 or parts[0] != "markdown" or parts[1] != "agrarian":
        raise ValueError(
            f"AUTHORING.md:{line}: unrecognised fence info {info!r}; "
            "expected 'markdown agrarian <scope> <expectation>' or a plain code fence"
        )
    scope = parts[2]
    if scope not in {"module", "exercise"}:
        raise ValueError(
            f"AUTHORING.md:{line}: unsupported example scope {scope!r} in {info!r}"
        )
    expectation = parts[3]
    if expectation == "valid":
        return scope, "valid", None
    if expectation.startswith("invalid="):
        substring = expectation.removeprefix("invalid=")
        if not substring:
            raise ValueError(
                f"AUTHORING.md:{line}: invalid example requires a nonempty message substring"
            )
        return scope, "invalid", substring
    raise ValueError(
        f"AUTHORING.md:{line}: unsupported example expectation {expectation!r} in {info!r}"
    )


def extract_examples(markdown_text: str) -> list[ExampleBlock]:
    """Collect every executable ``markdown agrarian`` fenced block from AUTHORING.md."""
    markdown = MarkdownIt("commonmark").enable("table")
    tokens = markdown.parse(markdown_text)
    examples: list[ExampleBlock] = []
    current_section = ""
    for index, token in enumerate(tokens):
        if token.type == "heading_open" and token.tag == "h2":
            current_section = tokens[index + 1].content.strip()
        elif token.type == "fence":
            line = (token.map[0] + 1) if token.map else 0
            parsed = parse_fence_info(token.info, line)
            if parsed is None:
                continue
            scope, expectation, expected_message = parsed
            examples.append(
                ExampleBlock(
                    section=current_section,
                    line=line,
                    scope=scope,
                    expectation=expectation,
                    expected_message=expected_message,
                    body=token.content,
                )
            )
    return examples


def extract_catalogue_templates(markdown_text: str) -> set[str]:
    """Extract every backticked message template from the Error catalogue table."""
    markdown = MarkdownIt("commonmark").enable("table")
    tokens = markdown.parse(markdown_text)
    in_catalogue = False
    in_tbody = False
    in_row = False
    column = -1
    templates: set[str] = set()
    headers: list[str] = []
    in_thead = False
    for index, token in enumerate(tokens):
        if token.type == "heading_open" and token.tag == "h2":
            heading = tokens[index + 1].content.strip()
            if in_catalogue:
                break
            in_catalogue = heading == CATALOGUE_HEADING
            continue
        if not in_catalogue:
            continue
        if token.type == "thead_open":
            in_thead = True
        elif token.type == "thead_close":
            in_thead = False
        elif in_thead and token.type == "inline":
            headers.append(token.content.strip())
        elif token.type == "tbody_open":
            in_tbody = True
        elif token.type == "tbody_close":
            in_tbody = False
        elif in_tbody and token.type == "tr_open":
            in_row = True
            column = -1
        elif in_tbody and token.type == "tr_close":
            in_row = False
        elif in_row and token.type == "td_open":
            column += 1
        elif in_row and column == 0 and token.type == "inline":
            code_tokens = [
                child.content for child in token.children or () if child.type == "code_inline"
            ]
            assert len(code_tokens) == 1, (
                f"Expected one backticked template in catalogue row, found {token.content!r}"
            )
            template = code_tokens[0]
            assert template not in templates, f"Duplicate error-catalogue template {template!r}"
            templates.add(template)
    assert headers == ["Message template", "Cause", "Fix"], headers
    return templates


def render_source_error_template(node: ast.AST, path: Path, line: int) -> str:
    """Render one ``SourceError(...)`` argument into its catalogue message template."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        rendered = node.value
    elif isinstance(node, ast.JoinedStr):
        parts: list[str] = []
        for value in node.values:
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                parts.append(value.value)
            elif isinstance(value, ast.FormattedValue):
                parts.append("…")
            else:
                pytest.fail(f"{path}:{line}: unsupported f-string part {ast.dump(value)}")
        rendered = "".join(parts)
    else:
        pytest.fail(
            f"{path}:{line}: SourceError message is not an f-string or string literal: "
            f"{ast.dump(node)}"
        )
    return re.sub(r"^…(?:, …)*: ", "", rendered)


def collect_code_templates() -> set[str]:
    """Collect every ``raise SourceError(...)`` template in parser.py and policy.py."""
    templates: set[str] = set()
    for relative in ("agrarian_builder/parser.py", "agrarian_builder/policy.py"):
        path = ROOT / relative
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Raise) or not isinstance(node.exc, ast.Call):
                continue
            func = node.exc.func
            is_source_error = (isinstance(func, ast.Name) and func.id == "SourceError") or (
                isinstance(func, ast.Attribute) and func.attr == "SourceError"
            )
            if not is_source_error:
                continue
            if len(node.exc.args) != 1 or node.exc.keywords:
                pytest.fail(
                    f"{path}:{node.lineno}: expected one positional argument to SourceError"
                )
            templates.add(render_source_error_template(node.exc.args[0], path, node.lineno))
    return templates


EXAMPLES = extract_examples(AUTHORING_DOC.read_text(encoding="utf-8"))


@pytest.mark.parametrize(
    "example",
    EXAMPLES,
    ids=[
        f"line-{item.line}-{item.scope}-{item.expectation}"
        for item in EXAMPLES
    ],
)
def test_authoring_examples_execute_against_parser_and_policy(example: ExampleBlock):
    source = (
        example.body
        if example.scope == "module"
        else EXERCISE_WRAPPER.format(body=example.body)
    )
    if example.expectation == "valid":
        document = parse_document(source, source_path=f"AUTHORING.md:{example.line}")
        check_publication([document])
    else:
        assert example.expected_message is not None
        with pytest.raises(SourceError) as error:
            document = parse_document(source, source_path=f"AUTHORING.md:{example.line}")
            check_publication([document])
        assert example.expected_message in str(error.value)


def test_authoring_examples_cover_all_response_kinds_and_sections():
    response_kinds: set[str] = set()
    invalid_sections: set[str] = set()
    for example in EXAMPLES:
        if example.expectation == "valid" and example.section.startswith("5."):
            source = (
                example.body
                if example.scope == "module"
                else EXERCISE_WRAPPER.format(body=example.body)
            )
            document = parse_document(source, source_path=f"AUTHORING.md:{example.line}")
            for section in document.sections:
                for exercise in section.exercises:
                    response_kinds.update(question.kind for question in exercise.questions)
        elif example.expectation == "invalid":
            invalid_sections.add(example.section.split(".", 1)[0])
    assert response_kinds == {
        "single-choice",
        "multi-select",
        "inline-choice",
        "gap",
        "typed-gap",
        "matching",
    }
    assert {"2", "3", "4", "5", "6"} <= invalid_sections


@pytest.mark.parametrize(
    "bad_info",
    [
        "",
        "markdown",
        "markdown agrarian",
        "markdown agrarian bogus valid",
        "markdown agrarian exercise",
        "markdown agrarian exercise unknown",
        'markdown agrarian exercise invalid=""',
        "markdown agrarian exercise valid extra",
        "agrarian exercise valid",
        "python",
    ],
)
def test_unrecognised_fence_info_strings_are_rejected(bad_info: str):
    with pytest.raises(ValueError, match="AUTHORING.md:10:"):
        parse_fence_info(bad_info, 10)


def test_error_catalogue_matches_every_source_error_in_parser_and_policy():
    catalogue = extract_catalogue_templates(AUTHORING_DOC.read_text(encoding="utf-8"))
    code = collect_code_templates()
    missing = sorted(code - catalogue)
    stale = sorted(catalogue - code)
    assert not missing and not stale, f"missing={missing!r}, stale={stale!r}"


def test_non_literal_source_error_argument_fails_naming_line():
    call = ast.parse("raise SourceError(message)\n").body[0]
    assert isinstance(call, ast.Raise) and isinstance(call.exc, ast.Call)
    with pytest.raises(pytest.fail.Exception, match=r"sample\.py:42:.*not an f-string or string"):
        render_source_error_template(call.exc.args[0], Path("sample.py"), 42)
