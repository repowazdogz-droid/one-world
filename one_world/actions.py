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

from one_world import geometry
from one_world.world import WorldStore

# Rejection reasons. Stable identifiers, not prose, so callers can branch.
UNKNOWN_ACTOR = "UNKNOWN_ACTOR"
UNKNOWN_RECEIVER = "UNKNOWN_RECEIVER"
UNKNOWN_OBJECT = "UNKNOWN_OBJECT"
NOT_POSSESSED = "NOT_POSSESSED"
SELF_GIVE = "SELF_GIVE"
ALREADY_STOWED = "ALREADY_STOWED"
UNKNOWN_ATTEMPT = "UNKNOWN_ATTEMPT"
UNKNOWN_RESPONSE = "UNKNOWN_RESPONSE"
WRONG_RESPONDER = "WRONG_RESPONDER"
ALREADY_RESOLVED = "ALREADY_RESOLVED"
ZERO_FACING = "ZERO_FACING"
NO_CHANGE = "NO_CHANGE"
NOT_PLACED = "NOT_PLACED"
NOT_ON_THE_GROUND = "NOT_ON_THE_GROUND"
OUT_OF_REACH = "OUT_OF_REACH"

ACCEPT = "ACCEPT"
REFUSE = "REFUSE"
#: The whole vocabulary an inhabitant has for answering an offer. Anything else
#: fails closed -- the world does not guess what an unrecognised answer means.
RESPONSES = frozenset({ACCEPT, REFUSE})

#: How close you must be to put something down or pick something up.
#: Deliberately crude: one radius, no arm length, no reaching direction, no
#: hand pose, no height. Exact integer centimetres, compared as squared
#: distance, consistent with every other threshold in the world.
#: BOUNDARY: INCLUSIVE -- exactly at the radius is within reach.
INTERACTION_RANGE_CM = 80


@dataclass(frozen=True)
class ActionResult:
    """Accepted with the event it produced, or rejected with a reason."""

    accepted: bool
    event_id: str | None = None
    reason: str | None = None
    attempt_id: str | None = None
    outcome: str | None = None

    def __bool__(self) -> bool:
        return self.accepted


def _rejected(reason: str) -> ActionResult:
    return ActionResult(accepted=False, reason=reason)


def _midpoint(a: tuple[int, int, int, int], b: tuple[int, int, int, int]):
    """Integer midpoint of two poses. Exact and deterministic (floor division)."""
    return ((a[0] + b[0]) // 2, (a[1] + b[1]) // 2)


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

        world._set_stow(object_id, place)

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


# ---------------------------------------------------------------------------
# v0.5: offers, and the right to say no.
#
# v0.4 went straight from "this proposal is causally possible" to "the object
# has moved". The recipient was never consulted. These two calls put a decision
# in that gap without pretending the world knows WHY anyone decided anything.
#
# The response is supplied by the caller, and that is NOT the authored-grade
# mistake: a perception grade is a physical fact the world should derive, but a
# decision is an inhabitant's own act. The canonical fact recorded is only
# "Ava refused this attempt" -- never a reason.
# ---------------------------------------------------------------------------


def attempt_give(
    world: WorldStore,
    *,
    actor: str,
    receiver: str,
    object_id: str,
    presence: list[str],
    location: str,
    occurred_at: str,
) -> ActionResult:
    """Offer an object to someone, and wait for their answer.

    Preconditions are exactly v0.4's GIVE preconditions: an offer that could
    not physically be made is not made. A causally impossible proposal produces
    NO event and NO attempt -- it never reached anyone to be refused. Refusal
    exists only downstream of a valid attempt.

    On success: a PENDING give_attempt row and one GIVE_ATTEMPT event. The
    object does NOT move yet.
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

        ex, ey = _midpoint(world.current_pose(actor), world.current_pose(receiver))
        event_id = world._append_event_locked(
            kind="GIVE_ATTEMPT",
            location=location,
            actor_id=actor,
            payload={"giver": actor, "receiver": receiver,
                     "object": obj["description"]},
            presence=presence,
            event_x_cm=ex,
            event_y_cm=ey,
            occurred_at=occurred_at,
        )
        seq = int(event_id.split("-")[1])
        attempt_id = f"att-{seq:06d}"          # deterministic; no UUID
        world._create_attempt(attempt_id, seq, actor, receiver, object_id)
    return ActionResult(accepted=True, event_id=event_id,
                        attempt_id=attempt_id, outcome="PENDING")


def respond_to_attempt(
    world: WorldStore,
    *,
    attempt_id: str,
    responder: str,
    response: str,
    presence: list[str],
    location: str,
    occurred_at: str,
    utterance: str = "No.",
) -> ActionResult:
    """Answer an offer. Only the person it was made to may answer, once.

    ACCEPT transfers the object and appends a GIVE event.
    REFUSE transfers nothing and appends a REFUSAL event.

    Either way the attempt's OUTCOME IS PERSISTED. Nothing later re-derives
    whether an offer succeeded by looking at who holds the object today.

    An invalid response produces no event, no state change and no sequence
    number: the world does not record every mistaken button-press as social
    history.
    """
    with world.transaction():
        if response not in RESPONSES:
            return _rejected(UNKNOWN_RESPONSE)
        att = world.attempt(attempt_id)
        if att is None:
            return _rejected(UNKNOWN_ATTEMPT)
        if att["outcome"] != "PENDING":
            return _rejected(ALREADY_RESOLVED)
        if responder != att["receiver_id"]:
            return _rejected(WRONG_RESPONDER)

        actor, receiver = att["actor_id"], att["receiver_id"]
        object_id = att["object_id"]
        obj = world.object_row(object_id)
        loc = world.object_location(object_id)
        # The offerer may have lost the object between offering and being
        # answered. Accepting something they no longer hold is not possible.
        if loc is None or loc["holder_id"] != actor:
            return _rejected(NOT_POSSESSED)

        if response == ACCEPT:
            world._transfer_holder(object_id, receiver, attempt_id)
            ex, ey = _midpoint(world.current_pose(actor),
                               world.current_pose(receiver))
            event_id = world._append_event_locked(
                kind="GIVE",
                location=location,
                actor_id=actor,
                payload={"giver": actor, "receiver": receiver,
                         "object": obj["description"]},
                presence=presence,
                event_x_cm=ex,
                event_y_cm=ey,
                occurred_at=occurred_at,
            )
            outcome = "ACCEPTED"
        else:
            # No transfer. The refusal is spoken, so it is heard rather than
            # seen, and it carries no description of the refused object -- a
            # bystander who could not make out the offer learns nothing new.
            rx, ry, _, _ = world.current_pose(responder)
            event_id = world._append_event_locked(
                kind="REFUSAL",
                location=location,
                actor_id=responder,
                payload={"refuser": responder, "utterance": utterance},
                presence=presence,
                event_x_cm=rx,
                event_y_cm=ry,
                occurred_at=occurred_at,
                audio_mode="DIRECTED",
            )
            outcome = "REFUSED"

        world._resolve_attempt(attempt_id, outcome, int(event_id.split("-")[1]))
    return ActionResult(accepted=True, event_id=event_id,
                        attempt_id=attempt_id, outcome=outcome)


# ---------------------------------------------------------------------------
# v0.6: movement is a state transition with a cause.
#
# Position decides what an inhabitant can see, hear and be occluded from, so a
# silent pose change is a silent change to everyone's future perception. After
# initialization the only way a live inhabitant's pose changes is through here.
# ---------------------------------------------------------------------------


def propose_move(
    world: WorldStore,
    *,
    actor: str,
    to_x_cm: int,
    to_y_cm: int,
    facing_x: int,
    facing_y: int,
    presence: list[str],
    location: str,
    occurred_at: str,
) -> ActionResult:
    """Move and/or turn. A discrete transition, not locomotion.

    Preconditions: the actor exists and has already been placed, the facing
    vector is non-zero, and the destination differs from the current pose in
    position or orientation. A pure rotation IS a move: orientation already
    changes what someone will perceive next, so turning is a real state change.

    TEMPORAL SEMANTICS, chosen rather than left to statement order:

        The MOVE event happens AT THE DEPARTURE. Its position is the FROM
        position, and the event-time snapshot records the world immediately
        BEFORE the transition -- so observers perceive the mover where they set
        off from, not already arrived. The pose is updated only after the event
        and its snapshots are written.

    This is the reverse of GIVE, deliberately. An object's location is not a
    sensing input, so a transfer may move state first. An actor's POSE IS the
    sensing input, so changing it before the snapshot would make the mover
    appear to have already teleported to everyone perceiving the movement.

    The payload records from, to and facing at commit time. Nothing later
    re-derives where a past move went by consulting today's pose.

    v0.8 -- ARRIVAL. Once the transition has been applied, the mover senses what
    is PRESENT from where they now stand, and that scan is snapshotted in this
    same transaction. The two halves of a move are therefore perceived from
    OPPOSITE ends of it, and deliberately so:

        MOVE event      perceived by everyone, from the DEPARTURE snapshot
        arrival scan    perceived by the mover alone, from the ARRIVAL pose

    A successful MOVE is the only trigger. Standing still rescans nothing, there
    is no clock, and there is no background sensing.
    """
    with world.transaction():
        if not world.being_exists(actor):
            return _rejected(UNKNOWN_ACTOR)
        if facing_x == 0 and facing_y == 0:
            return _rejected(ZERO_FACING)
        try:
            fx, fy, ffx, ffy = world.current_pose(actor)
        except KeyError:
            return _rejected(NOT_PLACED)
        if (fx, fy, ffx, ffy) == (to_x_cm, to_y_cm, facing_x, facing_y):
            return _rejected(NO_CHANGE)

        # Event first, while being_pose still holds the origin.
        event_id = world._append_event_locked(
            kind="MOVE",
            location=location,
            actor_id=actor,
            payload={"actor": actor, "from": [fx, fy], "to": [to_x_cm, to_y_cm],
                     "facing": [facing_x, facing_y]},
            presence=presence,
            event_x_cm=fx,
            event_y_cm=fy,
            occurred_at=occurred_at,
        )
        # ...then the transition the event explains.
        world._move_pose(actor, to_x_cm, to_y_cm, facing_x, facing_y)
        # ...and only now, from where the actor actually is, what is there.
        world._record_arrival_scan(
            event_id=event_id,
            world_seq=int(event_id.split("-")[1]),
            being_id=actor,
            trigger="MOVE",
        )
    return ActionResult(accepted=True, event_id=event_id)


# ---------------------------------------------------------------------------
# v0.9: looking is a thing you choose to do.
#
# v0.8 could only sense present state on arrival, so a stationary inhabitant was
# permanently ignorant of anything that appeared in front of them. Movement and
# observation were the same act. This separates them.
# ---------------------------------------------------------------------------


def propose_look(
    world: WorldStore,
    *,
    actor: str,
    presence: list[str],
    location: str,
    occurred_at: str,
) -> ActionResult:
    """Observe the world from where you already stand.

    Preconditions are only that the actor exists and is placed. There is no
    NO_CHANGE rule: looking twice at an unchanged world is two real experiences,
    not a repeated one, and the world does not decide that a second look was
    pointless.

    LOOK CHANGES NO PHYSICAL STATE. It does not move the actor, does not turn
    them, does not touch any object, and does not build or remove anything. That
    is not merely a convention of this function -- it holds no pose primitive
    and no object primitive, so there is nothing here that could. Facing is
    taken as it already is; an inhabitant who wants to inspect another direction
    rotates with a MOVE first, because rotation is already movement and v0.9
    does not fuse the two.

    What it DOES produce:

        a canonical LOOK event ....... "Ava looked." World truth.
        an observation scan .......... snapshotted from her CURRENT pose.
        STATE observations ........... "Ava saw a red lighter." HER truth.

    The second and third are not the same thing, and the third never enters
    canonical history. Nothing anywhere records that the world contains the fact
    "Ava saw a red lighter"; it records that she looked, and her own memory
    holds what that got her.

    The LOOK event is AGENCY-sensed: the actor knows they looked, and no
    bystander perceives it, because this world models no physical manifestation
    of looking beyond facing -- and facing changes are MOVE.
    """
    with world.transaction():
        if not world.being_exists(actor):
            return _rejected(UNKNOWN_ACTOR)
        try:
            ax, ay, _, _ = world.current_pose(actor)
        except KeyError:
            return _rejected(NOT_PLACED)

        event_id = world._append_event_locked(
            kind="LOOK",
            location=location,
            actor_id=actor,
            payload={"actor": actor},
            presence=presence,
            event_x_cm=ax,
            event_y_cm=ay,
            occurred_at=occurred_at,
        )
        # From where she already is. No transition preceded this, and none
        # follows it.
        world._record_arrival_scan(
            event_id=event_id,
            world_seq=int(event_id.split("-")[1]),
            being_id=actor,
            trigger="LOOK",
        )
    return ActionResult(accepted=True, event_id=event_id)


# ---------------------------------------------------------------------------
# v0.7: objects exist in space.
#
# Until now an object was always in someone's hand. These two actions let a
# lighter lie on the ground as canonical world state, and make possession
# something you have to be physically close enough to acquire.
# ---------------------------------------------------------------------------


def propose_place(
    world: WorldStore,
    *,
    actor: str,
    object_id: str,
    x_cm: int,
    y_cm: int,
    presence: list[str],
    location: str,
    occurred_at: str,
) -> ActionResult:
    """Put down something you are holding, at a point you can reach.

    Preconditions: the actor exists and is placed in the world, the object
    exists, the actor currently holds it, and the destination point is within
    INTERACTION_RANGE_CM of the actor. Nobody may set an object down across
    the room.

    On success the object stops being held and becomes a point in the world;
    any stow label is cleared, because something lying on the ground is not in
    anyone's pocket.
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
        try:
            ax, ay, _, _ = world.current_pose(actor)
        except KeyError:
            return _rejected(NOT_PLACED)
        if not geometry.within_radius(ax, ay, x_cm, y_cm, INTERACTION_RANGE_CM):
            return _rejected(OUT_OF_REACH)

        world._place_object(object_id, x_cm, y_cm)
        event_id = world._append_event_locked(
            kind="PLACE",
            location=location,
            actor_id=actor,
            payload={"actor": actor, "object": obj["description"],
                     "at": [x_cm, y_cm]},
            presence=presence,
            event_x_cm=x_cm,
            event_y_cm=y_cm,
            occurred_at=occurred_at,
        )
    return ActionResult(accepted=True, event_id=event_id)


def propose_pickup(
    world: WorldStore,
    *,
    actor: str,
    object_id: str,
    presence: list[str],
    location: str,
    occurred_at: str,
) -> ActionResult:
    """Pick up something lying in the world, if you are close enough to it.

    Preconditions: the actor exists and is placed, the object exists, the
    object is currently on the ground rather than held by anyone, and the actor
    is within INTERACTION_RANGE_CM of it. Reach is derived from canonical poses
    and the object's own position -- no caller asserts that it is reachable.
    """
    with world.transaction():
        if not world.being_exists(actor):
            return _rejected(UNKNOWN_ACTOR)
        obj = world.object_row(object_id)
        if obj is None:
            return _rejected(UNKNOWN_OBJECT)
        loc = world.object_location(object_id)
        if loc is None or loc["x_cm"] is None:
            return _rejected(NOT_ON_THE_GROUND)
        try:
            ax, ay, _, _ = world.current_pose(actor)
        except KeyError:
            return _rejected(NOT_PLACED)
        ox, oy = loc["x_cm"], loc["y_cm"]
        if not geometry.within_radius(ax, ay, ox, oy, INTERACTION_RANGE_CM):
            return _rejected(OUT_OF_REACH)

        world._take_object(object_id, actor)
        event_id = world._append_event_locked(
            kind="PICKUP",
            location=location,
            actor_id=actor,
            payload={"actor": actor, "object": obj["description"],
                     "at": [ox, oy]},
            presence=presence,
            event_x_cm=ox,
            event_y_cm=oy,
            occurred_at=occurred_at,
        )
    return ActionResult(accepted=True, event_id=event_id)
