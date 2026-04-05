"""Kit LOD capture — simple deferred exec via omni.kit.app."""
import omni.kit.app
import omni.usd
import os
from pxr import Usd, UsdGeom, Gf

STAGE_PATH = "/home/horde/.openclaw/workspace-lod/demo/lod_demo.usda"
OUTPUT_DIR = "/home/horde/.openclaw/workspace-lod/demo/kit_frames2"
CAMERA_PATH = "/World/Camera"
TOTAL_FRAMES = 60
HIGH_THRESHOLD = 0.15
LOW_THRESHOLD = 0.06

os.makedirs(OUTPUT_DIR, exist_ok=True)

def compute_screen_size(stage, prim_path, camera_path, time):
    prim = stage.GetPrimAtPath(prim_path)
    camera_prim = stage.GetPrimAtPath(camera_path)
    if not prim.IsValid() or not camera_prim.IsValid():
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

def decide_purpose(ss, cur, h, l):
    if cur == "proxy":
        return "render" if ss >= h else "proxy"
    return "proxy" if ss <= l else "render"

# Open stage
ctx = omni.usd.get_context()
ctx.open_stage(STAGE_PATH)
stage = ctx.get_stage()
print(f"Stage opened: {STAGE_PATH}")

sphere_prim = stage.GetPrimAtPath("/World/LODObject/HighDetail")
cube_prim = stage.GetPrimAtPath("/World/LODObject/LowDetail")
current_purpose = "render"

print(f"\n{'Frame':>5} {'ScreenSize':>12} {'Purpose':>8}")
print("-" * 30)

for frame in range(1, TOTAL_FRAMES + 1):
    time = Usd.TimeCode(frame)
    size = compute_screen_size(stage, "/World/LODObject", CAMERA_PATH, time)
    new_purpose = decide_purpose(size, current_purpose, HIGH_THRESHOLD, LOW_THRESHOLD)

    if new_purpose == "render":
        UsdGeom.Imageable(sphere_prim).GetVisibilityAttr().Set(UsdGeom.Tokens.inherited, time)
        UsdGeom.Imageable(cube_prim).GetVisibilityAttr().Set(UsdGeom.Tokens.invisible, time)
    else:
        UsdGeom.Imageable(sphere_prim).GetVisibilityAttr().Set(UsdGeom.Tokens.invisible, time)
        UsdGeom.Imageable(cube_prim).GetVisibilityAttr().Set(UsdGeom.Tokens.inherited, time)

    switched = " SWITCH" if new_purpose != current_purpose else ""
    print(f"{frame:5d} {size:12.4f} {new_purpose:>8}{switched}")
    current_purpose = new_purpose

baked_path = os.path.join(OUTPUT_DIR, "lod_demo_baked.usda")
stage.GetRootLayer().Export(baked_path)
print(f"\nBaked stage: {baked_path}")

omni.kit.app.get_app().post_uncancellable_quit(0)
