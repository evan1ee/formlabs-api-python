"""4x4 homogeneous transforms (spec §6.2). Row-major lists, column vectors, right-handed, mm."""

from __future__ import annotations

import math

Matrix = list[list[float]]


def identity() -> Matrix:
    return [[1.0 if i == j else 0.0 for j in range(4)] for i in range(4)]


def multiply(a: Matrix, b: Matrix) -> Matrix:
    return [[sum(a[i][k] * b[k][j] for k in range(4)) for j in range(4)] for i in range(4)]


def rotation(axis: str, degrees: float) -> Matrix:
    c, s = math.cos(math.radians(degrees)), math.sin(math.radians(degrees))
    m = identity()
    if axis == "x":
        m[1][1], m[1][2], m[2][1], m[2][2] = c, -s, s, c
    elif axis == "y":
        m[0][0], m[0][2], m[2][0], m[2][2] = c, s, -s, c
    elif axis == "z":
        m[0][0], m[0][1], m[1][0], m[1][1] = c, -s, s, c
    else:
        raise ValueError(f"axis must be x, y or z, got {axis!r}")
    return m


def translation(x: float, y: float, z: float) -> Matrix:
    m = identity()
    m[0][3], m[1][3], m[2][3] = x, y, z
    return m


def apply(m: Matrix, p: tuple[float, float, float]) -> tuple[float, float, float]:
    v = (*p, 1.0)
    return tuple(sum(m[i][k] * v[k] for k in range(4)) for i in range(3))  # type: ignore[return-value]


def invert_rigid(m: Matrix) -> Matrix:
    """Inverse of a rotation+translation matrix (no scale, no shear)."""
    r = [[m[j][i] for j in range(3)] for i in range(3)]
    t = [-sum(r[i][k] * m[k][3] for k in range(3)) for i in range(3)]
    out = identity()
    for i in range(3):
        for j in range(3):
            out[i][j] = r[i][j]
        out[i][3] = t[i]
    return out


def validate_rigid(m: Matrix, tol: float = 1e-6) -> None:
    """Reject scale, shear, reflection (left-handed) and non-affine matrices."""
    if len(m) != 4 or any(len(r) != 4 for r in m):
        raise ValueError("transform must be 4x4")
    if any(abs(m[3][j] - (1.0 if j == 3 else 0.0)) > tol for j in range(4)):
        raise ValueError("last row must be [0,0,0,1]")
    for i in range(3):
        for j in range(3):
            dot = sum(m[k][i] * m[k][j] for k in range(3))
            if abs(dot - (1.0 if i == j else 0.0)) > tol:
                raise ValueError("rotation block is not orthonormal (scale or shear present)")
    det = (
        m[0][0] * (m[1][1] * m[2][2] - m[1][2] * m[2][1])
        - m[0][1] * (m[1][0] * m[2][2] - m[1][2] * m[2][0])
        + m[0][2] * (m[1][0] * m[2][1] - m[1][1] * m[2][0])
    )
    if det < 0:
        raise ValueError("transform is left-handed (reflection)")
