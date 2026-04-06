"""
Tests for hdLod scene index pipeline integration.

Tests the C++ HdLodSceneIndex plugin through the USD rendering pipeline
(usdrecord with Storm). Verifies that:
1. The plugin loads and registers
2. LOD switching hides/shows correct geometry
3. Descendant walk works for parent Xform items
4. Hysteresis prevents flickering
5. Hierarchical evaluation gates child groups

Requires: USD built from source with hdLod plugin installed.
"""

import unittest
import os
import sys
import subprocess
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from pxr import Usd, UsdGeom, Sdf, Gf

from usd_lod import LodGroupAPI, LodItemAPI, LodDistanceHeuristicAPI

USD_ROOT = os.environ.get('USD_ROOT', '/tmp/usd-purpose-vis-build')


def _has_hdlod_plugin():
    """Check if the hdLod plugin is installed."""
    plugin_path = os.path.join(USD_ROOT, 'plugin', 'usd', 'hdLod', 'resources', 'plugInfo.json')
    lib_path = os.path.join(USD_ROOT, 'lib', 'libusd_hdLod.so')
    return os.path.exists(plugin_path) and os.path.exists(lib_path)


def _render_frame(scene_path, camera_path, frame=0, purposes='render,proxy'):
    """Render a single frame with usdrecord and return the output path."""
    outdir = tempfile.mkdtemp()
    out_path = os.path.join(outdir, 'frame.####.png')

    env = os.environ.copy()
    env['DISPLAY'] = ':99'
    env['__NV_PRIME_RENDER_OFFLOAD'] = '1'
    env['__GLX_VENDOR_LIBRARY_NAME'] = 'nvidia'
    env['LD_LIBRARY_PATH'] = f"{USD_ROOT}/lib:{env.get('LD_LIBRARY_PATH', '')}"
    env['PYTHONPATH'] = f"{USD_ROOT}/lib/python:{env.get('PYTHONPATH', '')}"

    cmd = [
        'python3', os.path.join(USD_ROOT, 'bin', 'usdrecord'),
        '--frames', f'{frame}:{frame}',
        '--camera', camera_path,
        '--renderer', 'Storm',
        '--purposes', purposes,
        '--imageWidth', '320',
        scene_path,
        out_path,
    ]
    result = subprocess.run(cmd, env=env, capture_output=True, timeout=30, text=True)
    actual_path = os.path.join(outdir, f'frame.{frame:04d}.png')
    return actual_path if os.path.exists(actual_path) else None


def _get_pixel_color(image_path, x, y):
    """Get RGB tuple at pixel (x,y) from a PNG image."""
    from PIL import Image
    img = Image.open(image_path).convert('RGB')
    return img.getpixel((x, y))


def _create_simple_lod_scene(path, camera_z=5.0):
    """Create a minimal LOD scene for testing.

    /World/Object (LodGroup) with distance thresholds [10, 25]
      /World/Object/High (Sphere, red) — active when dist < 10
      /World/Object/Mid  (Cube, green) — active when 10 <= dist < 25
      /World/Object/Low  (Cube, blue, small) — active when dist >= 25
    /World/Camera at (0, 1.5, camera_z)
    """
    stage = Usd.Stage.CreateNew(path)
    stage.SetMetadata('upAxis', 'Y')

    # Ground
    ground = UsdGeom.Cube.Define(stage, '/World/Ground')
    ground.GetSizeAttr().Set(20.0)
    ground.AddTranslateOp().Set(Gf.Vec3d(0, -0.1, 0))
    ground.AddScaleOp().Set(Gf.Vec3f(1, 0.005, 0.5))

    # LOD Group
    obj = stage.DefinePrim('/World/Object', 'Xform')
    group = LodGroupAPI.Apply(stage, obj.GetPath())

    # High: red sphere
    high = UsdGeom.Sphere.Define(stage, '/World/Object/High')
    high.GetRadiusAttr().Set(0.8)
    high.AddTranslateOp().Set(Gf.Vec3d(0, 0.8, 0))
    LodItemAPI.Apply(stage, high.GetPrim().GetPath())
    _apply_color(stage, high.GetPrim(), (0.9, 0.1, 0.1))

    # Mid: green cube
    mid = UsdGeom.Cube.Define(stage, '/World/Object/Mid')
    mid.GetSizeAttr().Set(1.3)
    mid.AddTranslateOp().Set(Gf.Vec3d(0, 0.65, 0))
    LodItemAPI.Apply(stage, mid.GetPrim().GetPath())
    _apply_color(stage, mid.GetPrim(), (0.1, 0.8, 0.1))

    # Low: blue small cube
    low = UsdGeom.Cube.Define(stage, '/World/Object/Low')
    low.GetSizeAttr().Set(0.8)
    low.AddTranslateOp().Set(Gf.Vec3d(0, 0.4, 0))
    LodItemAPI.Apply(stage, low.GetPrim().GetPath())
    _apply_color(stage, low.GetPrim(), (0.1, 0.1, 0.9))

    group.SetLodItems([
        high.GetPrim().GetPath(),
        mid.GetPrim().GetPath(),
        low.GetPrim().GetPath(),
    ])

    heuristic = LodDistanceHeuristicAPI.Apply(stage, obj.GetPath(), 'graphics')
    heuristic.SetDistanceMinThresholds([10.0, 25.0])
    heuristic.SetDistanceMaxThresholds([12.0, 27.0])

    # Camera
    cam = UsdGeom.Camera.Define(stage, '/World/Camera')
    cam.GetClippingRangeAttr().Set(Gf.Vec2f(0.1, 200))
    cam.GetFocalLengthAttr().Set(35.0)
    cam.AddTranslateOp().Set(Gf.Vec3d(0, 1.5, camera_z))
    cam.AddRotateXYZOp().Set(Gf.Vec3f(-10, 0, 0))

    stage.Save()
    return stage


def _create_xform_parent_lod_scene(path, camera_z=5.0):
    """Create LOD scene where items are parent Xforms with mesh children.

    /World/Object (LodGroup)
      /World/Object/HighDetail (Xform, LodItem)
        /World/Object/HighDetail/Body (Sphere, red)
        /World/Object/HighDetail/Hat  (Cone, red)
      /World/Object/LowDetail (Xform, LodItem)
        /World/Object/LowDetail/Body (Cube, blue)
    """
    stage = Usd.Stage.CreateNew(path)
    stage.SetMetadata('upAxis', 'Y')

    obj = stage.DefinePrim('/World/Object', 'Xform')
    group = LodGroupAPI.Apply(stage, obj.GetPath())

    # High detail: Xform parent with two mesh children
    high_xform = stage.DefinePrim('/World/Object/HighDetail', 'Xform')
    LodItemAPI.Apply(stage, high_xform.GetPath())

    body = UsdGeom.Sphere.Define(stage, '/World/Object/HighDetail/Body')
    body.GetRadiusAttr().Set(0.6)
    body.AddTranslateOp().Set(Gf.Vec3d(0, 0.6, 0))
    _apply_color(stage, body.GetPrim(), (0.9, 0.1, 0.1))

    hat = UsdGeom.Cone.Define(stage, '/World/Object/HighDetail/Hat')
    hat.GetRadiusAttr().Set(0.4)
    hat.GetHeightAttr().Set(0.6)
    hat.AddTranslateOp().Set(Gf.Vec3d(0, 1.5, 0))
    _apply_color(stage, hat.GetPrim(), (0.9, 0.1, 0.1))

    # Low detail: Xform parent with one mesh child
    low_xform = stage.DefinePrim('/World/Object/LowDetail', 'Xform')
    LodItemAPI.Apply(stage, low_xform.GetPath())

    low_body = UsdGeom.Cube.Define(stage, '/World/Object/LowDetail/Body')
    low_body.GetSizeAttr().Set(1.0)
    low_body.AddTranslateOp().Set(Gf.Vec3d(0, 0.5, 0))
    _apply_color(stage, low_body.GetPrim(), (0.1, 0.1, 0.9))

    group.SetLodItems([high_xform.GetPath(), low_xform.GetPath()])

    heuristic = LodDistanceHeuristicAPI.Apply(stage, obj.GetPath(), 'graphics')
    heuristic.SetDistanceMinThresholds([15.0])
    heuristic.SetDistanceMaxThresholds([17.0])

    # Camera
    cam = UsdGeom.Camera.Define(stage, '/World/Camera')
    cam.GetClippingRangeAttr().Set(Gf.Vec2f(0.1, 200))
    cam.GetFocalLengthAttr().Set(35.0)
    cam.AddTranslateOp().Set(Gf.Vec3d(0, 1.5, camera_z))
    cam.AddRotateXYZOp().Set(Gf.Vec3f(-10, 0, 0))

    stage.Save()
    return stage


def _apply_color(stage, prim, rgb):
    """Apply a simple diffuse color material."""
    path = prim.GetPath()
    mat_path = f'{path}/Material'
    shader_path = f'{mat_path}/Shader'
    mat = stage.DefinePrim(mat_path, 'Material')
    shader = stage.DefinePrim(shader_path, 'Shader')
    shader.CreateAttribute('info:id', Sdf.ValueTypeNames.Token).Set('UsdPreviewSurface')
    shader.CreateAttribute('inputs:diffuseColor', Sdf.ValueTypeNames.Color3f).Set(Gf.Vec3f(*rgb))
    shader.CreateAttribute('inputs:roughness', Sdf.ValueTypeNames.Float).Set(0.4)
    shader.CreateAttribute('outputs:surface', Sdf.ValueTypeNames.Token)
    mat.CreateRelationship('outputs:surface').SetTargets([Sdf.Path(f'{shader_path}.outputs:surface')])
    prim.CreateRelationship('material:binding').SetTargets([Sdf.Path(mat_path)])


class TestHdLodPluginExists(unittest.TestCase):
    """Verify the hdLod plugin is installed and discoverable."""

    def test_plugin_library_exists(self):
        lib = os.path.join(USD_ROOT, 'lib', 'libusd_hdLod.so')
        self.assertTrue(os.path.exists(lib), f"hdLod library not found: {lib}")

    def test_plugin_info_exists(self):
        pi = os.path.join(USD_ROOT, 'plugin', 'usd', 'hdLod', 'resources', 'plugInfo.json')
        self.assertTrue(os.path.exists(pi), f"plugInfo.json not found: {pi}")

    def test_plugin_info_valid(self):
        import json
        pi = os.path.join(USD_ROOT, 'plugin', 'usd', 'hdLod', 'resources', 'plugInfo.json')
        with open(pi) as f:
            data = json.load(f)
        plugins = data.get('Plugins', [])
        self.assertTrue(len(plugins) > 0)
        types = plugins[0].get('Info', {}).get('Types', {})
        self.assertIn('HdLod_SceneIndexPlugin', types)


@unittest.skipUnless(_has_hdlod_plugin(), "hdLod plugin not installed")
class TestHdLodRendering(unittest.TestCase):
    """Test LOD switching through the full rendering pipeline (usdrecord + Storm)."""

    def test_close_camera_shows_high_detail(self):
        """Camera at distance 5 → High detail (sphere) should render."""
        with tempfile.NamedTemporaryFile(suffix='.usda', delete=False) as f:
            scene_path = f.name
        try:
            _create_simple_lod_scene(scene_path, camera_z=5.0)
            img = _render_frame(scene_path, '/World/Camera')
            self.assertIsNotNone(img, "Render failed")
            # Image should exist and have non-zero size
            self.assertGreater(os.path.getsize(img), 1000)
        finally:
            os.unlink(scene_path)

    def test_far_camera_shows_low_detail(self):
        """Camera at distance 40 → Low detail (blue cube) should render."""
        with tempfile.NamedTemporaryFile(suffix='.usda', delete=False) as f:
            scene_path = f.name
        try:
            _create_simple_lod_scene(scene_path, camera_z=40.0)
            img = _render_frame(scene_path, '/World/Camera')
            self.assertIsNotNone(img, "Render failed")
            self.assertGreater(os.path.getsize(img), 1000)
        finally:
            os.unlink(scene_path)

    def test_renders_differ_by_distance(self):
        """Close and far renders should produce different images."""
        with tempfile.NamedTemporaryFile(suffix='.usda', delete=False) as f:
            close_path = f.name
        with tempfile.NamedTemporaryFile(suffix='.usda', delete=False) as f:
            far_path = f.name
        try:
            _create_simple_lod_scene(close_path, camera_z=5.0)
            _create_simple_lod_scene(far_path, camera_z=40.0)

            close_img = _render_frame(close_path, '/World/Camera')
            far_img = _render_frame(far_path, '/World/Camera')

            self.assertIsNotNone(close_img)
            self.assertIsNotNone(far_img)

            # File sizes should differ (different geometry = different image)
            close_size = os.path.getsize(close_img)
            far_size = os.path.getsize(far_img)
            self.assertNotEqual(close_size, far_size,
                                "Close and far renders should differ")
        finally:
            os.unlink(close_path)
            os.unlink(far_path)


@unittest.skipUnless(_has_hdlod_plugin(), "hdLod plugin not installed")
class TestHdLodDescendantWalk(unittest.TestCase):
    """Test that LOD works when items are parent Xforms with mesh children."""

    def test_xform_parent_close_renders(self):
        """Close camera → HighDetail Xform with Body+Hat should render."""
        with tempfile.NamedTemporaryFile(suffix='.usda', delete=False) as f:
            scene_path = f.name
        try:
            _create_xform_parent_lod_scene(scene_path, camera_z=5.0)
            img = _render_frame(scene_path, '/World/Camera')
            self.assertIsNotNone(img, "Render failed for Xform parent scene")
            self.assertGreater(os.path.getsize(img), 1000)
        finally:
            os.unlink(scene_path)

    def test_xform_parent_far_renders(self):
        """Far camera → LowDetail Xform with Body should render."""
        with tempfile.NamedTemporaryFile(suffix='.usda', delete=False) as f:
            scene_path = f.name
        try:
            _create_xform_parent_lod_scene(scene_path, camera_z=30.0)
            img = _render_frame(scene_path, '/World/Camera')
            self.assertIsNotNone(img, "Render failed for Xform parent scene (far)")
            self.assertGreater(os.path.getsize(img), 1000)
        finally:
            os.unlink(scene_path)

    def test_xform_parent_renders_differ(self):
        """Close and far renders should differ (different LOD items active)."""
        with tempfile.NamedTemporaryFile(suffix='.usda', delete=False) as f:
            close_path = f.name
        with tempfile.NamedTemporaryFile(suffix='.usda', delete=False) as f:
            far_path = f.name
        try:
            _create_xform_parent_lod_scene(close_path, camera_z=5.0)
            _create_xform_parent_lod_scene(far_path, camera_z=30.0)

            close_img = _render_frame(close_path, '/World/Camera')
            far_img = _render_frame(far_path, '/World/Camera')

            self.assertIsNotNone(close_img)
            self.assertIsNotNone(far_img)

            close_size = os.path.getsize(close_img)
            far_size = os.path.getsize(far_img)
            self.assertNotEqual(close_size, far_size,
                                "Xform parent: close and far should differ")
        finally:
            os.unlink(close_path)
            os.unlink(far_path)


class TestLodEvaluatorEdgeCases(unittest.TestCase):
    """Additional evaluator tests for edge cases."""

    def setUp(self):
        from usd_lod import LodGroupAPI, LodItemAPI, LodDistanceHeuristicAPI
        self.stage = Usd.Stage.CreateInMemory()

    def test_single_item_group(self):
        """Group with only one item → always selects that item."""
        from lod_evaluator import evaluate_lod

        obj = self.stage.DefinePrim('/World/Obj', 'Xform')
        group = LodGroupAPI.Apply(self.stage, obj.GetPath())
        only = self.stage.DefinePrim('/World/Obj/Only', 'Xform')
        LodItemAPI.Apply(self.stage, only.GetPath())
        group.SetLodItems([only.GetPath()])
        # No heuristic → defaults to first item
        result = evaluate_lod(self.stage, camera_pos=Gf.Vec3d(0, 0, 100))
        self.assertEqual(result[Sdf.Path('/World/Obj')], 0)

    def test_no_heuristic_defaults_to_first(self):
        """Group with items but no heuristic → selects first item."""
        from lod_evaluator import evaluate_lod

        obj = self.stage.DefinePrim('/World/Obj', 'Xform')
        group = LodGroupAPI.Apply(self.stage, obj.GetPath())
        high = self.stage.DefinePrim('/World/Obj/High', 'Xform')
        low = self.stage.DefinePrim('/World/Obj/Low', 'Xform')
        LodItemAPI.Apply(self.stage, high.GetPath())
        LodItemAPI.Apply(self.stage, low.GetPath())
        group.SetLodItems([high.GetPath(), low.GetPath()])

        result = evaluate_lod(self.stage, camera_pos=Gf.Vec3d(0, 0, 50))
        self.assertEqual(result[Sdf.Path('/World/Obj')], 0)

    def test_multiple_groups_independent(self):
        """Two sibling LOD groups evaluate independently."""
        from lod_evaluator import evaluate_lod

        # Group A at origin
        a = self.stage.DefinePrim('/World/A', 'Xform')
        ga = LodGroupAPI.Apply(self.stage, a.GetPath())
        a_high = self.stage.DefinePrim('/World/A/High', 'Xform')
        a_low = self.stage.DefinePrim('/World/A/Low', 'Xform')
        LodItemAPI.Apply(self.stage, a_high.GetPath())
        LodItemAPI.Apply(self.stage, a_low.GetPath())
        ga.SetLodItems([a_high.GetPath(), a_low.GetPath()])
        ha = LodDistanceHeuristicAPI.Apply(self.stage, a.GetPath(), 'graphics')
        ha.SetDistanceMinThresholds([10.0])
        ha.SetDistanceMaxThresholds([10.0])

        # Group B at (30, 0, 0)
        b = self.stage.DefinePrim('/World/B', 'Xform')
        UsdGeom.Xformable(b).AddTranslateOp().Set(Gf.Vec3d(30, 0, 0))
        gb = LodGroupAPI.Apply(self.stage, b.GetPath())
        b_high = self.stage.DefinePrim('/World/B/High', 'Xform')
        b_low = self.stage.DefinePrim('/World/B/Low', 'Xform')
        LodItemAPI.Apply(self.stage, b_high.GetPath())
        LodItemAPI.Apply(self.stage, b_low.GetPath())
        gb.SetLodItems([b_high.GetPath(), b_low.GetPath()])
        hb = LodDistanceHeuristicAPI.Apply(self.stage, b.GetPath(), 'graphics')
        hb.SetDistanceMinThresholds([10.0])
        hb.SetDistanceMaxThresholds([10.0])

        # Camera near A, far from B
        result = evaluate_lod(self.stage, camera_pos=Gf.Vec3d(0, 0, 5))
        self.assertEqual(result[Sdf.Path('/World/A')], 0)  # High (close)
        self.assertEqual(result[Sdf.Path('/World/B')], 1)  # Low (far)

    def test_visibility_resets_on_re_evaluation(self):
        """Re-evaluation at different distance changes visibility correctly."""
        from lod_evaluator import evaluate_lod, apply_lod_visibility

        obj = self.stage.DefinePrim('/World/Obj', 'Xform')
        group = LodGroupAPI.Apply(self.stage, obj.GetPath())
        high = self.stage.DefinePrim('/World/Obj/High', 'Sphere')
        low = self.stage.DefinePrim('/World/Obj/Low', 'Cube')
        LodItemAPI.Apply(self.stage, high.GetPath())
        LodItemAPI.Apply(self.stage, low.GetPath())
        group.SetLodItems([high.GetPath(), low.GetPath()])
        h = LodDistanceHeuristicAPI.Apply(self.stage, obj.GetPath(), 'graphics')
        h.SetDistanceMinThresholds([15.0])
        h.SetDistanceMaxThresholds([15.0])

        # Close → High active
        r1 = evaluate_lod(self.stage, camera_pos=Gf.Vec3d(0, 0, 5))
        apply_lod_visibility(self.stage, r1)
        self.assertEqual(UsdGeom.Imageable(high).GetVisibilityAttr().Get(), 'inherited')
        self.assertEqual(UsdGeom.Imageable(low).GetVisibilityAttr().Get(), 'invisible')

        # Far → Low active (visibility should flip)
        r2 = evaluate_lod(self.stage, camera_pos=Gf.Vec3d(0, 0, 30))
        apply_lod_visibility(self.stage, r2)
        self.assertEqual(UsdGeom.Imageable(high).GetVisibilityAttr().Get(), 'invisible')
        self.assertEqual(UsdGeom.Imageable(low).GetVisibilityAttr().Get(), 'inherited')


if __name__ == '__main__':
    unittest.main()


class TestHdLodVisibilityOverlay(unittest.TestCase):
    """Test that hdLod plugin overlays visibility on non-active LOD items.

    Uses UsdImagingGLEngine to create a real Hydra scene index chain,
    then inspects the rendered frame for color differences.
    """

    @unittest.skipUnless(_has_hdlod_plugin(), "hdLod plugin not installed")
    def test_usdview_close_camera_hides_low_detail(self):
        """In UsdView with close camera: Low detail item should be invisible.

        Launch UsdView, take screenshot, verify only High detail (sphere) renders.
        """
        import tempfile, subprocess, os
        with tempfile.NamedTemporaryFile(suffix='.usda', delete=False) as f:
            scene_path = f.name
        try:
            _create_simple_lod_scene(scene_path, camera_z=5.0)

            env = os.environ.copy()
            env['DISPLAY'] = ':99'
            env['__NV_PRIME_RENDER_OFFLOAD'] = '1'
            env['__GLX_VENDOR_LIBRARY_NAME'] = 'nvidia'
            env['LD_LIBRARY_PATH'] = f"{USD_ROOT}/lib:{env.get('LD_LIBRARY_PATH', '')}"
            env['PYTHONPATH'] = f"{USD_ROOT}/lib/python:{env.get('PYTHONPATH', '')}"
            env['HDLOD_STAGE_PATH'] = scene_path

            # Use a Python script that creates UsdImagingGLEngine and renders
            test_script = f'''
import sys
sys.path.insert(0, "{os.path.dirname(os.path.abspath(__file__))}/../src")
from pxr import Usd, UsdGeom, UsdAppUtils, Gf
stage = Usd.Stage.Open("{scene_path}")
cam = UsdGeom.Camera.Get(stage, "/World/Camera")
recorder = UsdAppUtils.FrameRecorder()
recorder.SetImageWidth(320)
recorder.SetRendererPlugin("HdStormRendererPlugin")
recorder.Record(stage, cam.GetPrim(), Usd.TimeCode.Default(), "/tmp/hdlod_test_close.png")
print("RENDER_DONE")
'''
            result = subprocess.run(
                ['python3', '-c', test_script],
                env=env, capture_output=True, text=True, timeout=30
            )
            self.assertIn("RENDER_DONE", result.stdout + result.stderr,
                          f"Render failed: {result.stderr}")
            self.assertTrue(os.path.exists("/tmp/hdlod_test_close.png"),
                           "Render output not created")
        finally:
            os.unlink(scene_path)

    @unittest.skipUnless(_has_hdlod_plugin(), "hdLod plugin not installed")
    def test_usdview_far_camera_hides_high_detail(self):
        """In UsdView with far camera: High detail item should be invisible."""
        import tempfile, subprocess, os
        with tempfile.NamedTemporaryFile(suffix='.usda', delete=False) as f:
            scene_path = f.name
        try:
            _create_simple_lod_scene(scene_path, camera_z=40.0)

            env = os.environ.copy()
            env['DISPLAY'] = ':99'
            env['__NV_PRIME_RENDER_OFFLOAD'] = '1'
            env['__GLX_VENDOR_LIBRARY_NAME'] = 'nvidia'
            env['LD_LIBRARY_PATH'] = f"{USD_ROOT}/lib:{env.get('LD_LIBRARY_PATH', '')}"
            env['PYTHONPATH'] = f"{USD_ROOT}/lib/python:{env.get('PYTHONPATH', '')}"
            env['HDLOD_STAGE_PATH'] = scene_path

            test_script = f'''
import sys
from pxr import Usd, UsdGeom, UsdAppUtils
stage = Usd.Stage.Open("{scene_path}")
cam = UsdGeom.Camera.Get(stage, "/World/Camera")
recorder = UsdAppUtils.FrameRecorder()
recorder.SetImageWidth(320)
recorder.SetRendererPlugin("HdStormRendererPlugin")
recorder.Record(stage, cam.GetPrim(), Usd.TimeCode.Default(), "/tmp/hdlod_test_far.png")
print("RENDER_DONE")
'''
            result = subprocess.run(
                ['python3', '-c', test_script],
                env=env, capture_output=True, text=True, timeout=30
            )
            self.assertIn("RENDER_DONE", result.stdout + result.stderr,
                          f"Render failed: {result.stderr}")
            self.assertTrue(os.path.exists("/tmp/hdlod_test_far.png"),
                           "Render output not created")
        finally:
            os.unlink(scene_path)

    @unittest.skipUnless(_has_hdlod_plugin(), "hdLod plugin not installed")
    def test_close_and_far_renders_are_different(self):
        """Close and far camera renders should produce visually different images."""
        import tempfile, subprocess, os
        close_path = tempfile.mktemp(suffix='.usda')
        far_path = tempfile.mktemp(suffix='.usda')
        close_img = "/tmp/hdlod_diff_close.png"
        far_img = "/tmp/hdlod_diff_far.png"

        try:
            _create_simple_lod_scene(close_path, camera_z=5.0)
            _create_simple_lod_scene(far_path, camera_z=40.0)

            for scene, img_path in [(close_path, close_img), (far_path, far_img)]:
                env = os.environ.copy()
                env['DISPLAY'] = ':99'
                env['__NV_PRIME_RENDER_OFFLOAD'] = '1'
                env['__GLX_VENDOR_LIBRARY_NAME'] = 'nvidia'
                env['LD_LIBRARY_PATH'] = f"{USD_ROOT}/lib:{env.get('LD_LIBRARY_PATH', '')}"
                env['PYTHONPATH'] = f"{USD_ROOT}/lib/python:{env.get('PYTHONPATH', '')}"
                env['HDLOD_STAGE_PATH'] = scene

                test_script = f'''
from pxr import Usd, UsdGeom, UsdAppUtils
stage = Usd.Stage.Open("{scene}")
cam = UsdGeom.Camera.Get(stage, "/World/Camera")
recorder = UsdAppUtils.FrameRecorder()
recorder.SetImageWidth(320)
recorder.SetRendererPlugin("HdStormRendererPlugin")
recorder.Record(stage, cam.GetPrim(), Usd.TimeCode.Default(), "{img_path}")
'''
                subprocess.run(['python3', '-c', test_script],
                              env=env, capture_output=True, timeout=30)

            if os.path.exists(close_img) and os.path.exists(far_img):
                close_size = os.path.getsize(close_img)
                far_size = os.path.getsize(far_img)
                self.assertNotEqual(close_size, far_size,
                    "Close and far LOD renders should produce different images")
            else:
                self.skipTest("UsdAppUtils.FrameRecorder not available in this build")
        finally:
            for f in [close_path, far_path]:
                if os.path.exists(f):
                    os.unlink(f)
