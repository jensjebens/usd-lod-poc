"""LOD Switching Heuristics — screen-space size computation and purpose decision.

Primary metric: compute_screen_size() — fast cone-angle method (radius/distance).
Purpose decision uses hysteresis to avoid flickering.
"""

from pxr import Usd, UsdGeom, Gf


def compute_screen_size(
    stage,
    prim_path: str,
    camera_path: str,
    time=None,
) -> float:
    """Compute bounding-sphere screen size ratio (radius / distance).

    This is the tangent of the half-cone-angle subtended by the object's
    bounding sphere as seen from the camera. Camera-parameter independent.

    Args:
        stage: An open Usd.Stage.
        prim_path: Sdf path to the prim to measure.
        camera_path: Sdf path to the camera prim.
        time: UsdTimeCode (defaults to Usd.TimeCode.Default()).

    Returns:
        Float in [0.0, 1.0] — radius/distance ratio.
        1.0 if camera is inside the bounding sphere.
        0.0 if prim has no bounds or is invalid.
    """
    if time is None:
        time = Usd.TimeCode.Default()

    prim = stage.GetPrimAtPath(prim_path)
    if not prim.IsValid():
        return 0.0

    camera_prim = stage.GetPrimAtPath(camera_path)
    if not camera_prim.IsValid():
        return 0.0

    # World bounding box → bounding sphere
    bbox_cache = UsdGeom.BBoxCache(time, ["default", "render", "proxy"])
    world_bbox = bbox_cache.ComputeWorldBound(prim)
    aligned = world_bbox.ComputeAlignedRange()

    if aligned.IsEmpty():
        return 0.0

    bbox_min = Gf.Vec3d(aligned.GetMin())
    bbox_max = Gf.Vec3d(aligned.GetMax())
    centre = (bbox_min + bbox_max) * 0.5
    radius = (bbox_max - centre).GetLength()

    if radius <= 0.0:
        return 0.0

    # Camera eye position
    usd_camera = UsdGeom.Camera(camera_prim)
    gf_camera = usd_camera.GetCamera(time)
    eye = gf_camera.frustum.GetPosition()

    distance = (centre - eye).GetLength()

    if distance <= radius:
        return 1.0  # Camera inside bounding sphere

    return min(1.0, radius / distance)


def decide_purpose(
    screen_size: float,
    current_purpose: str = "proxy",
    high_threshold: float = 0.02,
    low_threshold: float = 0.008,
) -> str:
    """Decide which purpose to use based on screen size and hysteresis.

    Args:
        screen_size: Current screen size metric (radius/distance).
        current_purpose: Current active purpose ("render" or "proxy").
        high_threshold: Switch proxy → render when metric >= this.
        low_threshold: Switch render → proxy when metric <= this.

    Returns:
        "render" or "proxy".
    """
    if current_purpose == "proxy":
        if screen_size >= high_threshold:
            return "render"
        return "proxy"
    else:  # current_purpose == "render"
        if screen_size <= low_threshold:
            return "proxy"
        return "render"
