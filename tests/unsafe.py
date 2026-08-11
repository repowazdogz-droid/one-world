"""The deliberately wrong implementation, for negative control.

`UnsafeCharacterHistory` has the same interface as `CharacterHistory` but is
constructed with the CANONICAL store and serves recall from world events
filtered by presence.

It is not a strawman. It filters, so it looks epistemically careful -- a
character only "remembers" events they were actually at. The bug is the one a
competent engineer under time pressure actually makes: conflating *was present*
with *perceived everything*, and drawing memory from canonical truth.
"""

from __future__ import annotations

from one_world.world import WorldStore


class UnsafeCharacterHistory:
    def __init__(self, world: WorldStore) -> None:
        self._world = world

    def recall(self, character_id: str) -> list[dict]:
        out = []
        for event in self._world.all_events():  # canonical order
            if character_id in event["presence"]:
                out.append(
                    {
                        "seq": event["world_seq"],
                        "kind": event["kind"],
                        "grade": "CLEAR",
                        "content": event["payload"],  # the full canonical payload
                    }
                )
        return out
