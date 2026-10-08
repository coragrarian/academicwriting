"""Command-line entry point for the static site generator."""

import argparse
from pathlib import Path

from agrarian_builder.parser import SourceError, discover_documents
from agrarian_builder.renderer import build_site


def main() -> int:
    """Build discovered modules and report counts from the semantic model.

    Source and filesystem failures become command-line errors with a non-zero
    exit status. This entry point owns arguments and reporting; interpretation
    and output replacement remain in the parser and renderer respectively.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "source",
        type=Path,
        nargs="?",
        default=Path("exercises"),
        help="Markdown module or directory (default: exercises/)",
    )
    parser.add_argument("--output", type=Path, default=Path("_site"))
    arguments = parser.parse_args()
    try:
        documents = discover_documents(arguments.source)
        build_site(documents, arguments.output)
    except (OSError, SourceError, ValueError) as error:
        parser.exit(1, f"Build failed: {error}\n")
    for document in documents:
        print(f"Parsed: {document.title}")
    sections = sum(len(document.sections) for document in documents)
    exercises = sum(
        len(section.exercises) for document in documents for section in document.sections
    )
    print(f"Modules: {len(documents)}; subsections: {sections}; exercises: {exercises}")
    learning_pages = len(documents) + sections + exercises
    print(f"Learning pages: {learning_pages}")
    print(f"Content pages: {learning_pages + 2}; HTML files including 404: {learning_pages + 3}")
    print(f"Output: {arguments.output}/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
