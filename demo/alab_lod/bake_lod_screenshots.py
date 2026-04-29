#!/usr/bin/env python3
"""
Create LOD-baked scenes for screenshot comparison.
Simulates hdLod: close = render visible/proxy hidden, far = proxy visible/render hidden.
Uses USD composition to override visibility.
"""

import os
import sys
import json
import subprocess

from pxr import Usd, UsdGeom, Sdf, Gf, Vt

ALAB_ENTRY = '/home/horde/.openclaw/workspace-alab/alab/ALab-2.3.0/ALab/entry.usda'
OVERLAY = '/home/horde/.openclaw/workspace-lod/demo/alab_lod/alab_lod_overlay.usda'
CANDIDATES = '/home/horde/.openclaw/workspace-lod/demo/alab_lod/alab_lod_candidates.json'
OUTDIR = '/home/horde/.openclaw/workspace-lod/demo/alab_lod/screenshots'
USDRECORD = os.path.expanduser('~/builds/usd-lod-install/bin/usdrecord')

os.makedirs(OUTDIR, exist_ok=True)

with open(CANDIDATES) as f:
    candidates = json.load(f)


def create_baked_scene(output_path, show_proxy=False):
    """Create a scene with visibility baked to simulate LOD state."""
    # Use USD API to create the layer properly (avoids text formatting issues)
    stage = Usd.Stage.CreateNew(output_path)
    
    # Set sublayers
    root_layer = stage.GetRootLayer()
    root_layer.subLayerPaths.append(OVERLAY)
    root_layer.subLayerPaths.append(ALAB_ENTRY)
    root_layer.startTimeCode = 1
    root_layer.endTimeCode = 1
    
    # Add camera
    cam = UsdGeom.Camera.Define(stage, '/lod_cam_mid')
    cam.GetFocalLengthAttr().Set(35.0)
    cam.GetHorizontalApertureAttr().Set(36.0)
    cam.GetVerticalApertureAttr().Set(24.0)
    cam.GetClippingRangeAttr().Set(Gf.Vec2f(1, 100000))
    cam.AddTranslateOp().Set((150.0, 120.0, 200.0))
    cam.AddRotateXYZOp().Set((float(-10), float(20), float(0)))
    
    # Override visibility on items
    for cand in candidates:
        proxy_paths = cand.get('proxy', [])
        render_paths = cand.get('render', [])
        
        if show_proxy:
            # Far LOD: hide render items, show proxy
            hidden = render_paths
        else:
            # Close LOD: hide proxy items, show render
            hidden = proxy_paths
        
        for path in hidden:
            prim = stage.OverridePrim(path)
            if prim:
                UsdGeom.Imageable(prim).GetVisibilityAttr().Set('invisible')
    
    stage.Save()
    return output_path


def render(scene_path, camera, output_image, width=1280):
    """Render with usdrecord."""
    env = os.environ.copy()
    env['PYTHONPATH'] = os.path.expanduser('~/builds/usd-lod-install/lib/python') + ':' + env.get('PYTHONPATH', '')
    env['LD_LIBRARY_PATH'] = os.path.expanduser('~/builds/usd-lod-install/lib') + ':' + env.get('LD_LIBRARY_PATH', '')
    env['PXR_PLUGINPATH_NAME'] = os.path.expanduser('~/builds/usd-lod-install/lib/usd')
    env['DISPLAY'] = ':99'
    env['__NV_PRIME_RENDER_OFFLOAD'] = '1'
    env['__GLX_VENDOR_LIBRARY_NAME'] = 'nvidia'
    env['QT_QPA_PLATFORM'] = 'offscreen'

    cmd = [
        'python3', USDRECORD,
        '--defaultTime',
        '--camera', camera,
        '--imageWidth', str(width),
        '--complexity', 'low',
        scene_path,
        output_image,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=180)
    if not os.path.exists(output_image):
        # Print errors for debugging
        for line in result.stderr.split('\n')[-10:]:
            if 'Error' in line or 'error' in line:
                print(f'  ERR: {line[:200]}')
    return os.path.exists(output_image)


def main():
    print("=== LOD-Baked Screenshot Comparison ===")
    print(f"LOD groups: {len(candidates)}")
    print()

    # Create render-visible scene (close-up LOD state)
    print("1. Creating CLOSE LOD scene (render visible, proxy hidden)...")
    close_scene = create_baked_scene(
        os.path.join(OUTDIR, 'baked_close.usda'), show_proxy=False)
    print(f"   Wrote: {close_scene}")

    # Create proxy-visible scene (far LOD state)
    print("2. Creating FAR LOD scene (proxy visible, render hidden)...")
    far_scene = create_baked_scene(
        os.path.join(OUTDIR, 'baked_far.usda'), show_proxy=True)
    print(f"   Wrote: {far_scene}")

    # Render both
    print("3. Rendering CLOSE LOD state...")
    ok1 = render(close_scene, '/lod_cam_mid', os.path.join(OUTDIR, 'lod_close_state.png'))
    print(f"   {'OK' if ok1 else 'FAILED'}")

    print("4. Rendering FAR LOD state...")
    ok2 = render(far_scene, '/lod_cam_mid', os.path.join(OUTDIR, 'lod_far_state.png'))
    print(f"   {'OK' if ok2 else 'FAILED'}")

    # List results
    print("\n=== Results ===")
    for f in sorted(os.listdir(OUTDIR)):
        if f.endswith('.png'):
            path = os.path.join(OUTDIR, f)
            size = os.path.getsize(path)
            print(f"  {f}: {size:,} bytes")


if __name__ == '__main__':
    main()
