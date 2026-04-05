"""LOD Switching Heuristics — screen-space size computation and purpose decision.

Computes how large a prim appears on screen (as a fraction of total screen area)
and decides whether to use 'render' or 'proxy' purpose using a hysteresis model.
"""

from pxr import Usd, UsdGeom, Gf
import math


def compute_screen_fraction(
    stage,
    prim_path: str,
    camera_path: str,
    time=None,
    image_width: int = 1920,
    image_height: int = 1080,
) -> float:
    """Compute the fraction of the screen covered by a prim's bounding box.

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

    # Get the 8 corners of the bounding box
    bbox_min = world_range.GetMin()
    bbox_max = world_range.GetMax()

    corners = [
        Gf.Vec3d(bbox_min[0], bbox_min[1], bbox_min[2]),
        Gf.Vec3d(bbox_max[0], bbox_min[1], bbox_min[2]),
        Gf.Vec3d(bbox_min[0], bbox_max[1], bbox_min[2]),
        Gf.Vec3d(bbox_max[0], bbox_max[1], bbox_min[2]),
        Gf.Vec3d(bbox_min[0], bbox_min[1], bbox_max[2]),
        Gf.Vec3d(bbox_max[0], bbox_min[1], bbox_max[2]),
        Gf.Vec3d(bbox_min[0], bbox_max[1], bbox_max[2]),
        Gf.Vec3d(bbox_max[0], bbox_max[1], bbox_max[2]),
    ]

    # Project each corner to NDC
    ndc_xs = []
    ndc_ys = []

    for corner in corners:
        # Homogeneous point
        hom = Gf.Vec4d(corner[0], corner[1], corner[2], 1.0)

        # Transform through view-projection
        clip = hom * Gf.Matrix4d(vp)

        w = clip[3]
        if w <= 0:
            # Behind camera — skip this corner
            continue

        ndc_x = clip[0] / w
        ndc_y = clip[1] / w

        ndc_xs.append(ndc_x)
        ndc_ys.append(ndc_y)

    if not ndc_xs:
        # All corners behind camera
        return 0.0

    # Clamp to NDC range [-1, 1]
    ndc_min_x = max(-1.0, min(ndc_xs))
    ndc_max_x = min(1.0, max(ndc_xs))
    ndc_min_y = max(-1.0, min(ndc_ys))
    ndc_max_y = min(1.0, max(ndc_ys))

    # Compute screen fraction
    ndc_width = max(0.0, ndc_max_x - ndc_min_x)
    ndc_height = max(0.0, ndc_max_y - ndc_min_y)

    # Full NDC area is 2*2 = 4
    screen_fraction = (ndc_width * ndc_height) / 4.0

    return max(0.0, min(1.0, screen_fraction))


def decide_purpose(
    screen_fraction: float,
    current_purpose: str = "proxy",
    high_threshold: float = 0.05,
    low_threshold: float = 0.02,
) -> str:
    """Decide which purpose to use based on screen fraction and hysteresis.

    Args:
        screen_fraction: Current screen fraction [0.0, 1.0].
        current_purpose: Current active purpose ("render" or "proxy").
        high_threshold: Switch proxy → render when fraction >= this.
        low_threshold: Switch render → proxy when fraction <= this.

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
