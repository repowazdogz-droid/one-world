"""Character-facing recall.

This module is the whole of what an inhabitant can reach. It is constructed
with a perception-store connection and nothing else, imports no canonical
storage module, and has no helper that opens canonical storage.

That is an architectural/capability boundary, not OS confinement: a process
running as this user could still open the canonical file if handed its path.
What is enforced and tested here is that nothing on this path is handed one,
so reaching canonical truth would require adding new code, not just a query.
"""

from __future__ import annotations

import json
import sqlite3


class CharacterHistory:
    """Recall for inhabitants. Reads persisted perceptions, in perception order."""

    def __init__(self, minds_conn: sqlite3.Connection) -> None:
        self._conn = minds_conn

    def recall(self, character_id: str) -> list[dict]:
        """One memory order, carrying both epistemic sources.

        `source` says HOW the character came to know a thing -- by witnessing
        something happen, or by looking and finding it already there. It is
        stored, not inferred: this method does no derivation at all, and there
        is nothing here that could turn one source into the other.

        Recall reads persisted bytes and nothing else. It cannot dereference an
        object id, look up where something is now, or consult any canonical
        state, because it holds no handle through which to do so.
        """
        rows = self._conn.execute(
            "SELECT perception_seq, kind, grade, source, perceived_json "
            "FROM perception WHERE character_id = ? ORDER BY perception_seq",
            (character_id,),
        ).fetchall()
        return [
            {
                "seq": int(r["perception_seq"]),
                "kind": r["kind"],
                "grade": r["grade"],
                "source": r["source"],
                "content": json.loads(r["perceived_json"]),
            }
            for r in rows
        ]
