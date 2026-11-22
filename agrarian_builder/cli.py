"""Validate authored Markdown, inspect the course manifest or build the site."""

import argparse
import difflib
import sys
from collections.abc import Sequence
from pathlib import Path

from jinja2 import TemplateError

from .manifest import course_manifest, format_manifest
from .parser import SourceError, discover_documents
from .policy import check_publication
from .renderer import build_site

COURSE_SOURCE = Path("exercises")
MANIFEST_PATH = Path("course.manifest.json")


def main(argv: Sequence[str] | None = None) -> int:
    """Run the repository CLI, retaining source context in failure diagnostics.

    Paths are relative to the working directory. Production builds and manifest
    write/check operations always read ``exercises/``; only ``validate`` and a
    read-only ``inspect`` accept a source file or another directory. Publication
    rules apply whenever the resolved source is ``exercises/``; any other file
    or directory is checked for grammar only.
    """
    parser = argparse.ArgumentParser(prog="agrarian", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    validate_command = commands.add_parser(
        "validate",
        help="Validate Markdown without generating site output.",
        description=(
            "Validate Markdown without generating site output. Publication rules "
            "apply when validating exercises/; a single file or any other directory "
            "is checked for grammar only."
        ),
    )
    validate_command.add_argument(
        "source",
        type=Path,
        nargs="?",
        default=COURSE_SOURCE,
        help=(
            "Markdown file or directory (default: exercises/; publication rules "
            "apply to exercises/, other sources are checked for grammar only)."
        ),
    )
    build_command = commands.add_parser(
        "build", help="Validate and rebuild the complete course from exercises/."
    )
    build_command.add_argument(
        "--output",
        type=Path,
        default=Path("_site"),
        help="Recognised build output directory (default: _site/).",
    )
    inspect_command = commands.add_parser(
        "inspect",
        help="Print, write or check the structural course manifest.",
        description=(
            "Print, write or check the structural course manifest. Publication rules "
            "apply when inspecting exercises/; a single file or any other directory "
            "is checked for grammar only."
        ),
    )
    inspect_command.add_argument(
        "source",
        type=Path,
        nargs="?",
        default=None,
        help=(
            "Markdown file or directory for stdout inspection (default: exercises/; "
            "publication rules apply to exercises/, other sources are checked for "
            "grammar only)."
        ),
    )
    mode = inspect_command.add_mutually_exclusive_group()
    mode.add_argument(
        "--write",
        action="store_true",
        help="Write course.manifest.json at the repository root from exercises/.",
    )
    mode.add_argument(
        "--check",
        action="store_true",
        help="Check that course.manifest.json matches exercises/.",
    )
    arguments = parser.parse_args(argv)
    if (
        arguments.command == "inspect"
        and (arguments.write or arguments.check)
        and arguments.source is not None
    ):
        parser.error("--write and --check always read exercises/; omit the source argument")

    if arguments.command == "validate":
        source = arguments.source
    elif arguments.command == "inspect":
        source = arguments.source or COURSE_SOURCE
    else:
        source = COURSE_SOURCE
    try:
        documents = discover_documents(source)
        if source.resolve() == COURSE_SOURCE.resolve():
            check_publication(documents)
        if arguments.command == "inspect":
            rendered = format_manifest(course_manifest(documents))
            if arguments.write:
                MANIFEST_PATH.write_text(rendered, encoding="utf-8")
                print(f"Wrote: {MANIFEST_PATH}")
                return 0
            if arguments.check:
                committed = MANIFEST_PATH.read_text(encoding="utf-8")
                if committed != rendered:
                    diff = "".join(
                        difflib.unified_diff(
                            committed.splitlines(keepends=True),
                            rendered.splitlines(keepends=True),
                            fromfile=str(MANIFEST_PATH),
                            tofile="exercises/",
                        )
                    )
                    if diff and not diff.endswith("\n"):
                        diff += "\n"
                    parser.exit(
                        1,
                        f"{diff}Course manifest is out of date: review the diff above, "
                        "then run agrarian inspect --write.\n",
                    )
                print("Manifest: up to date")
                return 0
            sys.stdout.write(rendered)
            return 0
        if arguments.command == "build":
            build_site(documents, arguments.output)
    except (OSError, SourceError, ValueError, TemplateError) as error:
        parser.exit(1, f"{arguments.command.capitalize()} failed: {error}\n")

    sections = sum(len(document.sections) for document in documents)
    exercises = sum(
        len(section.exercises) for document in documents for section in document.sections
    )
    print(f"Modules: {len(documents)}; subsections: {sections}; exercises: {exercises}")
    if arguments.command == "validate":
        print(f"Validated: {source}")
    else:
        learning_pages = len(documents) + sections + exercises
        print(f"Learning pages: {learning_pages}")
        print(
            f"Content pages: {learning_pages + 2}; HTML files including 404: {learning_pages + 3}"
        )
        print(f"Output: {arguments.output}")
    return 0
