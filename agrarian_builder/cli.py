"""Validate authored Markdown or regenerate the complete canonical course."""

import argparse
from collections.abc import Sequence
from pathlib import Path

from jinja2 import TemplateError

from .parser import SourceError, discover_documents
from .renderer import build_site


def main(argv: Sequence[str] | None = None) -> int:
    """Run the repository CLI, retaining source context in failure diagnostics.

    Paths are relative to the working directory. Production builds always read
    ``exercises/``; only validation accepts a source file or another directory.
    """
    parser = argparse.ArgumentParser(prog="agrarian", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    validate = commands.add_parser(
        "validate", help="Validate Markdown without generating site output."
    )
    validate.add_argument(
        "source",
        type=Path,
        nargs="?",
        default=Path("exercises"),
        help="Markdown file or directory (default: exercises/).",
    )
    build = commands.add_parser(
        "build", help="Validate and rebuild the complete course from exercises/."
    )
    build.add_argument(
        "--output",
        type=Path,
        default=Path("_site"),
        help="Recognised build output directory (default: _site/).",
    )
    arguments = parser.parse_args(argv)
    source = arguments.source if arguments.command == "validate" else Path("exercises")
    try:
        documents = discover_documents(source)
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
