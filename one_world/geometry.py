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
