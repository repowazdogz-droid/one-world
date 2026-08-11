"""The occlusion predicate, case by case.

INDEPENDENCE NOTE: every expectation is a hand-reasoned boolean. Nothing here
recomputes the answer with the production predicate, because a test that
re-derives its expectation from the code under test agrees with that code by
construction and would bless a bug as readily as correct behaviour.

The chosen semantics, restated:

    a wall occludes iff some point of the CLOSED wall segment lies on the sight
    segment EXCLUDING the sight segment's own two endpoints.

Closed wall  -> grazing a wall END blocks (barriers err toward withholding).
Open sight   -> standing ON a wall does not blind you, and an event ON a wall
                is still visible (you are AT the barrier, not behind it).
"""

from __future__ import annotations

import pytest

from one_world.geometry import occludes, occluded_by_any

#: A vertical wall at x=100 spanning y in [-50, 50].
W = (100, -50, 100, 50)


# -- the ordinary cases --------------------------------------------------


@pytest.mark.parametrize(
    "ox,oy,ex,ey,expected,why",
    [
        # Sight along y=0 from x=200 to x=0 crosses x=100 at (100,0),
        # which is inside the wall's y-range and interior to the sight line.
        (200, 0, 0, 0, True, "ordinary crossing"),
        # Sight from x=200 to x=150 never reaches x=100.
        (200, 0, 150, 0, False, "no intersection: wall beyond the event"),
        # Observer at x=50 looking to x=0; the wall at x=100 is behind them.
        (50, 0, 0, 0, False, "wall behind the observer"),
        # Sight along y=200 passes far above the wall's y-range of [-50,50].
        (200, 200, 0, 200, False, "parallel offset, never meets the wall"),
        # (200,200)->(0,0) reaches x=100 at y=100, above the wall's top at 50.
        (200, 200, 0, 0, False, "diagonal passes over the wall's end"),
        # (200,60)->(0,-60) reaches x=100 at y=0, inside the wall.
        (200, 60, 0, -60, True, "diagonal crossing through the wall"),
    ],
)
def test_ordinary_cases(ox, oy, ex, ey, expected, why):
    assert occludes(W, ox, oy, ex, ey) is expected, why


# -- degenerate cases, each decided deliberately -------------------------


def test_sight_grazing_a_wall_endpoint_blocks():
    """The wall is CLOSED: touching its very end still blocks.

    Wall (100,0)-(100,50); sight (200,0)->(0,0) touches exactly (100,0), the
    wall's own endpoint, and that point is interior to the sight line.
    """
    assert occludes((100, 0, 100, 50), 200, 0, 0, 0) is True


def test_observer_standing_on_a_wall_is_not_blinded_by_it():
    """The sight line is OPEN at its endpoints. Observer at (100,0) is ON W."""
    assert occludes(W, 100, 0, 0, 0) is False


def test_observer_standing_on_a_wall_endpoint_is_not_blinded_by_it():
    assert occludes(W, 100, 50, 0, 0) is False


def test_event_occurring_on_a_wall_is_still_visible():
    """Event at (100,0) lies on W; the observer is at (200,0)."""
    assert occludes(W, 200, 0, 100, 0) is False


@pytest.mark.parametrize(
    "wall,ox,oy,ex,ey,expected,why",
    [
        # Wall lies along y=0 from x=100 to x=200; sight runs x=300 -> x=0.
        # Overlap on x is [100,200]: positive length, so sight passes along it.
        ((100, 0, 200, 0), 300, 0, 0, 0, True, "collinear, overlapping"),
        # Wall x in [400,500]; sight x in [0,300]. Disjoint on the shared line.
        ((400, 0, 500, 0), 300, 0, 0, 0, False, "collinear, disjoint"),
        # Wall x in [300,400]; sight x in [0,300]. They share only x=300,
        # which is the observer's own position -- a sight-line endpoint.
        ((300, 0, 400, 0), 300, 0, 0, 0, False, "collinear, touching at observer"),
        # Wall x in [-100,0]; shares only x=0, the event's position.
        ((-100, 0, 0, 0), 300, 0, 0, 0, False, "collinear, touching at event"),
    ],
)
def test_collinear_cases(wall, ox, oy, ex, ey, expected, why):
    assert occludes(wall, ox, oy, ex, ey) is expected, why


def test_vertical_collinear_uses_the_other_axis():
    """A vertical wall shares x with the sight line, so x cannot separate."""
    assert occludes((0, 100, 0, 200), 0, 300, 0, 0) is True   # overlap [100,200]
    assert occludes((0, 400, 0, 500), 0, 300, 0, 0) is False  # disjoint


def test_zero_length_wall_is_rejected_not_interpreted():
    with pytest.raises(ValueError, match="zero-length wall"):
        occludes((100, 0, 100, 0), 200, 0, 0, 0)


def test_no_sight_line_cannot_be_occluded():
    """Observer standing exactly on the event; callers treat this as CLEAR."""
    assert occludes(W, 0, 0, 0, 0) is False


# -- multiple walls ------------------------------------------------------


def test_any_wall_blocks():
    far = (400, -50, 400, 50)
    assert occluded_by_any([], 200, 0, 0, 0) is False
    assert occluded_by_any([far], 200, 0, 0, 0) is False       # beyond the event
    assert occluded_by_any([far, W], 200, 0, 0, 0) is True     # W blocks
    assert occluded_by_any([W, far], 200, 0, 0, 0) is True     # order irrelevant


def test_occlusion_is_symmetric_in_the_sight_line():
    """Blocking does not depend on which end you look from."""
    assert occludes(W, 200, 0, 0, 0) == occludes(W, 0, 0, 200, 0) is True


def test_predicate_is_pure_and_repeatable():
    for _ in range(5):
        assert occludes(W, 200, 0, 0, 0) is True
        assert occludes(W, 50, 0, 0, 0) is False
