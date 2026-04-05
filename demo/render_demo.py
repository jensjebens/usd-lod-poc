"""Create a demo scene with a red sphere (render) and green cube (proxy),
animate a camera dollying out, compute screen_size at each frame,
switch purposes at the threshold, and render with usdrecord.
"""
import os
import sys
import subprocess
import math

USD_ROOT = "/home/horde/.openclaw/workspace-alab/usd-bin/usd-v25.08"
sys.path.insert(0, os.path.join(USD_ROOT, "lib", "python"))
os.environ["LD_LIBRARY_PATH"] = os.path.join(USD_ROOT, "lib") + ":" + os.environ.get("LD_LIBRARY_PATH", "")
os.environ["PATH"] = os.path.join(USD_ROOT, "bin") + ":" + os.environ.get("PATH", "")

from pxr import Usd, UsdGeom, UsdShade, Gf, Sdf, Vt

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from lod_heuristics import compute_screen_size, decide_purpose

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "..", "demo")
os.makedirs(OUTPUT_DIR, exist_ok=True)

TOTAL_FRAMES = 60
START_DISTANCE = 3.0
END_DISTANCE = 40.0
HIGH_THRESHOLD = 0.15
LOW_THRESHOLD = 0.06
IMAGE_WIDTH = 960


def create_material(stage, path, color):
    """Create a simple UsdPreviewSurface material."""
    mat = UsdShade.Material.Define(stage, path)
    shader = UsdShade.Shader.Define(stage, path + "/PBRShader")
    shader.CreateIdAttr("UsdPreviewSurface")
    shader.CreateInput("diffuseColor", Sdf.ValueTypeNames.Color3f).Set(Gf.Vec3f(*color))
    shader.CreateInput("roughness", Sdf.ValueTypeNames.Float).Set(0.4)
    shader.CreateInput("metallic", Sdf.ValueTypeNames.Float).Set(0.0)
    mat.CreateSurfaceOutput().ConnectToSource(shader.ConnectableAPI(), "surface")
    return mat


def build_scene():
    """Build the animated USD scene."""
    scene_path = os.path.join(OUTPUT_DIR, "lod_demo.usda")
    stage = Usd.Stage.CreateNew(scene_path)
    stage.SetStartTimeCode(1)
    stage.SetEndTimeCode(TOTAL_FRAMES)
    UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.y)

    # Root xform
    root = UsdGeom.Xform.Define(stage, "/World")

    # Ground plane for context
    ground = UsdGeom.Cube.Define(stage, "/World/Ground")
    ground.GetSizeAttr().Set(80.0)
    UsdGeom.Xformable(ground.GetPrim()).AddTranslateOp().Set(Gf.Vec3d(0, -40.5, 0))
    ground_mat = create_material(stage, "/World/Materials/GroundMat", (0.3, 0.3, 0.35))
    UsdShade.MaterialBindingAPI(ground.GetPrim()).Bind(ground_mat)

    # --- LOD group: sphere (render) + cube (proxy) ---
    lod_group = UsdGeom.Xform.Define(stage, "/World/LODObject")

    # Red sphere — render purpose (high detail)
    sphere = UsdGeom.Sphere.Define(stage, "/World/LODObject/HighDetail")
    sphere.GetRadiusAttr().Set(1.0)
    img = UsdGeom.Imageable(sphere.GetPrim())
    img.GetPurposeAttr().Set(UsdGeom.Tokens.render)
    red_mat = create_material(stage, "/World/Materials/RedMat", (0.9, 0.15, 0.1))
    UsdShade.MaterialBindingAPI(sphere.GetPrim()).Bind(red_mat)

    # Green cube — proxy purpose (low detail)
    cube = UsdGeom.Cube.Define(stage, "/World/LODObject/LowDetail")
    cube.GetSizeAttr().Set(1.6)
    img_cube = UsdGeom.Imageable(cube.GetPrim())
    img_cube.GetPurposeAttr().Set(UsdGeom.Tokens.proxy)
    green_mat = create_material(stage, "/World/Materials/GreenMat", (0.1, 0.8, 0.2))
    UsdShade.MaterialBindingAPI(cube.GetPrim()).Bind(green_mat)

    # Camera — dolly out over time
    cam = UsdGeom.Camera.Define(stage, "/World/Camera")
    cam.GetFocalLengthAttr().Set(35.0)
    cam.GetHorizontalApertureAttr().Set(36.0)
    cam.GetVerticalApertureAttr().Set(20.25)
    cam.GetClippingRangeAttr().Set(Gf.Vec2f(0.1, 1000.0))

    cam_xform = UsdGeom.Xformable(cam.GetPrim())
    translate_op = cam_xform.AddTranslateOp()

    for frame in range(1, TOTAL_FRAMES + 1):
        t = (frame - 1) / max(1, TOTAL_FRAMES - 1)
        dist = START_DISTANCE + t * (END_DISTANCE - START_DISTANCE)
        # Camera slightly above, looking toward origin
        translate_op.Set(Gf.Vec3d(dist * 0.3, 1.0 + dist * 0.05, dist), Usd.TimeCode(frame))

    stage.GetRootLayer().Save()
    print(f"Scene saved: {scene_path}")
    return scene_path


def render_frames(scene_path):
    """Render each frame, switching purposes based on screen_size."""
    stage = Usd.Stage.Open(scene_path)

    # Track switching state
    current_purpose = "render"  # Start showing the red sphere

    sphere_prim = stage.GetPrimAtPath("/World/LODObject/HighDetail")
    cube_prim = stage.GetPrimAtPath("/World/LODObject/LowDetail")

    frames_dir = os.path.join(OUTPUT_DIR, "frames")
    os.makedirs(frames_dir, exist_ok=True)

    print(f"\n{'Frame':>5} {'Distance':>10} {'ScreenSize':>12} {'Purpose':>8} {'Showing':>12}")
    print("-" * 55)

    for frame in range(1, TOTAL_FRAMES + 1):
        time = Usd.TimeCode(frame)

        # Compute screen size for the LOD group
        size = compute_screen_size(stage, "/World/LODObject", "/World/Camera", time)

        # Decide purpose
        new_purpose = decide_purpose(size, current_purpose, HIGH_THRESHOLD, LOW_THRESHOLD)

        # Apply visibility: show one, hide the other
        sphere_vis = UsdGeom.Imageable(sphere_prim)
        cube_vis = UsdGeom.Imageable(cube_prim)

        if new_purpose == "render":
            sphere_vis.GetVisibilityAttr().Set(UsdGeom.Tokens.inherited, time)
            cube_vis.GetVisibilityAttr().Set(UsdGeom.Tokens.invisible, time)
            showing = "Red Sphere"
        else:
            sphere_vis.GetVisibilityAttr().Set(UsdGeom.Tokens.invisible, time)
            cube_vis.GetVisibilityAttr().Set(UsdGeom.Tokens.inherited, time)
            showing = "Green Cube"

        # Get camera distance for display
        cam = UsdGeom.Camera(stage.GetPrimAtPath("/World/Camera"))
        gf_cam = cam.GetCamera(time)
        eye = gf_cam.frustum.GetPosition()
        dist = eye.GetLength()

        switched = " ← SWITCH" if new_purpose != current_purpose else ""
        print(f"{frame:5d} {dist:10.2f} {size:12.4f} {new_purpose:>8} {showing:>12}{switched}")

        current_purpose = new_purpose

    # Save the modified stage with visibility keyframes
    stage.GetRootLayer().Save()

    # Render with usdrecord — render purpose first, then proxy
    # We use --purposes to control which geometry shows
    # Actually, since we set visibility per-frame, we can render with both purposes
    env = os.environ.copy()
    env["DISPLAY"] = ":99"
    env["__NV_PRIME_RENDER_OFFLOAD"] = "1"
    env["__GLX_VENDOR_LIBRARY_NAME"] = "nvidia"

    out_pattern = os.path.join(frames_dir, "frame.####.png")

    cmd = [
        "usdrecord",
        "--camera", "/World/Camera",
        "--frames", f"1:{TOTAL_FRAMES}",
        "--imageWidth", str(IMAGE_WIDTH),
        "--purposes", "render,proxy",
        "--renderer", "Storm",
        scene_path,
        out_pattern,
    ]

    print(f"\nRendering {TOTAL_FRAMES} frames with usdrecord...")
    print(f"  Command: {' '.join(cmd)}")
    result = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=300)

    if result.returncode != 0:
        print(f"usdrecord stderr:\n{result.stderr}")
        raise RuntimeError(f"usdrecord failed with code {result.returncode}")

    print("Render complete.")
    return frames_dir


def make_gif(frames_dir):
    """Stitch frames into a GIF using ffmpeg."""
    gif_path = os.path.join(OUTPUT_DIR, "lod_demo.gif")

    # ffmpeg: input PNGs → GIF with palette for quality
    palette_cmd = [
        "ffmpeg", "-y",
        "-framerate", "24",
        "-i", os.path.join(frames_dir, "frame.%04d.png"),
        "-vf", "fps=24,scale=480:-1:flags=lanczos,palettegen",
        os.path.join(frames_dir, "palette.png"),
    ]

    gif_cmd = [
        "ffmpeg", "-y",
        "-framerate", "24",
        "-i", os.path.join(frames_dir, "frame.%04d.png"),
        "-i", os.path.join(frames_dir, "palette.png"),
        "-lavfi", "fps=24,scale=480:-1:flags=lanczos[x];[x][1:v]paletteuse",
        gif_path,
    ]

    print("\nCreating GIF...")
    subprocess.run(palette_cmd, capture_output=True, text=True, timeout=60)
    result = subprocess.run(gif_cmd, capture_output=True, text=True, timeout=60)

    if result.returncode != 0:
        print(f"ffmpeg stderr:\n{result.stderr}")
        raise RuntimeError("ffmpeg GIF creation failed")

    size_kb = os.path.getsize(gif_path) / 1024
    print(f"GIF saved: {gif_path} ({size_kb:.0f} KB)")
    return gif_path


if __name__ == "__main__":
    scene = build_scene()
    frames = render_frames(scene)
    gif = make_gif(frames)
    print(f"\nDone! GIF: {gif}")
