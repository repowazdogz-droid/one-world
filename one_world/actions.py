"""The action layer: proposals in, validated state transitions out.

An action is a PROPOSAL. The world engine inspects canonical state, decides
whether the proposal is possible, and either rejects it with no trace or
atomically changes the world and writes the corresponding history.

This is the authority boundary a language model would eventually sit outside
of. A model may propose GIVE(warren, ava, lighter-1); it cannot make the give
happen by describing it convincingly, and it cannot author the historical
payload -- that is generated from canonical object state.

Rejection leaves NOTHING behind: no state change, no event, no sequence number
consumed, no snapshot, no observation, no outbox row, and therefore no
perception. A rejected proposal did not happen.
"""

from __future__ import annotations

from dataclasses import dataclass

from one_world.world import WorldStore

# Rejection reasons. Stable identifiers, not prose, so callers can branch.
UNKNOWN_ACTOR = "UNKNOWN_ACTOR"
UNKNOWN_RECEIVER = "UNKNOWN_RECEIVER"
UNKNOWN_OBJECT = "UNKNOWN_OBJECT"
NOT_POSSESSED = "NOT_POSSESSED"
SELF_GIVE = "SELF_GIVE"
ALREADY_STOWED = "ALREADY_STOWED"


@dataclass(frozen=True)
class ActionResult:
    """Accepted with the event it produced, or rejected with a reason."""

    accepted: bool
    event_id: str | None = None
    reason: str | None = None

    def __bool__(self) -> bool:
        return self.accepted


def _rejected(reason: str) -> ActionResult:
    return ActionResult(accepted=False, reason=reason)


def _midpoint(a: tuple[int, int, int, int], b: tuple[int, int, int, int]):
    """Integer midpoint of two poses. Exact and deterministic (floor division)."""
    return ((a[0] + b[0]) // 2, (a[1] + b[1]) // 2)


def propose_give(
    world: WorldStore,
    *,
    actor: str,
    receiver: str,
    object_id: str,
    presence: list[str],
    location: str,
    occurred_at: str,
) -> ActionResult:
    """Hand an object from actor to receiver.

    Preconditions: both beings exist, the object exists, the actor currently
    holds it, and the actor is not the receiver (handing something to yourself
    is not a transfer, and allowing it would let history record a change that
    did not occur).

    On success the object moves to the receiver and is taken out of whatever it
    was stowed in, and one GIVE event is appended. The event position is DERIVED
    as the midpoint of the two poses rather than supplied.
    """
    with world.transaction():
        if not world.being_exists(actor):
            return _rejected(UNKNOWN_ACTOR)
        if not world.being_exists(receiver):
            return _rejected(UNKNOWN_RECEIVER)
        if actor == receiver:
            return _rejected(SELF_GIVE)
        obj = world.object_row(object_id)
        if obj is None:
            return _rejected(UNKNOWN_OBJECT)
        loc = world.object_location(object_id)
        if loc is None or loc["holder_id"] != actor:
            return _rejected(NOT_POSSESSED)

        # -- accepted: state first, then the history that explains it --
        world._set_object_location(object_id, receiver, None)

        ex, ey = _midpoint(world.current_pose(actor), world.current_pose(receiver))
        event_id = world._append_event_locked(
            kind="GIVE",
            location=location,
            actor_id=actor,
            # Generated from canonical state. The caller never supplies the
            # object's description, so a proposal cannot disagree with truth.
            payload={"giver": actor, "receiver": receiver,
                     "object": obj["description"]},
            presence=presence,
            event_x_cm=ex,
            event_y_cm=ey,
            occurred_at=occurred_at,
        )
    return ActionResult(accepted=True, event_id=event_id)


def propose_stow(
    world: WorldStore,
    *,
    actor: str,
    object_id: str,
    place: str,
    presence: list[str],
    location: str,
    occurred_at: str,
) -> ActionResult:
    """Put an object you are holding away, into a named place on your person.

    v0.4 narrowing, deliberate: stowing does NOT change who holds the object and
    does not introduce containers as first-class world objects. `place` is a
    label on the holder. A general containment ontology is out of scope, and
    nothing in the milestone needs one.

    Preconditions: the actor exists, the object exists, the actor holds it, and
    it is not already stowed. The event happens at the actor's own position.
    """
    with world.transaction():
        if not world.being_exists(actor):
            return _rejected(UNKNOWN_ACTOR)
        obj = world.object_row(object_id)
        if obj is None:
            return _rejected(UNKNOWN_OBJECT)
        loc = world.object_location(object_id)
        if loc is None or loc["holder_id"] != actor:
            return _rejected(NOT_POSSESSED)
        if loc["stowed_in"] is not None:
            return _rejected(ALREADY_STOWED)

        world._set_object_location(object_id, actor, place)

        ax, ay, _, _ = world.current_pose(actor)
        event_id = world._append_event_locked(
            kind="STOW",
            location=location,
            actor_id=actor,
            payload={"actor": actor, "object": obj["description"], "place": place},
            presence=presence,
            event_x_cm=ax,
            event_y_cm=ay,
            occurred_at=occurred_at,
        )
    return ActionResult(accepted=True, event_id=event_id)
