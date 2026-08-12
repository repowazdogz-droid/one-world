"""The physical perception model: derives observation grades from world state.

This replaces the v0.1 seam where an author handed CLEAR / COARSE to
commit_event. Nothing here is authored per event; grades follow from positions,
facing, and the event's own physical parameters.

Deliberately crude, but with explicit semantics. What it establishes is that
different physical situations DETERMINISTICALLY produce different subjective
histories. What it does not establish is anything about real vision or acoustics
-- see the claim audit in README.
"""

from __future__ import annotations

from one_world import geometry

VISUAL = "VISUAL"
AUDIO = "AUDIO"
#: v0.9. The actor knows they did it; nobody else perceives it at all.
#:
#: CALIBRATION -- why LOOK is not VISUAL. This model has no physical
#: manifestation of looking. The only externally visible correlate of where
#: someone is attending is their FACING, and changing facing is already a MOVE
#: with its own event and its own perception. Making LOOK visual would mean
#: inventing eye or head motion that nothing else in the world models, so
#: bystanders receive NO perception of a LOOK rather than a made-up one.
#:
#: This is a deliberately conservative choice and a real limitation, not a
#: claim that looking is undetectable in principle.
AGENCY = "AGENCY"

#: Which sense carries which kind of event. Unknown kinds FAIL CLOSED: a new
#: event kind must declare its modality rather than defaulting to full
#: visibility for everyone.
MODALITY = {
    "GIVE": VISUAL,
    "GIVE_ATTEMPT": VISUAL,   # you can watch someone offer something
    "MOVE": VISUAL,           # you can watch someone set off
    "PLACE": VISUAL,          # you can watch someone put something down
    "PICKUP": VISUAL,
    "STOW": VISUAL,
    "SPEECH": AUDIO,
    "REFUSAL": AUDIO,         # saying no out loud; heard, not seen
    "LOOK": AGENCY,           # v0.9: you know you looked; nobody sees you do it
}

#: Beyond this, an event is not seen at all.
VIEW_RANGE_CM = 1500
#: Within this (and in the cone), object identity resolves. Between the two, the
#: event is seen but its details are not.
DETAIL_RANGE_CM = 300

#: Speech is heard iff the listener is within the radius for its mode.
#: Hearing is BINARY here: it never yields COARSE, because a partial-audibility
#: grade would need a SPEECH/COARSE projection, and v0.1 deliberately has none.
#:
#: CALIBRATION -- what DIRECTED does and does not mean. DIRECTED is nothing more
#: than a SHORTER DETERMINISTIC HEARING RADIUS. It is not addressee-aware: the
#: model never consults who the speaker was talking to, and anyone standing
#: inside the radius hears the sentence exactly as the addressee does. It is not
#: an acoustic model either -- no attenuation curve, no volume, no directivity,
#: no masking, no walls. That Ava hears the private line and Noah does not is a
#: consequence of 100 cm vs 802 cm, and of nothing else.
AUDIO_RANGE_CM = {
    "PUBLIC": 1000,
    "DIRECTED": 150,
}


def _visual_grade(ox, oy, fx, fy, tx, ty, walls):
    """CLEAR / COARSE / None for looking at the point (tx, ty) from a pose.

    The WHOLE of the visual model, and the single implementation of it. Event
    sensing and arrival-state sensing both come through here, so "can Ava see
    the lighter lying there" is decided by exactly the same range, cone and
    occlusion rules as "can Ava see Warren put it down". Two copies of this
    could drift apart into two different physics; one cannot.
    """
    dsq = geometry.dist_sq(ox, oy, tx, ty)
    if dsq == 0:
        return "CLEAR"  # standing on it; no direction to test
    if dsq > VIEW_RANGE_CM * VIEW_RANGE_CM:
        return None
    if not geometry.in_facing_cone(ox, oy, fx, fy, tx, ty):
        return None
    if geometry.occluded_by_any(walls, ox, oy, tx, ty):
        return None  # v0.3: solid structure between observer and target
    if dsq <= DETAIL_RANGE_CM * DETAIL_RANGE_CM:
        return "CLEAR"
    return "COARSE"


def _see(observer_id, actor_id, ox, oy, fx, fy, ex, ey, walls):
    if observer_id == actor_id:
        # CALIBRATION -- this is SELF / AGENCY knowledge in a deliberately small
        # model: an actor is taken to know what they themselves just did. It is
        # NOT a claim that the actor visually perceived their own action, and no
        # geometry is consulted here. It exists so that a degenerate case (an
        # actor at zero distance from their own event, where facing has no
        # meaning) has an explicit answer rather than an arithmetic accident.
        return "CLEAR"
    return _visual_grade(ox, oy, fx, fy, ex, ey, walls)


def _hear(observer_id, actor_id, ox, oy, sx, sy, audio_mode):
    if observer_id == actor_id:
        return "CLEAR"  # you hear yourself speak
    radius = AUDIO_RANGE_CM.get(audio_mode)
    if radius is None:
        raise ValueError(f"unknown audio mode: {audio_mode!r}")
    if geometry.within_radius(ox, oy, sx, sy, radius):
        return "CLEAR"
    return None


def sense_event(
    *,
    kind: str,
    actor_id: str,
    event_x_cm: int,
    event_y_cm: int,
    audio_mode: str | None,
    poses: dict[str, tuple[int, int, int, int]],
    walls: tuple,
) -> dict[str, str]:
    """Derive {being_id: grade} for one event from event-time poses and geometry.

    Beings who perceived nothing are ABSENT from the result, matching the v0.1
    convention that a missing world_observation row means "did not perceive".

    Pure and total over its inputs: same poses, geometry and parameters, same
    answer, on any machine and at any later time.

    `walls` is REQUIRED and has no default. Since canonical structure now
    changes what people perceive, it is a load-bearing sensing input, and the
    two situations must stay distinguishable:

        walls=()          an explicit canonical fact -- this event-time
                          snapshot contained no walls
        walls omitted     a programmer error -- a required input was not
                          supplied

    A default would silently collapse the second into the first and quietly
    restore unoccluded v0.2 sensing, which is exactly the failure this
    signature exists to prevent.
    """
    modality = MODALITY.get(kind)
    if modality is None:
        raise ValueError(f"no sensing rule defined for event kind {kind!r}")

    if modality == AGENCY:
        # No geometry is consulted, and deliberately so: this is not a claim
        # that the actor SAW their own action, it is the same self-knowledge
        # rule _see applies to an actor, with the visual case removed entirely
        # because there is nothing for anyone else to see.
        if audio_mode is not None:
            raise ValueError(f"{kind!r} is silent but carries audio_mode {audio_mode!r}")
        if actor_id not in poses:
            raise ValueError(f"actor {actor_id!r} has no event-time pose")
        return {actor_id: "CLEAR"}

    if modality == VISUAL:
        if audio_mode is not None:
            raise ValueError(f"{kind!r} is visual but carries audio_mode {audio_mode!r}")
        graded = {
            being_id: _see(being_id, actor_id, x, y, fx, fy,
                           event_x_cm, event_y_cm, walls)
            for being_id, (x, y, fx, fy) in sorted(poses.items())
        }
    else:
        # Walls are a VISUAL barrier only. Sound occlusion is out of scope for
        # v0.3 and is deliberately not modelled: `walls` is ignored here.
        if actor_id not in poses:
            raise ValueError(f"speaker {actor_id!r} has no event-time pose")
        sx, sy, _, _ = poses[actor_id]
        graded = {
            being_id: _hear(being_id, actor_id, x, y, sx, sy, audio_mode)
            for being_id, (x, y, _fx, _fy) in sorted(poses.items())
        }

    return {b: g for b, g in graded.items() if g is not None}


def sense_state(
    *,
    observer_pose: tuple[int, int, int, int],
    objects: tuple,
    walls: tuple,
) -> dict[str, str]:
    """Derive {object_id: grade} for objects LYING IN THE WORLD right now.

    This is the second epistemic source, and it is deliberately NOT sense_event:

      * There is no actor and therefore NO AGENCY SHORTCUT. An object you own,
        or put down yourself, is invisible from across a wall like any other.
        Knowing where you left something is memory, not sight, and v0.8 does
        not model it.
      * There is no modality table. Objects lying on the ground do not make a
        sound, so state sensing is visual and only visual.

    `objects` is a sequence of (object_id, x_cm, y_cm) -- PLACED objects only.
    Held and stowed objects are not passed in, and this function has no way to
    ask about them.

    Objects that were not visible are ABSENT from the result, matching the
    convention that a missing row means "did not perceive".

    Pure and total over its inputs. `walls` is REQUIRED and has no default, for
    the reason spelled out on sense_event: an omitted barrier set must not
    silently become an asserted empty one.
    """
    ox, oy, fx, fy = observer_pose
    graded = {
        object_id: _visual_grade(ox, oy, fx, fy, x, y, walls)
        for object_id, x, y in sorted(objects)
    }
    return {o: g for o, g in graded.items() if g is not None}
