"""Exact 2-D integer geometry. There is no floating point anywhere in this file.

Positions are integer centimetres. Facing is an integer vector (fx, fy), not
both zero; it is a direction, not a unit vector, and its magnitude is divided
out by the tests below.

Using integers throughout is a deliberate choice, not an accident of taste: a
perception grade decided by a float comparison could in principle differ across
libm implementations exactly on a threshold, which would make historical replay
machine-dependent. Every predicate here is exact.
"""

from __future__ import annotations

#: cos(45 deg)^2 = 1/2, which is what makes the cone test exact in integers.
HALF_FOV_DEGREES = 45


def dist_sq(ax: int, ay: int, bx: int, by: int) -> int:
    """Squared distance in cm^2. Exact."""
    dx = bx - ax
    dy = by - ay
    return dx * dx + dy * dy


def within_radius(ax: int, ay: int, bx: int, by: int, radius_cm: int) -> bool:
    """Is b within radius_cm of a?

    BOUNDARY: INCLUSIVE. Exactly on the radius counts as within.
    """
    return dist_sq(ax, ay, bx, by) <= radius_cm * radius_cm


def _orient(ax: int, ay: int, bx: int, by: int, px: int, py: int) -> int:
    """Cross product (b-a) x (p-a). Sign says which side of line ab p lies on."""
    return (bx - ax) * (py - ay) - (by - ay) * (px - ax)


def _sign(n: int) -> int:
    return (n > 0) - (n < 0)


def _on_closed(ax: int, ay: int, bx: int, by: int, px: int, py: int) -> bool:
    """Is p within the bounding box of segment ab?

    Only meaningful once p is known to be COLLINEAR with ab, which is how every
    caller here uses it.
    """
    return min(ax, bx) <= px <= max(ax, bx) and min(ay, by) <= py <= max(ay, by)


def _collinear_occludes(wall, ox: int, oy: int, ex: int, ey: int) -> bool:
    """All four points lie on one line. Does the overlap block sight?"""
    wx1, wy1, wx2, wy2 = wall
    # Project onto an axis that separates points on this line. If the wall is
    # vertical every point shares an x, so use y; otherwise x works.
    if wx1 == wx2:
        wa, wb, sa, sb = wy1, wy2, oy, ey
    else:
        wa, wb, sa, sb = wx1, wx2, ox, ex
    lo = max(min(wa, wb), min(sa, sb))
    hi = min(max(wa, wb), max(sa, sb))
    if lo > hi:
        return False  # collinear but disjoint
    if lo < hi:
        return True  # overlap of positive length: contains interior points
    # A single shared point. It blocks only if it is not an endpoint of the
    # sight line itself. (For a non-degenerate wall this is always an endpoint,
    # so the branch is defensive rather than reachable.)
    return lo != sa and lo != sb


def occludes(wall, ox: int, oy: int, ex: int, ey: int) -> bool:
    """Does `wall` block sight from (ox, oy) to (ex, ey)?

    SEMANTICS, chosen rather than inherited:

        A wall occludes iff some point of the CLOSED wall segment lies on the
        sight segment EXCLUDING the sight segment's own two endpoints.

    The wall is closed and the sight line is open, and each half of that is a
    deliberate decision:

      * Closed wall -- sight grazing a wall's ENDPOINT is BLOCKED. An
        information barrier should err toward withholding, never toward
        leaking, which is the same instinct as fail-closed projection.
      * Open sight line -- an observer STANDING ON a wall is not blinded by it,
        and an event happening ON a wall is still visible. You are at the
        barrier, not behind it. Blocking here would mean standing against a
        wall blinds you to everything, which is nonsense.

    A zero-length wall is rejected rather than given invented semantics.
    """
    wx1, wy1, wx2, wy2 = wall
    if wx1 == wx2 and wy1 == wy2:
        raise ValueError("zero-length wall has no occlusion semantics")
    if ox == ex and oy == ey:
        return False  # no sight line at all; callers treat dsq == 0 as CLEAR

    d1 = _orient(wx1, wy1, wx2, wy2, ox, oy)
    d2 = _orient(wx1, wy1, wx2, wy2, ex, ey)
    d3 = _orient(ox, oy, ex, ey, wx1, wy1)
    d4 = _orient(ox, oy, ex, ey, wx2, wy2)

    if d1 == 0 and d2 == 0:
        return _collinear_occludes(wall, ox, oy, ex, ey)

    # Proper crossing: strictly through the interior of both segments.
    if _sign(d1) * _sign(d2) < 0 and _sign(d3) * _sign(d4) < 0:
        return True

    # Non-collinear segments share at most one point, so these are exclusive.
    if d1 == 0 and _on_closed(wx1, wy1, wx2, wy2, ox, oy):
        return False  # sight line STARTS on the wall: observer at the barrier
    if d2 == 0 and _on_closed(wx1, wy1, wx2, wy2, ex, ey):
        return False  # the event happens ON the wall
    if d3 == 0 and _on_closed(ox, oy, ex, ey, wx1, wy1):
        return True  # a wall END lies across the line of sight
    if d4 == 0 and _on_closed(ox, oy, ex, ey, wx2, wy2):
        return True
    return False


def occluded_by_any(walls, ox: int, oy: int, ex: int, ey: int) -> bool:
    """Sight is blocked if ANY wall blocks it."""
    return any(occludes(w, ox, oy, ex, ey) for w in walls)


def in_facing_cone(ox: int, oy: int, fx: int, fy: int, tx: int, ty: int) -> bool:
    """Is (tx, ty) within HALF_FOV_DEGREES of facing (fx, fy), seen from (ox, oy)?

    cos(45 deg) = sqrt(2)/2, so cos^2 = 1/2 and

        dot / (|v| * |f|) >= sqrt(2)/2

    becomes, for dot > 0,

        2 * dot^2 >= |v|^2 * |f|^2

    which is exact integer arithmetic -- no sqrt, no cos, no atan2.

    BOUNDARIES:
      * dot <= 0 is EXCLUSIVE: a target exactly abeam (90 deg off facing) or
        behind is NOT visible.
      * the cone edge is INCLUSIVE: a target at exactly 45 deg IS visible.
      * a target at the observer's own position (dsq == 0) has no direction and
        is rejected here; callers handle that case explicitly before asking.
    """
    vx = tx - ox
    vy = ty - oy
    dot = vx * fx + vy * fy
    if dot <= 0:
        return False
    dsq = vx * vx + vy * vy
    fsq = fx * fx + fy * fy
    return 2 * dot * dot >= dsq * fsq
