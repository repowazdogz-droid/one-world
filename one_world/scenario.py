"""The three-inhabitant acceptance scenario, runnable as separate processes.

  python -m one_world.scenario --dir D --phase populate [--crash-before-derive N]
  python -m one_world.scenario --dir D --phase recover
  python -m one_world.scenario --dir D --phase recall     # opens perception store only
  python -m one_world.scenario --dir D --phase move --being B --x X --y Y --fx FX --fy FY

Recall runs in its own process so that "restart" means a real restart.

v0.2: no step supplies a perception grade. Each step supplies PHYSICAL FACTS --
where each inhabitant stands and which way they face -- and the sensing model
derives who perceived what. The geometry below is chosen so that the v0.1
behavioural contract (Ava 3 memories, Warren 2, Noah 1 coarse) is CAUSED rather
than asserted.
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

# Scene, in integer centimetres. Facing is an integer direction vector.
#
#   y
#   8m  .            N(50,800) facing (0,-1)  -- watching, but 8 m away
#       .
#   0m  W(0,0)---[X(50,0)]---A(100,0)
#       0m       exchange     1m
#
# VIEW_RANGE_CM=1500, DETAIL_RANGE_CM=300, DIRECTED audio radius=150.
# Noah is inside view range and inside his 45-degree cone, but 800 cm from the
# exchange -- well beyond the 300 cm detail threshold. That distance alone is
# what reduces his perception. No grade literal is written anywhere in this file.

SCENARIO = [
    {
        # Warren hands Ava the lighter. Ava is 50 cm away, Noah 800 cm.
        "poses": {
            "warren": (0, 0, 1, 0),
            "ava": (100, 0, -1, 0),
            "noah": (50, 800, 0, -1),
        },
        "event": {
            "kind": "GIVE",
            "location": ROOM,
            "actor_id": "warren",
            "payload": {"giver": "warren", "receiver": "ava", "object": "red lighter"},
            "presence": ALL_THREE,
            "event_x_cm": 50,
            "event_y_cm": 0,
            "occurred_at": "0001-01-01T00:00:00Z",
        },
    },
    {
        # Warren speaks quietly to Ava. DIRECTED carries 150 cm; Ava is 100 cm
        # from him, Noah is ~802 cm. Noah is in the room and does not hear it.
        "poses": {
            "warren": (0, 0, 1, 0),
            "ava": (100, 0, -1, 0),
            "noah": (50, 800, 0, -1),
        },
        "event": {
            "kind": "SPEECH",
            "location": ROOM,
            "actor_id": "warren",
            "payload": {
                "speaker": "warren",
                "addressee": "ava",
                "utterance": "I'm leaving tomorrow",
            },
            "presence": ALL_THREE,
            "event_x_cm": 0,
            "event_y_cm": 0,
            "audio_mode": "DIRECTED",
            "occurred_at": "0001-01-01T00:01:00Z",
        },
    },
    {
        # Ava pockets the lighter. Warren has turned away (facing -x, so Ava at
        # +100 is behind him) and Noah has turned away (facing +y, away from the
        # exchange). Only Ava perceives it -- by agency, being the actor.
        "poses": {
            "warren": (0, 0, -1, 0),
            "ava": (100, 0, -1, 0),
            "noah": (50, 800, 0, 1),
        },
        "event": {
            "kind": "STOW",
            "location": ROOM,
            "actor_id": "ava",
            "payload": {"actor": "ava", "object": "red lighter", "place": "jacket pocket"},
            "presence": ALL_THREE,
            "event_x_cm": 100,
            "event_y_cm": 0,
            "occurred_at": "0001-01-01T00:02:00Z",
        },
    },
]

CANONICAL_EVENT_COUNT = len(SCENARIO)


def world_path(d: str) -> str:
    return os.path.join(d, "world.db")


def minds_path(d: str) -> str:
    return os.path.join(d, "minds.db")


def apply_step(world: WorldStore, step: dict) -> str:
    """Put everyone where the step says they are, then commit the event.

    Poses are physical facts and are legitimate authored input. Grades are not
    authored anywhere -- commit_event derives them.
    """
    for being_id, pose in sorted(step["poses"].items()):
        world.set_pose(being_id, *pose)
    return world.commit_event(**step["event"])


def _open_both(d: str):
    world_conn = schema.open_world(world_path(d))
    minds_conn = schema.open_minds(minds_path(d))
    schema.init_world(world_conn)
    schema.init_minds(minds_conn)
    return world_conn, minds_conn


def populate(d: str, crash_before_derive: int | None) -> None:
    world_conn, minds_conn = _open_both(d)
    world = WorldStore(world_conn)
    for being_id, name, nature in BEINGS:
        world.add_being(being_id, name, nature)

    router = PerceptionRouter(world, minds_conn)
    for index, step in enumerate(SCENARIO):
        apply_step(world, step)
        if crash_before_derive is not None and index == crash_before_derive:
            # Hard kill: no unwinding, no flush, no atexit. The canonical event
            # and its pose snapshot are committed; its perceptions are not.
            os._exit(9)
        router.derive_pending()


def move(d: str, being_id: str, x: int, y: int, fx: int, fy: int) -> None:
    """Change present-day physical state. Must not affect past perceptions."""
    world_conn = schema.open_world(world_path(d))
    schema.init_world(world_conn)
    WorldStore(world_conn).set_pose(being_id, x, y, fx, fy)


def recover(d: str) -> int:
    world_conn, minds_conn = _open_both(d)
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
    ap.add_argument(
        "--phase", required=True, choices=["populate", "recover", "recall", "move"]
    )
    ap.add_argument("--crash-before-derive", type=int, default=None)
    for flag in ("--being", "--x", "--y", "--fx", "--fy"):
        ap.add_argument(flag)
    args = ap.parse_args(argv)

    if args.phase == "populate":
        populate(args.dir, args.crash_before_derive)
    elif args.phase == "move":
        move(args.dir, args.being, int(args.x), int(args.y), int(args.fx), int(args.fy))
    elif args.phase == "recover":
        print(json.dumps({"derived": recover(args.dir)}))
    else:
        json.dump(recall_all(args.dir), sys.stdout, sort_keys=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
