"""The three-inhabitant acceptance scenario, runnable as separate processes.

  python -m one_world.scenario --dir D --phase populate [--crash-before-derive N]
  python -m one_world.scenario --dir D --phase recover
  python -m one_world.scenario --dir D --phase recall     # opens perception store only

Recall runs in its own process so that "restart" means a real restart.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

from one_world import schema
from one_world.minds import CharacterHistory
from one_world.perception import PerceptionRouter
from one_world.world import WorldStore

BEINGS = [
    ("warren", "Warren", "human"),
    ("ava", "Ava", "ai"),
    ("noah", "Noah", "ai"),
]

ROOM = "the_back_room"
ALL_THREE = ["warren", "ava", "noah"]

# All three are present throughout. Noah is in the room for the private
# conversation and simply does not hear it: presence is canonical fact,
# perception is derived, and their divergence is the point.
SCENARIO = [
    {
        "kind": "GIVE",
        "location": ROOM,
        "actor_id": "warren",
        "payload": {"giver": "warren", "receiver": "ava", "object": "red lighter"},
        "presence": ALL_THREE,
        "observations": {"warren": "CLEAR", "ava": "CLEAR", "noah": "COARSE"},
        "occurred_at": "0001-01-01T00:00:00Z",
    },
    {
        "kind": "SPEECH",
        "location": ROOM,
        "actor_id": "warren",
        "payload": {
            "speaker": "warren",
            "addressee": "ava",
            "utterance": "I'm leaving tomorrow",
        },
        "presence": ALL_THREE,
        "observations": {"warren": "CLEAR", "ava": "CLEAR"},  # Noah does not hear
        "occurred_at": "0001-01-01T00:01:00Z",
    },
    {
        # Perceived by Ava alone. Exists so that Warren -- the human player --
        # can be shown to have a strictly smaller history than the world.
        "kind": "STOW",
        "location": ROOM,
        "actor_id": "ava",
        "payload": {"actor": "ava", "object": "red lighter", "place": "jacket pocket"},
        "presence": ALL_THREE,
        "observations": {"ava": "CLEAR"},
        "occurred_at": "0001-01-01T00:02:00Z",
    },
]

CANONICAL_EVENT_COUNT = len(SCENARIO)


def world_path(d: str) -> str:
    return os.path.join(d, "world.db")


def minds_path(d: str) -> str:
    return os.path.join(d, "minds.db")


def populate(d: str, crash_before_derive: int | None) -> None:
    world_conn = schema.open_world(world_path(d))
    minds_conn = schema.open_minds(minds_path(d))
    schema.init_world(world_conn)
    schema.init_minds(minds_conn)

    world = WorldStore(world_conn)
    for being_id, name, nature in BEINGS:
        world.add_being(being_id, name, nature)

    router = PerceptionRouter(world, minds_conn)
    for index, spec in enumerate(SCENARIO):
        world.commit_event(**spec)
        if crash_before_derive is not None and index == crash_before_derive:
            # Hard kill: no unwinding, no flush, no atexit. The canonical event
            # is committed; its perceptions are not.
            os._exit(9)
        router.derive_pending()


def recover(d: str) -> int:
    world_conn = schema.open_world(world_path(d))
    minds_conn = schema.open_minds(minds_path(d))
    schema.init_world(world_conn)
    schema.init_minds(minds_conn)
    router = PerceptionRouter(WorldStore(world_conn), minds_conn)
    return router.derive_pending()


def recall_all(d: str) -> dict:
    """Opens the perception store only. No canonical path is constructed here."""
    minds_conn = schema.open_minds(minds_path(d))
    history = CharacterHistory(minds_conn)
    return {b[0]: history.recall(b[0]) for b in BEINGS}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", required=True)
    ap.add_argument("--phase", required=True, choices=["populate", "recover", "recall"])
    ap.add_argument("--crash-before-derive", type=int, default=None)
    args = ap.parse_args(argv)

    if args.phase == "populate":
        populate(args.dir, args.crash_before_derive)
    elif args.phase == "recover":
        print(json.dumps({"derived": recover(args.dir)}))
    else:
        json.dump(recall_all(args.dir), sys.stdout, sort_keys=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
