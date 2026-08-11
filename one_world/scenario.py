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
from one_world.actions import propose_give, propose_stow
from one_world.minds import CharacterHistory
from one_world.perception import PerceptionRouter
from one_world.world import WorldStore

BEINGS = [
    ("warren", "Warren", "human"),
    ("ava", "Ava", "ai"),
    ("noah", "Noah", "ai"),
]

ROOM = "the_back_room"

#: The one canonical object. `description` is the world's own detail; it is not
#: what any character necessarily perceives.
LIGHTER = ("lighter-1", "lighter", "red lighter")
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
        # Proposal, not an assertion. The engine checks Warren really holds
        # lighter-1, moves it, and generates the payload from canonical state.
        # The event position is derived as the midpoint of the two poses: (50,0).
        "action": {
            "verb": "GIVE",
            "actor": "warren",
            "receiver": "ava",
            "object_id": "lighter-1",
            "presence": ALL_THREE,
            "location": ROOM,
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
        # Ava can only stow it because the GIVE actually transferred it.
        # The event happens at her own position: (100,0).
        "action": {
            "verb": "STOW",
            "actor": "ava",
            "object_id": "lighter-1",
            "place": "jacket pocket",
            "presence": ALL_THREE,
            "location": ROOM,
            "occurred_at": "0001-01-01T00:02:00Z",
        },
    },
]

CANONICAL_EVENT_COUNT = len(SCENARIO)


# ---------------------------------------------------------------------------
# v0.3 scene: two observers with IDENTICAL relevant visual geometry, separated
# only by canonical world structure.
#
#            y
#        50  |          |w1
#         0  A(-200,0)->  [X(0,0)]  |  <-N(200,0)
#       -50  |          |w1
#            -200        0    100   200      x
#
# Ava and Noah are BOTH 200 cm from the event, BOTH facing straight at it, and
# BOTH inside DETAIL_RANGE_CM (300). Under v0.2 each would be CLEAR. The only
# difference is that wall w1 stands across Noah's line of sight.
# ---------------------------------------------------------------------------

WALL_ID = "w1"
BLOCKING_WALL = (100, -50, 100, 50)

WALL_SCENE_POSES = {
    "warren": (0, 0, 1, 0),      # actor, at the event
    "ava": (-200, 0, 1, 0),      # 200 cm west, looking east
    "noah": (200, 0, -1, 0),     # 200 cm east, looking west
}

#: Noah relocated so the same wall no longer crosses his sight line.
#: (200,200) -> (0,0) passes x=100 at y=100, clear of the wall's y range.
NOAH_CLEAR_OF_WALL = (200, 200, -1, -1)

#: Descriptive record of the v0.3 wall event. `event_x_cm/event_y_cm` are the
#: DERIVED position (Warren's own pose) and are kept here so the v0.3 sensing
#: control tests can reason about the same geometry.
WALL_EVENT = {
    "kind": "STOW",
    "actor_id": "warren",
    "event_x_cm": 0,
    "event_y_cm": 0,
    "occurred_at": "0002-01-01T00:00:00Z",
}


def wall_action(occurred_at: str) -> dict:
    return {
        "verb": "STOW", "actor": "warren", "object_id": "lighter-1",
        "place": "the table", "presence": ALL_THREE, "location": ROOM,
        "occurred_at": occurred_at,
    }


def setup_wall_scene(world: WorldStore, *, with_wall: bool, noah_pose=None) -> None:
    """Place everyone, and build or omit the blocking wall."""
    poses = dict(WALL_SCENE_POSES)
    if noah_pose is not None:
        poses["noah"] = noah_pose
    for being_id, pose in sorted(poses.items()):
        world.set_pose(being_id, *pose)
    if with_wall:
        world.add_wall(WALL_ID, *BLOCKING_WALL)
    else:
        world.remove_wall(WALL_ID)


def wall_event(world: WorldStore, occurred_at: str) -> str:
    """The v0.3 scene's event, now a validated action."""
    return run_action(world, wall_action(occurred_at))


def world_path(d: str) -> str:
    return os.path.join(d, "world.db")


def minds_path(d: str) -> str:
    return os.path.join(d, "minds.db")


def apply_step(world: WorldStore, step: dict) -> str:
    """Put everyone where the step says they are, then run the step.

    Poses are physical facts and are legitimate authored input. Grades are
    derived, and for state-changing verbs the payload and event position are
    derived too -- the step only proposes.
    """
    for being_id, pose in sorted(step["poses"].items()):
        world.set_pose(being_id, *pose)
    if "action" in step:
        return run_action(world, step["action"])
    return world.commit_event(**step["event"])


def run_action(world: WorldStore, spec: dict) -> str:
    """Dispatch a proposal and insist it was accepted."""
    spec = dict(spec)
    verb = spec.pop("verb")
    fn = {"GIVE": propose_give, "STOW": propose_stow}[verb]
    result = fn(world, **spec)
    if not result.accepted:
        raise AssertionError(f"scenario action {verb} rejected: {result.reason}")
    return result.event_id


def seed_world(world: WorldStore, holder: str = "warren") -> None:
    """Beings and the one object, with an explicit initial holder."""
    for being_id, name, nature in BEINGS:
        world.add_being(being_id, name, nature)
    world.add_object(*LIGHTER, holder_id=holder)


def _open_both(d: str):
    world_conn = schema.open_world(world_path(d))
    minds_conn = schema.open_minds(minds_path(d))
    schema.init_world(world_conn)
    schema.init_minds(minds_conn)
    return world_conn, minds_conn


def populate(d: str, crash_before_derive: int | None) -> None:
    world_conn, minds_conn = _open_both(d)
    world = WorldStore(world_conn)
    seed_world(world)

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


def wall_populate(d: str, with_wall: bool, crash_before_derive: int | None) -> None:
    """The v0.3 acceptance scene: one event, wall present or absent."""
    world_conn, minds_conn = _open_both(d)
    world = WorldStore(world_conn)
    seed_world(world)
    setup_wall_scene(world, with_wall=with_wall)
    wall_event(world, WALL_EVENT["occurred_at"])
    if crash_before_derive is not None:
        os._exit(9)
    PerceptionRouter(world, minds_conn).derive_pending()


def set_wall(d: str, present: bool) -> None:
    """Change present-day geometry. Must not affect past perceptions."""
    world_conn = schema.open_world(world_path(d))
    schema.init_world(world_conn)
    world = WorldStore(world_conn)
    if present:
        world.add_wall(WALL_ID, *BLOCKING_WALL)
    else:
        world.remove_wall(WALL_ID)


def new_wall_event(d: str, occurred_at: str) -> None:
    """Commit a further equivalent event under TODAY's geometry."""
    world_conn, minds_conn = _open_both(d)
    world = WorldStore(world_conn)
    # A second stow needs the object un-stowed first; the engine would reject
    # otherwise. Retrieving is not an event in v0.4.
    world._set_object_location("lighter-1", "warren", None)
    wall_event(world, occurred_at)
    PerceptionRouter(world, minds_conn).derive_pending()


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
        "--phase", required=True,
        choices=["populate", "recover", "recall", "move",
                 "wall-populate", "wall-add", "wall-remove", "wall-event"],
    )
    ap.add_argument("--wall", choices=["yes", "no"], default="yes")
    ap.add_argument("--at", default="0002-01-01T00:00:00Z")
    ap.add_argument("--crash-before-derive", type=int, default=None)
    for flag in ("--being", "--x", "--y", "--fx", "--fy"):
        ap.add_argument(flag)
    args = ap.parse_args(argv)

    if args.phase == "populate":
        populate(args.dir, args.crash_before_derive)
    elif args.phase == "wall-populate":
        wall_populate(args.dir, args.wall == "yes", args.crash_before_derive)
    elif args.phase in ("wall-add", "wall-remove"):
        set_wall(args.dir, args.phase == "wall-add")
    elif args.phase == "wall-event":
        new_wall_event(args.dir, args.at)
    elif args.phase == "move":
        move(args.dir, args.being, int(args.x), int(args.y), int(args.fx), int(args.fy))
    elif args.phase == "recover":
        print(json.dumps({"derived": recover(args.dir)}))
    else:
        json.dump(recall_all(args.dir), sys.stdout, sort_keys=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
