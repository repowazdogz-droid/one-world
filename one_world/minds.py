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
        rows = self._conn.execute(
            "SELECT perception_seq, kind, grade, perceived_json FROM perception "
            "WHERE character_id = ? ORDER BY perception_seq",
            (character_id,),
        ).fetchall()
        return [
            {
                "seq": int(r["perception_seq"]),
                "kind": r["kind"],
                "grade": r["grade"],
                "content": json.loads(r["perceived_json"]),
            }
            for r in rows
        ]
