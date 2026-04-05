"""Kit headless capture script for LOD switching demo.

Uses Kit's Python env to iterate frames, compute screen_size, 
toggle visibility, then render via UsdImagingGL.Engine (Hydra Storm).
"""
import os
import sys
import math

# Kit provides pxr
from pxr import Usd, UsdGeom, UsdShade, Gf, Sdf, UsdImagingGL, CameraUtil

import omni.kit.app

STAGE_PATH = "/home/horde/.openclaw/workspace-lod/demo/lod_demo.usda"
OUTPUT_DIR = "/home/horde/.openclaw/workspace-lod/demo/kit_frames"
CAMERA_PATH = "/World/Camera"
TOTAL_FRAMES = 60
HIGH_THRESHOLD = 0.15
LOW_THRESHOLD = 0.06
IMAGE_WIDTH = 960
IMAGE_HEIGHT = 540


def compute_screen_size(stage, prim_path, camera_path, time):
    """Bounding sphere screen size ratio (radius / distance)."""
    prim = stage.GetPrimAtPath(prim_path)
    if not prim.IsValid():
        return 0.0
    camera_prim = stage.GetPrimAtPath(camera_path)
    if not camera_prim.IsValid():
        return 0.0

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

    usd_camera = UsdGeom.Camera(camera_prim)
    gf_camera = usd_camera.GetCamera(time)
    eye = gf_camera.frustum.GetPosition()
    distance = (centre - eye).GetLength()

    if distance <= radius:
        return 1.0
    return min(1.0, radius / distance)


def decide_purpose(screen_size, current_purpose, high_threshold, low_threshold):
    """Hysteresis-based purpose decision."""
    if current_purpose == "proxy":
        if screen_size >= high_threshold:
            return "render"
        return "proxy"
    else:
        if screen_size <= low_threshold:
            return "proxy"
        return "render"


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    stage = Usd.Stage.Open(STAGE_PATH)
    if not stage:
        print(f"ERROR: Cannot open stage {STAGE_PATH}")
        omni.kit.app.get_app().post_uncancellable_quit(1)
        return

    # Check if UsdImagingGL is available for rendering
    try:
        engine = UsdImagingGL.Engine()
        print("UsdImagingGL.Engine created — Storm rendering available")
        has_engine = True
    except Exception as e:
        print(f"UsdImagingGL.Engine not available: {e}")
        has_engine = False

    sphere_prim = stage.GetPrimAtPath("/World/LODObject/HighDetail")
    cube_prim = stage.GetPrimAtPath("/World/LODObject/LowDetail")
    current_purpose = "render"

    print(f"\n{'Frame':>5} {'ScreenSize':>12} {'Purpose':>8}")
    print("-" * 30)

    for frame in range(1, TOTAL_FRAMES + 1):
        time = Usd.TimeCode(frame)

        size = compute_screen_size(stage, "/World/LODObject", CAMERA_PATH, time)
        new_purpose = decide_purpose(size, current_purpose, HIGH_THRESHOLD, LOW_THRESHOLD)

        sphere_vis = UsdGeom.Imageable(sphere_prim)
        cube_vis = UsdGeom.Imageable(cube_prim)

        if new_purpose == "render":
            sphere_vis.GetVisibilityAttr().Set(UsdGeom.Tokens.inherited, time)
            cube_vis.GetVisibilityAttr().Set(UsdGeom.Tokens.invisible, time)
        else:
            sphere_vis.GetVisibilityAttr().Set(UsdGeom.Tokens.invisible, time)
            cube_vis.GetVisibilityAttr().Set(UsdGeom.Tokens.inherited, time)

        switched = " SWITCH" if new_purpose != current_purpose else ""
        print(f"{frame:5d} {size:12.4f} {new_purpose:>8}{switched}")
        current_purpose = new_purpose

    # Save baked stage for usdrecord
    baked_path = os.path.join(OUTPUT_DIR, "lod_demo_baked.usda")
    stage.GetRootLayer().Export(baked_path)
    print(f"\nBaked stage saved: {baked_path}")
    print("Use usdrecord to render frames from the baked stage.")

    omni.kit.app.get_app().post_uncancellable_quit(0)


main()
