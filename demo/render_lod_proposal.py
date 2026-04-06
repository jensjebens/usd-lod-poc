"""
render_lod_demo.py — LOD Proposal POC: Animated demo renderer

Creates a sample stage with a 3-level LOD object, evaluates LOD
per frame as camera dollies out, and renders with usdrecord (Storm).

Usage:
    python3 render_lod_demo.py

Output:
    demo/lod_proposal_demo.gif
"""

import os
import sys
import subprocess
import math

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from pxr import Usd, UsdGeom, Sdf, Gf, Vt
from usd_lod import LodGroupAPI, LodItemAPI, LodDistanceHeuristicAPI
from lod_evaluator import evaluate_lod, apply_lod_visibility


# -- Config --
NUM_FRAMES = 100
CAM_START = Gf.Vec3d(0, 1.5, 3)
CAM_END = Gf.Vec3d(0, 3, 45)
IMAGE_WIDTH = 960

# Distance thresholds (min/max for hysteresis)
DIST_MIN = [8.0, 20.0]   # switch to Mid at 8, Low at 20
DIST_MAX = [10.0, 22.0]  # switch back to High at 10, Mid at 22

USD_ROOT = os.environ.get('USD_ROOT', '/tmp/usd-purpose-vis-build')
DEMO_DIR = os.path.join(os.path.dirname(__file__), '..', 'demo')
FRAMES_DIR = os.path.join(DEMO_DIR, 'lod_frames')
SCENE_PATH = os.path.join(DEMO_DIR, 'lod_proposal_scene.usda')
OUTPUT_GIF = os.path.join(DEMO_DIR, 'lod_proposal_demo.gif')


def create_scene():
    """Create the LOD demo stage."""
    stage = Usd.Stage.CreateNew(SCENE_PATH)
    stage.SetMetadata('upAxis', 'Y')
    stage.SetStartTimeCode(1)
    stage.SetEndTimeCode(NUM_FRAMES)

    # Ground
    ground = UsdGeom.Cube.Define(stage, '/World/Ground')
    ground.GetSizeAttr().Set(30.0)
    ground.AddTranslateOp().Set(Gf.Vec3d(0, -0.15, 0))
    ground.AddScaleOp().Set(Gf.Vec3f(1, 0.01, 0.5))
    ground_mat = _create_material(stage, '/World/Materials/GroundMat', (0.35, 0.35, 0.4))
    UsdGeom.Gprim(ground).GetPrim().ApplyAPI(UsdGeom.Tokens.MaterialBindingAPI if hasattr(UsdGeom.Tokens, 'MaterialBindingAPI') else 'MaterialBindingAPI')
    ground.GetPrim().CreateRelationship('material:binding').SetTargets([Sdf.Path('/World/Materials/GroundMat')])

    # -- LOD Group: /World/Object --
    obj = stage.DefinePrim('/World/Object', 'Xform')
    group = LodGroupAPI.Apply(stage, obj.GetPath())

    # High detail: Sphere (red)
    high = UsdGeom.Sphere.Define(stage, '/World/Object/High')
    high.GetRadiusAttr().Set(0.8)
    high.AddTranslateOp().Set(Gf.Vec3d(0, 0.8, 0))
    LodItemAPI.Apply(stage, high.GetPrim().GetPath())
    high_mat = _create_material(stage, '/World/Materials/RedMat', (0.9, 0.15, 0.1))
    high.GetPrim().CreateRelationship('material:binding').SetTargets([Sdf.Path('/World/Materials/RedMat')])

    # Mid detail: Cylinder-ish (green) — use a cube scaled to approximate
    mid = UsdGeom.Cube.Define(stage, '/World/Object/Mid')
    mid.GetSizeAttr().Set(1.3)
    mid.AddTranslateOp().Set(Gf.Vec3d(0, 0.65, 0))
    LodItemAPI.Apply(stage, mid.GetPrim().GetPath())
    mid_mat = _create_material(stage, '/World/Materials/GreenMat', (0.1, 0.8, 0.2))
    mid.GetPrim().CreateRelationship('material:binding').SetTargets([Sdf.Path('/World/Materials/GreenMat')])

    # Low detail: small cube (blue)
    low = UsdGeom.Cube.Define(stage, '/World/Object/Low')
    low.GetSizeAttr().Set(1.0)
    low.AddTranslateOp().Set(Gf.Vec3d(0, 0.5, 0))
    LodItemAPI.Apply(stage, low.GetPrim().GetPath())
    low_mat = _create_material(stage, '/World/Materials/BlueMat', (0.2, 0.4, 0.9))
    low.GetPrim().CreateRelationship('material:binding').SetTargets([Sdf.Path('/World/Materials/BlueMat')])

    # Set LOD items (high → low)
    group.SetLodItems([
        high.GetPrim().GetPath(),
        mid.GetPrim().GetPath(),
        low.GetPrim().GetPath(),
    ])

    # Distance heuristic
    heuristic = LodDistanceHeuristicAPI.Apply(stage, obj.GetPath(), 'graphics')
    heuristic.SetDistanceMinThresholds(DIST_MIN)
    heuristic.SetDistanceMaxThresholds(DIST_MAX)

    # Camera with animated position
    cam = UsdGeom.Camera.Define(stage, '/World/Camera')
    cam.GetClippingRangeAttr().Set(Gf.Vec2f(0.1, 200))
    cam.GetFocalLengthAttr().Set(35.0)
    cam.GetHorizontalApertureAttr().Set(36.0)
    cam.GetVerticalApertureAttr().Set(20.25)

    translate_op = cam.AddTranslateOp()
    rotate_op = cam.AddRotateXYZOp()

    for f in range(1, NUM_FRAMES + 1):
        t = (f - 1) / (NUM_FRAMES - 1)
        pos = CAM_START + (CAM_END - CAM_START) * t
        translate_op.Set(pos, Usd.TimeCode(f))
        # Slight downward look
        pitch = -5.0 - t * 5.0
        rotate_op.Set(Gf.Vec3f(pitch, 0, 0), Usd.TimeCode(f))

    stage.Save()
    print(f"Scene saved: {SCENE_PATH}")
    return stage


def _create_material(stage, path, color):
    """Create a simple UsdPreviewSurface material."""
    mat = stage.DefinePrim(path, 'Material')
    shader = stage.DefinePrim(f'{path}/Shader', 'Shader')
    shader.CreateAttribute('info:id', Sdf.ValueTypeNames.Token).Set('UsdPreviewSurface')
    shader.CreateAttribute('inputs:diffuseColor', Sdf.ValueTypeNames.Color3f).Set(
        Gf.Vec3f(*color)
    )
    shader.CreateAttribute('inputs:roughness', Sdf.ValueTypeNames.Float).Set(0.4)
    shader.CreateAttribute('outputs:surface', Sdf.ValueTypeNames.Token)
    mat.CreateRelationship('outputs:surface').SetTargets(
        [Sdf.Path(f'{path}/Shader.outputs:surface')]
    )
    return mat


def render_frames(stage):
    """Evaluate LOD per frame, set visibility, render with usdrecord."""
    os.makedirs(FRAMES_DIR, exist_ok=True)

    usdrecord = os.path.join(USD_ROOT, 'bin', 'usdrecord')
    env = os.environ.copy()
    env['DISPLAY'] = ':99'
    env['__NV_PRIME_RENDER_OFFLOAD'] = '1'
    env['__GLX_VENDOR_LIBRARY_NAME'] = 'nvidia'
    env['LD_LIBRARY_PATH'] = f"{USD_ROOT}/lib:{env.get('LD_LIBRARY_PATH', '')}"
    env['PYTHONPATH'] = f"{USD_ROOT}/lib/python:{env.get('PYTHONPATH', '')}"

    prev_state = None
    lod_labels = ['High (Sphere)', 'Mid (Cube)', 'Low (Small Cube)']
    lod_colors = ['red', 'green', 'blue']

    frame_info = []

    for f in range(1, NUM_FRAMES + 1):
        tc = Usd.TimeCode(f)
        t = (f - 1) / (NUM_FRAMES - 1)

        # Get camera position at this frame
        cam = UsdGeom.Camera.Get(stage, '/World/Camera')
        xform = UsdGeom.Xformable(cam)
        cam_pos = Gf.Vec3d(0, 0, 0)
        # Read the translate value at this time code
        for op in xform.GetOrderedXformOps():
            if op.GetOpType() == UsdGeom.XformOp.TypeTranslate:
                cam_pos = Gf.Vec3d(op.Get(tc))
                break

        # Evaluate LOD
        result = evaluate_lod(stage, camera_pos=cam_pos, prev_state=prev_state)
        apply_lod_visibility(stage, result)
        prev_state = result

        # Save stage for this frame
        stage.Save()

        active_idx = result.get(Sdf.Path('/World/Object'), 0)
        distance = cam_pos.GetLength()  # object at origin
        frame_info.append((f, distance, active_idx, lod_labels[active_idx]))

        # Render
        frame_path = os.path.join(FRAMES_DIR, f'frame_{f:04d}.png')
        cmd = [
            'python3', usdrecord,
            '--frames', f'{f}:{f}',
            '--camera', '/World/Camera',
            '--renderer', 'Storm',
            '--purposes', 'render,proxy',
            '--imageWidth', str(IMAGE_WIDTH),
            '--complexity', 'high',
            SCENE_PATH,
            os.path.join(FRAMES_DIR, 'frame_####.png'),
        ]
        subprocess.run(cmd, env=env, capture_output=True, timeout=30)

        if f % 10 == 0 or f == 1:
            print(f"  Frame {f:3d}/{NUM_FRAMES}: dist={distance:.1f}, LOD={lod_labels[active_idx]}")

    return frame_info


def annotate_and_gif(frame_info):
    """Add LOD labels to frames and create GIF."""
    from PIL import Image, ImageDraw, ImageFont

    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 16)
        small_font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 14)
    except:
        font = ImageFont.load_default()
        small_font = font

    frames = []
    lod_bar_colors = {
        0: (220, 50, 40),    # red for high
        1: (40, 180, 60),    # green for mid
        2: (50, 100, 220),   # blue for low
    }

    for f_num, dist, active_idx, label in frame_info:
        path = os.path.join(FRAMES_DIR, f'frame_{f_num:04d}.png')
        if not os.path.exists(path):
            continue

        img = Image.open(path).convert('RGB')
        draw = ImageDraw.Draw(img)

        # Top bar with LOD info
        bar_color = lod_bar_colors.get(active_idx, (60, 60, 60))
        draw.rectangle([(0, 0), (img.width, 32)], fill=(*bar_color, 220))

        text = f"LOD: {label}  |  Distance: {dist:.1f}  |  Frame {f_num}"
        bbox = draw.textbbox((0, 0), text, font=font)
        text_w = bbox[2] - bbox[0]
        x = (img.width - text_w) // 2
        draw.text((x, 7), text, fill=(255, 255, 255), font=font)

        # Threshold indicators
        info = f"Thresholds: High<{DIST_MIN[0]} | Mid {DIST_MIN[0]}-{DIST_MIN[1]} | Low>{DIST_MIN[1]}"
        draw.text((10, img.height - 22), info, fill=(200, 200, 200), font=small_font)

        frames.append(img)

    if not frames:
        print("No frames to create GIF!")
        return

    # Create GIF — 24fps = ~42ms per frame
    frames[0].save(
        OUTPUT_GIF,
        save_all=True,
        append_images=frames[1:],
        duration=42,
        loop=0,
        optimize=True,
    )
    print(f"GIF saved: {OUTPUT_GIF} ({len(frames)} frames)")


if __name__ == '__main__':
    print("=== LOD Proposal POC Demo ===")
    print(f"USD_ROOT: {USD_ROOT}")
    print(f"Frames: {NUM_FRAMES}, Camera: {CAM_START} → {CAM_END}")
    print(f"Thresholds (min): {DIST_MIN}, (max): {DIST_MAX}")
    print()

    print("1. Creating scene...")
    stage = create_scene()

    print("2. Rendering frames...")
    frame_info = render_frames(stage)

    print("3. Creating annotated GIF...")
    annotate_and_gif(frame_info)

    # Print LOD switch points
    print("\n=== LOD Transitions ===")
    prev_idx = None
    for f, dist, idx, label in frame_info:
        if idx != prev_idx:
            print(f"  Frame {f:3d} (dist {dist:.1f}): → {label}")
            prev_idx = idx

    print("\nDone!")
