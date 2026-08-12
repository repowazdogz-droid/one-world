"""What is actually enforced about canonical access.

These are deliberately separate from the behavioural contract: they do not
change when the history implementation is swapped, so they are not evidence of
discrimination. They pin the capability invariant.

The claim under test is narrow and matches what the code enforces:
character-facing code receives only a perception-store connection, receives no
canonical connection or path, imports no canonical-storage module, and has no
helper that opens canonical storage. It is NOT a claim of OS-level confinement.
"""

from __future__ import annotations

import ast
import inspect
import os
import sqlite3

import pytest

from one_world import minds
from one_world.minds import CharacterHistory

MINDS_SRC_PATH = os.path.abspath(minds.__file__)
MINDS_SRC = open(MINDS_SRC_PATH).read()
MINDS_TREE = ast.parse(MINDS_SRC)


def _imported_modules(tree):
    out = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            out.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            out.add(node.module)
    return out


def test_minds_module_imports_no_canonical_storage():
    imported = _imported_modules(MINDS_TREE)
    forbidden = {"one_world.world", "one_world.schema", "one_world.perception"}
    assert not (imported & forbidden), f"canonical import present: {imported & forbidden}"


def test_minds_module_imports_only_stdlib():
    assert _imported_modules(MINDS_TREE) <= {"__future__", "json", "sqlite3"}


def test_minds_module_names_no_canonical_table_or_file():
    """No code path in character-facing code references canonical storage."""
    for token in ("world_event", "world_presence", "world_observation",
                  "projection_outbox", "world.db", "ATTACH",
                  # v0.8 canonical tables. State observation gave character
                  # memory a second origin, and this is what keeps recall from
                  # dereferencing it back into canonical truth.
                  "arrival_scan", "arrival_sighting", "object_location"):
        assert token not in MINDS_SRC, f"canonical reference {token!r} in minds.py"


def test_minds_module_opens_nothing():
    """It has no helper that opens a database; it is handed a connection."""
    assert "sqlite3.connect" not in MINDS_SRC
    assert "open_world" not in MINDS_SRC


def test_character_history_takes_only_a_minds_connection():
    params = list(inspect.signature(CharacterHistory.__init__).parameters)
    assert params == ["self", "minds_conn"]


def test_character_history_cannot_be_given_a_world_capability(tmp_path):
    """There is no parameter through which a canonical handle could arrive."""
    minds_conn = sqlite3.connect(os.path.join(tmp_path, "m.db"))
    world_conn = sqlite3.connect(os.path.join(tmp_path, "w.db"))
    with pytest.raises(TypeError):
        CharacterHistory(minds_conn, world_conn)


def test_character_history_exposes_no_canonical_attribute():
    public = [a for a in dir(CharacterHistory) if not a.startswith("_")]
    assert public == ["recall"]


def test_recall_phase_never_constructs_a_canonical_path():
    """The recall entry point builds the perception path only."""
    from one_world import scenario

    src = inspect.getsource(scenario.recall_all)
    assert "minds_path" in src
    assert "world_path" not in src
    assert "open_world" not in src
