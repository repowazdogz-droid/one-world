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
UNKNOWN_ATTEMPT = "UNKNOWN_ATTEMPT"
UNKNOWN_RESPONSE = "UNKNOWN_RESPONSE"
WRONG_RESPONDER = "WRONG_RESPONDER"
ALREADY_RESOLVED = "ALREADY_RESOLVED"

ACCEPT = "ACCEPT"
REFUSE = "REFUSE"
#: The whole vocabulary an inhabitant has for answering an offer. Anything else
#: fails closed -- the world does not guess what an unrecognised answer means.
RESPONSES = frozenset({ACCEPT, REFUSE})


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
