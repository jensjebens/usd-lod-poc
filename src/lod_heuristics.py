"""LOD Switching Heuristics — screen-space size computation and purpose decision.

Two metrics available:
  - compute_screen_size()    — fast cone-angle method (radius/distance). Primary.
  - compute_screen_fraction() — full NDC projection method. Appendix/fallback.

Purpose decision uses hysteresis to avoid flickering.
"""

from pxr import Usd, UsdGeom, Gf
import math


# ---------------------------------------------------------------------------
# Primary metric: Cone angle (bounding sphere)
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Secondary metric: NDC projection (full frustum)
# ---------------------------------------------------------------------------

def compute_screen_fraction(
    stage,
    prim_path: str,
    camera_path: str,
    time=None,
    image_width: int = 1920,
    image_height: int = 1080,
) -> float:
    """Compute the fraction of the screen covered by a prim's projected AABB.

    Projects all 8 bounding box corners through view-projection matrix to NDC.
    More precise than cone angle but ~10x slower.

    Args:
        stage: An open Usd.Stage.
        prim_path: Sdf path to the prim to measure.
        camera_path: Sdf path to the camera prim.
        time: UsdTimeCode (defaults to Usd.TimeCode.Default()).
        image_width: Output image width in pixels.
        image_height: Output image height in pixels.

    Returns:
        Float in [0.0, 1.0] — fraction of screen area covered.
        0.0 if the prim is entirely behind the camera or has no bounds.
    """
    if time is None:
        time = Usd.TimeCode.Default()

    prim = stage.GetPrimAtPath(prim_path)
    if not prim.IsValid():
        return 0.0

    camera_prim = stage.GetPrimAtPath(camera_path)
    if not camera_prim.IsValid():
        return 0.0

    # Compute world bounding box
    bbox_cache = UsdGeom.BBoxCache(time, ["default", "render", "proxy"])
    world_bbox = bbox_cache.ComputeWorldBound(prim)
    world_range = world_bbox.ComputeAlignedRange()

    if world_range.IsEmpty():
        return 0.0

    # Get camera frustum
    usd_camera = UsdGeom.Camera(camera_prim)
    gf_camera = usd_camera.GetCamera(time)
    frustum = gf_camera.frustum

    view_matrix = frustum.ComputeViewMatrix()
    proj_matrix = frustum.ComputeProjectionMatrix()
    vp = view_matrix * proj_matrix

    # 8 corners of the bounding box
    bbox_min = world_range.GetMin()
    bbox_max = world_range.GetMax()

    corners = [
        Gf.Vec3d(x, y, z)
        for x in (bbox_min[0], bbox_max[0])
        for y in (bbox_min[1], bbox_max[1])
        for z in (bbox_min[2], bbox_max[2])
    ]

    # Project each corner to NDC
    ndc_xs = []
    ndc_ys = []

    for corner in corners:
        clip = Gf.Vec4d(corner[0], corner[1], corner[2], 1.0) * Gf.Matrix4d(vp)
        w = clip[3]
        if w <= 0:
            continue
        ndc_xs.append(clip[0] / w)
        ndc_ys.append(clip[1] / w)

    if not ndc_xs:
        return 0.0

    # Clamp to NDC range [-1, 1]
    ndc_min_x = max(-1.0, min(ndc_xs))
    ndc_max_x = min(1.0, max(ndc_xs))
    ndc_min_y = max(-1.0, min(ndc_ys))
    ndc_max_y = min(1.0, max(ndc_ys))

    ndc_width = max(0.0, ndc_max_x - ndc_min_x)
    ndc_height = max(0.0, ndc_max_y - ndc_min_y)

    # Full NDC area is 2*2 = 4
    screen_fraction = (ndc_width * ndc_height) / 4.0

    return max(0.0, min(1.0, screen_fraction))


# ---------------------------------------------------------------------------
# Purpose decision with hysteresis
# ---------------------------------------------------------------------------

def decide_purpose(
    screen_fraction: float,
    current_purpose: str = "proxy",
    high_threshold: float = 0.05,
    low_threshold: float = 0.02,
) -> str:
    """Decide which purpose to use based on screen metric and hysteresis.

    Works with either metric (screen_size or screen_fraction) — just set
    thresholds appropriately for the metric you're using.

    Args:
        screen_fraction: Current screen metric value.
        current_purpose: Current active purpose ("render" or "proxy").
        high_threshold: Switch proxy → render when metric >= this.
        low_threshold: Switch render → proxy when metric <= this.

    Returns:
        "render" or "proxy".
    """
    if current_purpose == "proxy":
        if screen_fraction >= high_threshold:
            return "render"
        return "proxy"
    else:  # current_purpose == "render"
        if screen_fraction <= low_threshold:
            return "proxy"
        return "render"
