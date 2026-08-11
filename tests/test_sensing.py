"""Unit tests for the physical perception model.

INDEPENDENCE NOTE: every expected value below is a hand-computed literal. None
is recomputed with geometry.py, because a test that re-derives the answer with
the production formula agrees with it by construction and would confirm a bug
just as happily as correct code.

Worked example for the cone test, facing (1,0) from the origin, target (100,101):
    dot  = 100*1 + 101*0                 = 100
    dsq  = 100*100 + 101*101             = 20201
    fsq  = 1*1 + 0*0                     = 1
    2*dot^2 = 20000  >=  dsq*fsq = 20201  ->  FALSE, just outside the 45 deg cone
Whereas target (100,100) is exactly 45 deg:
    2*dot^2 = 20000  >=  dsq*fsq = 20000  ->  TRUE, inclusive edge
"""

from __future__ import annotations

import pytest

from one_world.sensing import sense_event

OBS = "noah"  # a non-actor observer throughout
ACTOR = "warren"


def see(x, y, fx, fy, ex=0, ey=0):
    """Grade for one observer at (x,y) facing (fx,fy), event at (ex,ey)."""
    return sense_event(
        kind="GIVE", actor_id=ACTOR, event_x_cm=ex, event_y_cm=ey,
        audio_mode=None, poses={OBS: (x, y, fx, fy)}, walls=(),
    ).get(OBS)


def hear(x, y, mode, sx=0, sy=0):
    return sense_event(
        kind="SPEECH", actor_id=ACTOR, event_x_cm=sx, event_y_cm=sy,
        audio_mode=mode, poses={OBS: (x, y, 1, 0), ACTOR: (sx, sy, 1, 0)}, walls=(),
    ).get(OBS)


# -- visual range and detail, with the thresholds stated explicitly ------
# Observer stands at (-d, 0) facing (1,0); the event is at the origin, so the
# observer is d cm away and looking straight at it.

@pytest.mark.parametrize(
    "distance_cm,expected",
    [
        (1,     "CLEAR"),    # nose to nose
        (100,   "CLEAR"),
        (299,   "CLEAR"),
        (300,   "CLEAR"),    # DETAIL_RANGE_CM exactly: INCLUSIVE
        (301,   "COARSE"),   # one cm past detail
        (800,   "COARSE"),   # the scenario's Noah
        (1499,  "COARSE"),
        (1500,  "COARSE"),   # VIEW_RANGE_CM exactly: INCLUSIVE
        (1501,  None),       # one cm past sight
        (10000, None),
    ],
)
def test_visual_detail_by_distance(distance_cm, expected):
    assert see(-distance_cm, 0, 1, 0) == expected


# -- the 45 degree cone --------------------------------------------------
# Observer at the origin facing (1,0); event at the given point,
# all well inside the detail range so only the angle decides.

@pytest.mark.parametrize(
    "ex,ey,expected",
    [
        (100, 0,    "CLEAR"),   # dead ahead
        (100, 100,  "CLEAR"),   # exactly 45 deg: INCLUSIVE edge
        (100, -100, "CLEAR"),   # symmetric on the other side
        (100, 101,  None),      # a hair outside 45 deg
        (100, -101, None),
        (0,   100,  None),      # exactly abeam, 90 deg: EXCLUSIVE
        (0,   -100, None),
        (-100, 0,   None),      # directly behind
        (-100, 100, None),
    ],
)
def test_visual_cone(ex, ey, expected):
    assert see(0, 0, 1, 0, ex, ey) == expected


def test_facing_magnitude_does_not_matter():
    """Facing is a direction, not a unit vector; |f| divides out."""
    assert see(0, 0, 1, 0, 100, 0) == see(0, 0, 7, 0, 100, 0) == "CLEAR"
    assert see(0, 0, 3, 3, 100, 100) == "CLEAR"


def test_observer_standing_on_the_event_sees_it_regardless_of_facing():
    """dsq == 0 has no direction; handled explicitly rather than by arithmetic."""
    assert see(0, 0, 1, 0, 0, 0) == "CLEAR"
    assert see(0, 0, -1, 0, 0, 0) == "CLEAR"


def test_actor_always_perceives_own_event():
    """Agency, not vision: facing away from what you yourself are doing."""
    got = sense_event(
        kind="GIVE", actor_id=ACTOR, event_x_cm=9999, event_y_cm=9999,
        audio_mode=None, poses={ACTOR: (0, 0, -1, 0)}, walls=(),
    )
    assert got == {ACTOR: "CLEAR"}


# -- hearing -------------------------------------------------------------

@pytest.mark.parametrize(
    "distance_cm,mode,expected",
    [
        (0,    "DIRECTED", "CLEAR"),
        (100,  "DIRECTED", "CLEAR"),   # the scenario's Ava
        (149,  "DIRECTED", "CLEAR"),
        (150,  "DIRECTED", "CLEAR"),   # radius exactly: INCLUSIVE
        (151,  "DIRECTED", None),
        (802,  "DIRECTED", None),      # the scenario's Noah
        (802,  "PUBLIC",   "CLEAR"),   # same spot, louder speech
        (1000, "PUBLIC",   "CLEAR"),   # radius exactly: INCLUSIVE
        (1001, "PUBLIC",   None),
    ],
)
def test_hearing_by_distance_and_mode(distance_cm, mode, expected):
    assert hear(distance_cm, 0, mode) == expected


def test_hearing_ignores_facing():
    """Sound is omnidirectional in this model. Deliberately crude."""
    for fx, fy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
        got = sense_event(
            kind="SPEECH", actor_id=ACTOR, event_x_cm=0, event_y_cm=0,
            audio_mode="DIRECTED", poses={OBS: (100, 0, fx, fy), ACTOR: (0, 0, 1, 0)},
            walls=(),
        )
        assert got.get(OBS) == "CLEAR"


def test_hearing_is_binary_and_never_coarse():
    """A COARSE speech grade would need a SPEECH/COARSE projection, and v0.1
    deliberately has none. Guard the invariant at the source."""
    for distance in (0, 1, 149, 150, 151, 5000):
        assert hear(distance, 0, "DIRECTED") in ("CLEAR", None)


# -- fail closed ---------------------------------------------------------


def test_unknown_event_kind_fails_closed():
    """A new kind must declare its modality, not default to full visibility."""
    with pytest.raises(ValueError, match="no sensing rule"):
        sense_event(kind="TELEPORT", actor_id=ACTOR, event_x_cm=0, event_y_cm=0,
                    audio_mode=None, poses={OBS: (0, 0, 1, 0)}, walls=())


def test_unknown_audio_mode_fails_closed():
    with pytest.raises(ValueError, match="unknown audio mode"):
        hear(10, 0, "TELEPATHY")


def test_visual_event_carrying_audio_mode_fails_closed():
    with pytest.raises(ValueError, match="visual but carries audio_mode"):
        sense_event(kind="GIVE", actor_id=ACTOR, event_x_cm=0, event_y_cm=0,
                    audio_mode="PUBLIC", poses={OBS: (0, 0, 1, 0)}, walls=())


def test_speech_without_speaker_pose_fails_closed():
    with pytest.raises(ValueError, match="no event-time pose"):
        sense_event(kind="SPEECH", actor_id=ACTOR, event_x_cm=0, event_y_cm=0,
                    audio_mode="PUBLIC", poses={OBS: (0, 0, 1, 0)}, walls=())


def test_beings_who_perceive_nothing_are_absent_not_null():
    """Matches the v0.1 convention: a missing row means did not perceive."""
    got = sense_event(
        kind="GIVE", actor_id=ACTOR, event_x_cm=0, event_y_cm=0, audio_mode=None,
        poses={"near": (-100, 0, 1, 0), "far": (-99999, 0, 1, 0)}, walls=(),
    )
    assert got == {"near": "CLEAR"}


def test_sensing_is_pure_and_repeatable():
    """Same inputs, same answer -- no clock, no randomness, no float."""
    poses = {"a": (-800, 0, 1, 0), "b": (-100, 0, 1, 0), "c": (0, 900, 1, 0)}
    first = sense_event(kind="GIVE", actor_id=ACTOR, event_x_cm=0, event_y_cm=0,
                        audio_mode=None, poses=poses, walls=())
    for _ in range(5):
        assert sense_event(kind="GIVE", actor_id=ACTOR, event_x_cm=0, event_y_cm=0,
                           audio_mode=None, poses=poses, walls=()) == first
    assert first == {"a": "COARSE", "b": "CLEAR"}  # c is abeam -> absent
