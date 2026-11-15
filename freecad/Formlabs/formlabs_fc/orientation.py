"""Maps the FreeCAD view to PreForm axes: what you see is how it lands.

FreeCAD is Z-up. The view camera orientation R (3x3, camera-to-world, column vectors) gives the screen axes in
world coordinates: right = R[:,0], up = R[:,1], toward the viewer = R[:,2]. A screen vector (a, b, c) becomes
PreForm (a, -c, b) (X right, Z up, front at -Y). In FreeCAD's Front view this is the identity.
"""
from __future__ import annotations

Matrix3 = list[list[float]]
Matrix4 = list[list[float]]

_SCREEN_TO_PREFORM: Matrix3 = [[1, 0, 0], [0, 0, -1], [0, 1, 0]]  # column vectors: p = S * screen
_IDENTITY: Matrix3 = [[1, 0, 0], [0, 1, 0], [0, 0, 1]]


def _mul(a: Matrix3, b: Matrix3) -> Matrix3:
    return [[sum(a[i][k] * b[k][j] for k in range(3)) for j in range(3)] for i in range(3)]


def _transpose(m: Matrix3) -> Matrix3:
    return [[m[j][i] for j in range(3)] for i in range(3)]


def quaternion_to_matrix(x: float, y: float, z: float, w: float) -> Matrix3:
    n = (x * x + y * y + z * z + w * w) ** 0.5 or 1.0
    x, y, z, w = x / n, y / n, z / n, w / n
    return [
        [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
        [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
        [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
    ]


def world_to_preform(camera_to_world: Matrix3) -> Matrix3:
    """Rotation taking world (model) coordinates to PreForm coordinates for this view."""
    return _mul(_SCREEN_TO_PREFORM, _transpose(camera_to_world))


def rotation_for(mode: str, camera_to_world: Matrix3 | None) -> Matrix3:
    """'view' (default): as the view shows it. 'same': axes unchanged. 'yup': stand a Y-up part up."""
    if mode == "yup":  # world (x, y, z) -> (x, -z, y)
        return [list(r) for r in _SCREEN_TO_PREFORM]
    if mode == "same" or camera_to_world is None:
        return [list(r) for r in _IDENTITY]
    return world_to_preform(camera_to_world)


def to_4x4(rot: Matrix3, translation=(0.0, 0.0, 0.0)) -> Matrix4:
    return [[float(v) for v in rot[i]] + [float(translation[i])] for i in range(3)] + [[0.0, 0.0, 0.0, 1.0]]


def apply(m: Matrix3, v) -> tuple[float, float, float]:
    return tuple(sum(m[i][k] * v[k] for k in range(3)) for i in range(3))  # type: ignore[return-value]
