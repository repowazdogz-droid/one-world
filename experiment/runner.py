"""Execution stage, and the scripted worlds. CANONICAL SIDE.

This module is allowed a WorldStore. It builds the world, and it executes
proposals that have ALREADY been chosen. Canonical state may judge whether a
proposed action is physically possible; it may not influence which action was
proposed, and nothing here is visible to `experiment.policy`.
"""

from __future__ import annotations

import os

from one_world import schema
from one_world.actions import (
    propose_look, propose_move, propose_pickup, propose_place,
)
from one_world.perception import PerceptionRouter
from one_world.scenario import ROOM, seed_world
from one_world.world import WorldStore

A = (-2000, 0)          # where the lighter first lies
B = (2000, 0)           # where it ends up
DECISION = (0, 0, 1, 0)  # both inhabitants stand HERE, identically

AVA_START = (0, 3000, 0, -1)
NOAH_START = (0, -3000, 0, 1)
WARREN_START = (-2000, 0, 1, 0)

AVA_OBSERVES_A = (-2100, 0, 1, 0)    # 100 cm from A: CLEAR
NOAH_OBSERVES_B = (2100, 0, -1, 0)   # 100 cm from B: CLEAR
WARREN_AT_B = (2050, 0, -1, 0)       # 50 cm from B: within reach

#: Built at setup, identical for both inhabitants. A history holds a
#: DESCRIPTION; the action API needs an id. Resolving one to the other is part
#: of EXECUTION, and being identical for both it cannot cause any divergence.
DESCRIPTIONS = {"red lighter": "lighter-1"}


def _open(d):
    os.makedirs(d, exist_ok=True)
    wc = schema.open_world(os.path.join(d, "world.db"))
    schema.init_world(wc)
    mc = schema.open_minds(os.path.join(d, "minds.db"))
    schema.init_minds(mc)
    return WorldStore(wc), wc, mc


def _move(world, actor, pose, at):
    r = propose_move(world, actor=actor, to_x_cm=pose[0], to_y_cm=pose[1],
                     facing_x=pose[2], facing_y=pose[3], location=ROOM,
                     occurred_at=at)
    assert r.accepted, f"setup MOVE rejected: {r.reason}"
    return r


def build_asymmetric(d):
    """Ava acquires A and is never told it moved. Noah acquires B.

    No wall anywhere: the asymmetry is produced by RANGE alone.
    """
    world, wc, mc = _open(d)
    seed_world(world)
    world.seed_pose("warren", *WARREN_START)
    world.seed_pose("ava", *AVA_START)
    world.seed_pose("noah", *NOAH_START)
    router = PerceptionRouter(world, mc)

    assert propose_place(world, actor="warren", object_id="lighter-1",
                         x_cm=A[0], y_cm=A[1], location=ROOM,
                         occurred_at="t1").accepted
    _move(world, "ava", AVA_OBSERVES_A, "t2")     # sees the lighter at A
    _move(world, "ava", DECISION, "t3")           # returns; sees nothing
    assert propose_pickup(world, actor="warren", object_id="lighter-1",
                          location=ROOM, occurred_at="t4").accepted
    _move(world, "warren", WARREN_AT_B, "t5")
    assert propose_place(world, actor="warren", object_id="lighter-1",
                         x_cm=B[0], y_cm=B[1], location=ROOM,
                         occurred_at="t6").accepted
    _move(world, "noah", NOAH_OBSERVES_B, "t7")   # sees the lighter at B
    _move(world, "noah", DECISION, "t8")          # returns; sees nothing
    router.derive_pending()
    return world, wc, mc


def build_symmetric(d):
    """CONTROL: both acquire B. Same policy, same structure, same evidence."""
    world, wc, mc = _open(d)
    seed_world(world)
    world.seed_pose("warren", *WARREN_START)
    world.seed_pose("ava", *AVA_START)
    world.seed_pose("noah", *NOAH_START)
    router = PerceptionRouter(world, mc)

    _move(world, "warren", WARREN_AT_B, "t1")
    assert propose_place(world, actor="warren", object_id="lighter-1",
                         x_cm=B[0], y_cm=B[1], location=ROOM,
                         occurred_at="t2").accepted
    _move(world, "ava", (2100, 50, -1, 0), "t3")   # 111 cm from B: CLEAR
    _move(world, "ava", DECISION, "t4")
    _move(world, "noah", NOAH_OBSERVES_B, "t5")    # 100 cm from B: CLEAR
    _move(world, "noah", DECISION, "t6")
    router.derive_pending()
    return world, wc, mc


def execute(world, mc, character_id, proposals, at="x"):
    """Carry out an ALREADY-CHOSEN sequence, and report what the world said.

    Returns one record per proposal. The world's verdict is recorded as a
    physical consequence; it is never fed back into selection.
    """
    outcomes = []
    for index, (verb, params) in enumerate(proposals):
        stamp = f"{at}-{character_id}-{index}"
        if verb == "MOVE":
            to, facing = params["to"], params["facing"]
            r = propose_move(world, actor=character_id, to_x_cm=to[0],
                             to_y_cm=to[1], facing_x=facing[0],
                             facing_y=facing[1], location=ROOM,
                             occurred_at=stamp)
        elif verb == "TAKE":
            object_id = DESCRIPTIONS[params["description"]]
            r = propose_pickup(world, actor=character_id, object_id=object_id,
                               location=ROOM, occurred_at=stamp)
        else:
            raise ValueError(f"unknown verb {verb!r}")
        outcomes.append({"verb": verb, "params": params,
                         "accepted": r.accepted, "reason": r.reason})
    PerceptionRouter(world, mc).derive_pending()
    return outcomes
