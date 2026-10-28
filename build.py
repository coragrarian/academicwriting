"""Compatibility entry point for ``agrarian build`` (whole course only)."""

import sys

from agrarian_builder.cli import main

if __name__ == "__main__":
    raise SystemExit(main(["build", *sys.argv[1:]]))
