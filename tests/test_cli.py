"""Exercise the installed console script and whole-course production boundary."""

import shutil
import subprocess
import sys
import sysconfig
from pathlib import Path

import pytest
from conftest import ROOT, SYNTHETIC_COURSE
from test_extensibility import assert_shape, file_bytes, structure

from agrarian_builder import renderer
from agrarian_builder.cli import main
from agrarian_builder.parser import discover_documents

ENTRY_POINT = Path(sysconfig.get_path("scripts")) / "agrarian"


@pytest.fixture
def course(tmp_path):
    shutil.copytree(SYNTHETIC_COURSE, tmp_path / "exercises")
    return tmp_path


def run_cli(directory, *arguments):
    return subprocess.run(
        [str(ENTRY_POINT), *map(str, arguments)],
        cwd=directory,
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.mark.parametrize("arguments", [("--help",), ("validate", "--help"), ("build", "--help")])
def test_installed_entry_point_help(tmp_path, arguments):
    result = run_cli(tmp_path, *arguments)
    assert result.returncode == 0, result.stderr
    assert "usage:" in result.stdout
    assert "agrarian" in result.stdout
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("target", [None, "exercises", "exercises/30-first.md"])
def test_validate_does_not_write_any_output(course, target):
    before = file_bytes(course)
    result = run_cli(course, "validate", *([target] if target else []))
    assert result.returncode == 0, result.stderr
    assert "Validated:" in result.stdout
    expected = "Modules: 1;" if target and target.endswith(".md") else "Modules: 4;"
    assert expected in result.stdout
    assert file_bytes(course) == before
    assert not (course / "_site").exists()
    assert not (course / "_site.building").exists()


def test_targeted_validation_reports_source_context_without_validating_siblings(course):
    path = course / "exercises/20-third.md"
    path.write_text(
        "# Broken module\n\n## Broken subsection\n\n### Exercise 1\n\n#### Item A\n\n- [ ] No\n"
    )
    result = run_cli(course, "validate", "exercises/30-first.md")
    assert result.returncode == 0, result.stderr
    for target in ("exercises/20-third.md", "exercises"):
        result = run_cli(course, "validate", target)
        assert result.returncode == 1
        assert "exercises/20-third.md, Broken subsection, Exercise 1, Item A" in result.stderr
        assert "no correct answer" in result.stderr
        assert "Traceback" not in result.stderr
    assert not (course / "_site").exists()


@pytest.mark.parametrize("source", ["missing.md", "empty"])
def test_validate_missing_or_empty_source_fails(tmp_path, source):
    (tmp_path / "empty").mkdir()
    result = run_cli(tmp_path, "validate", source)
    assert result.returncode == 1
    assert source in result.stderr
    assert "Traceback" not in result.stderr


def test_validate_rejects_reserved_public_page_identity(course):
    (course / "exercises/30-first.md").write_text(
        "---\nid: about\ntitle: Reserved\n---\n# Reserved\n\n## Section\n"
    )
    result = run_cli(course, "validate")
    assert result.returncode == 1
    assert "30-first.md" in result.stderr and "public About page" in result.stderr


@pytest.mark.parametrize("output", [None, "nested/output"])
def test_build_regenerates_the_complete_canonical_tree(course, output):
    result = run_cli(course, "build", *(["--output", output] if output else []))
    assert result.returncode == 0, result.stderr
    destination = course / (output or "_site")
    assert f"Output: {output or '_site'}" in result.stdout
    assert "Modules: 4; subsections: 5; exercises: 6" in result.stdout
    assert "Learning pages: 15" in result.stdout
    documents = discover_documents(course / "exercises")
    assert_shape(structure(destination, documents), documents)


@pytest.mark.parametrize("source", ["exercises", "exercises/30-first.md"])
@pytest.mark.parametrize("shim", [False, True])
def test_production_commands_reject_positional_sources(course, source, shim):
    if shim:
        result = subprocess.run(
            [sys.executable, str(ROOT / "build.py"), source],
            cwd=course,
            capture_output=True,
            text=True,
            check=False,
        )
    else:
        result = run_cli(course, "build", source)
    assert result.returncode == 2
    assert "unrecognized arguments" in result.stderr
    assert not (course / "_site").exists()
    assert not (course / "_site.building").exists()


def test_bad_source_leaves_previous_site_untouched(course):
    assert run_cli(course, "build").returncode == 0
    before = file_bytes(course / "_site")
    (course / "exercises/20-third.md").write_text("# Broken\n")
    result = run_cli(course, "build")
    assert result.returncode == 1
    assert "20-third.md" in result.stderr and "no level-two subsections" in result.stderr
    assert file_bytes(course / "_site") == before
    assert not (course / "_site.building").exists()


def test_render_error_is_reported_and_preserves_previous_site(course, monkeypatch, capsys):
    assert run_cli(course, "build").returncode == 0
    before = file_bytes(course / "_site")
    templates = course / "templates"
    shutil.copytree(ROOT / "templates", templates)
    (templates / "exercise.html").unlink()
    monkeypatch.chdir(course)
    monkeypatch.setattr(renderer, "TEMPLATES", templates)
    with pytest.raises(SystemExit) as error:
        main(["build"])
    assert error.value.code == 1
    diagnostic = capsys.readouterr().err
    assert "Build failed:" in diagnostic and "exercise.html" in diagnostic
    assert file_bytes(course / "_site") == before


@pytest.mark.parametrize("directory", ["_site", "_site.building"])
def test_cli_preserves_unrecognised_output_and_staging(course, directory):
    existing = course / directory
    existing.mkdir()
    (existing / "keep.txt").write_text("user data")
    result = run_cli(course, "build")
    assert result.returncode == 1
    assert "unrecognised" in result.stderr
    assert (existing / "keep.txt").read_text() == "user data"


def test_cli_refuses_unrecognised_custom_output(course):
    existing = course / "unrelated"
    existing.mkdir()
    (existing / "keep.txt").write_text("user data")
    result = run_cli(course, "build", "--output", "unrelated")
    assert result.returncode == 1
    assert "unrecognised" in result.stderr
    assert (existing / "keep.txt").read_text() == "user data"
