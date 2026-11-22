"""Keep JSDoc object typedefs in static/*.js aligned with Python contracts."""

import json
import re
from typing import is_typeddict

from conftest import ROOT

from agrarian_builder import contracts

TYPEDEF_OBJECT_RE = re.compile(r"@typedef\s+\{Object\}\s+(\w+)")
TYPEDEF_OTHER_RE = re.compile(r"@typedef\b")
PROPERTY_RE = re.compile(r"@property\s+\{[^}]*\}\s+(\w+)")

# Browser-local saved state is owned exclusively by client scripts and is never
# emitted by the Python renderer.
BROWSER_ONLY_TYPEDEFS = {"SavedModuleState"}


def parse_jsdoc_object_typedefs() -> dict[str, set[str]]:
    """Collect @typedef {Object} property sets across all browser scripts."""
    typedefs: dict[str, set[str]] = {}
    for path in sorted((ROOT / "static").glob("*.js")):
        current: str | None = None
        for line in path.read_text(encoding="utf-8").splitlines():
            object_match = TYPEDEF_OBJECT_RE.search(line)
            if object_match:
                name = object_match.group(1)
                assert name not in typedefs, f"Duplicate JSDoc typedef {name} in {path}"
                typedefs[name] = set()
                current = name
                continue
            if TYPEDEF_OTHER_RE.search(line):
                current = None
                continue
            if current is not None and "*/" in line:
                current = None
                continue
            property_match = PROPERTY_RE.search(line)
            if current is not None and property_match:
                prop = property_match.group(1)
                assert prop not in typedefs[current], (
                    f"Duplicate @property {prop} on {current} in {path}"
                )
                typedefs[current].add(prop)
    return typedefs


def python_contract_keys() -> dict[str, set[str]]:
    """Collect field sets for every TypedDict in agrarian_builder.contracts."""
    return {
        name: set(cls.__required_keys__ | cls.__optional_keys__)
        for name, cls in vars(contracts).items()
        if is_typeddict(cls)
    }


def test_jsdoc_typedefs_match_python_typed_contracts():
    js_typedefs = parse_jsdoc_object_typedefs()
    py_contracts = python_contract_keys()
    assert BROWSER_ONLY_TYPEDEFS <= set(js_typedefs)
    assert set(js_typedefs) - BROWSER_ONLY_TYPEDEFS == set(py_contracts)
    for name, expected_keys in py_contracts.items():
        assert js_typedefs[name] == expected_keys, name
    records_match = re.search(
        r"const\s+RECORDS\s*=\s*(\[[^\]]+\]);",
        (ROOT / "static/progress.js").read_text(encoding="utf-8"),
    )
    assert records_match is not None
    assert js_typedefs["SavedModuleState"] == set(json.loads(records_match.group(1)))
