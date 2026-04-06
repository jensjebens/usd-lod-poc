"""Tests for purpose-specific visibility in Hydra rendering.

These tests verify that VisibilityAPI's proxyVisibility, renderVisibility,
and guideVisibility attributes are respected by the Hydra rendering pipeline.

Tests are written to FAIL against current USD (the bug we're fixing).
They should PASS after the fix is applied.

Test levels:
  1. UsdImagingDataSourcePrim — does the data source expose purpose visibility?
  2. Flattening — does purpose visibility inherit to descendants?
  3. Rendering — does Storm actually hide prims based on purpose visibility?
"""
import pytest
import os
import sys
import subprocess
import math

USD_ROOT = "/tmp/usd-purpose-vis-build"
sys.path.insert(0, os.path.join(USD_ROOT, "lib", "python"))
os.environ["LD_LIBRARY_PATH"] = os.path.join(USD_ROOT, "lib") + ":" + os.environ.get("LD_LIBRARY_PATH", "")

from pxr import Usd, UsdGeom, UsdShade, Gf, Sdf


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_material(stage, path, color):
    """Create a simple UsdPreviewSurface material."""
    mat = UsdShade.Material.Define(stage, path)
    sh = UsdShade.Shader.Define(stage, path + "/S")
    sh.CreateIdAttr("UsdPreviewSurface")
    sh.CreateInput("diffuseColor", Sdf.ValueTypeNames.Color3f).Set(Gf.Vec3f(*color))
    mat.CreateSurfaceOutput().ConnectToSource(sh.ConnectableAPI(), "surface")
    return mat


def _make_purpose_vis_stage():
    """Create a test stage with purpose visibility set.

    Layout (all at y=1, camera at z=8):
      Left  (-3,1,0): Sphere, purpose=render, renderVisibility=invisible
      Centre (0,1,0): Cube,   purpose=proxy,  proxyVisibility=invisible
      Right  (3,1,0): Sphere, purpose=render, renderVisibility=inherited (visible)
    """
    stage = Usd.Stage.CreateInMemory()
    UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.y)

    # Camera
    cam = UsdGeom.Camera.Define(stage, "/World/Camera")
    cam.GetFocalLengthAttr().Set(35.0)
    cam.GetHorizontalApertureAttr().Set(36.0)
    cam.GetVerticalApertureAttr().Set(20.25)
    UsdGeom.Xformable(cam.GetPrim()).AddTranslateOp().Set(Gf.Vec3d(0, 2, 8))

    red = _make_material(stage, "/World/Mats/Red", (0.9, 0.1, 0.1))
    green = _make_material(stage, "/World/Mats/Green", (0.1, 0.8, 0.2))
    blue = _make_material(stage, "/World/Mats/Blue", (0.1, 0.2, 0.9))

    # LEFT: render purpose, renderVisibility=invisible → should be hidden
    left = UsdGeom.Sphere.Define(stage, "/World/Left")
    left.GetRadiusAttr().Set(1.0)
    UsdGeom.Xformable(left.GetPrim()).AddTranslateOp().Set(Gf.Vec3d(-3, 1, 0))
    UsdGeom.Imageable(left.GetPrim()).CreatePurposeAttr().Set(UsdGeom.Tokens.render)
    vis = UsdGeom.VisibilityAPI.Apply(left.GetPrim())
    vis.CreateRenderVisibilityAttr().Set("invisible")
    UsdShade.MaterialBindingAPI.Apply(left.GetPrim())
    UsdShade.MaterialBindingAPI(left.GetPrim()).Bind(red)

    # CENTRE: proxy purpose, proxyVisibility=invisible → should be hidden
    centre = UsdGeom.Cube.Define(stage, "/World/Centre")
    centre.GetSizeAttr().Set(1.8)
    UsdGeom.Xformable(centre.GetPrim()).AddTranslateOp().Set(Gf.Vec3d(0, 1, 0))
    UsdGeom.Imageable(centre.GetPrim()).CreatePurposeAttr().Set(UsdGeom.Tokens.proxy)
    vis2 = UsdGeom.VisibilityAPI.Apply(centre.GetPrim())
    vis2.CreateProxyVisibilityAttr().Set("invisible")
    UsdShade.MaterialBindingAPI.Apply(centre.GetPrim())
    UsdShade.MaterialBindingAPI(centre.GetPrim()).Bind(green)

    # RIGHT: render purpose, no vis override → should be visible
    right = UsdGeom.Sphere.Define(stage, "/World/Right")
    right.GetRadiusAttr().Set(1.0)
    UsdGeom.Xformable(right.GetPrim()).AddTranslateOp().Set(Gf.Vec3d(3, 1, 0))
    UsdGeom.Imageable(right.GetPrim()).CreatePurposeAttr().Set(UsdGeom.Tokens.render)
    UsdShade.MaterialBindingAPI.Apply(right.GetPrim())
    UsdShade.MaterialBindingAPI(right.GetPrim()).Bind(blue)

    return stage


def _make_inherited_purpose_vis_stage():
    """Stage where purpose visibility is set on parent and should inherit to child.

    /World/Group (Xform, proxyVisibility=invisible)
      /World/Group/Child (Cube, purpose=proxy)

    Child should be invisible via inherited proxyVisibility.
    """
    stage = Usd.Stage.CreateInMemory()
    UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.y)

    cam = UsdGeom.Camera.Define(stage, "/World/Camera")
    cam.GetFocalLengthAttr().Set(35.0)
    cam.GetHorizontalApertureAttr().Set(36.0)
    cam.GetVerticalApertureAttr().Set(20.25)
    UsdGeom.Xformable(cam.GetPrim()).AddTranslateOp().Set(Gf.Vec3d(0, 2, 8))

    green = _make_material(stage, "/World/Mats/Green", (0.1, 0.8, 0.2))

    group = UsdGeom.Xform.Define(stage, "/World/Group")
    vis = UsdGeom.VisibilityAPI.Apply(group.GetPrim())
    vis.CreateProxyVisibilityAttr().Set("invisible")

    child = UsdGeom.Cube.Define(stage, "/World/Group/Child")
    child.GetSizeAttr().Set(2.0)
    UsdGeom.Xformable(child.GetPrim()).AddTranslateOp().Set(Gf.Vec3d(0, 1, 0))
    UsdGeom.Imageable(child.GetPrim()).CreatePurposeAttr().Set(UsdGeom.Tokens.proxy)
    UsdShade.MaterialBindingAPI.Apply(child.GetPrim())
    UsdShade.MaterialBindingAPI(child.GetPrim()).Bind(green)

    return stage


def _make_override_purpose_vis_stage():
    """Stage where child overrides parent's purpose visibility with 'visible'.

    /World/Group (Xform, proxyVisibility=invisible)
      /World/Group/Child (Cube, purpose=proxy, proxyVisibility=visible)

    Child should be visible — 'visible' overrides ancestor 'invisible'.
    """
    stage = Usd.Stage.CreateInMemory()
    UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.y)

    cam = UsdGeom.Camera.Define(stage, "/World/Camera")
    cam.GetFocalLengthAttr().Set(35.0)
    cam.GetHorizontalApertureAttr().Set(36.0)
    cam.GetVerticalApertureAttr().Set(20.25)
    UsdGeom.Xformable(cam.GetPrim()).AddTranslateOp().Set(Gf.Vec3d(0, 2, 8))

    green = _make_material(stage, "/World/Mats/Green", (0.1, 0.8, 0.2))

    group = UsdGeom.Xform.Define(stage, "/World/Group")
    vis = UsdGeom.VisibilityAPI.Apply(group.GetPrim())
    vis.CreateProxyVisibilityAttr().Set("invisible")

    child = UsdGeom.Cube.Define(stage, "/World/Group/Child")
    child.GetSizeAttr().Set(2.0)
    UsdGeom.Xformable(child.GetPrim()).AddTranslateOp().Set(Gf.Vec3d(0, 1, 0))
    UsdGeom.Imageable(child.GetPrim()).CreatePurposeAttr().Set(UsdGeom.Tokens.proxy)
    vis2 = UsdGeom.VisibilityAPI.Apply(child.GetPrim())
    vis2.CreateProxyVisibilityAttr().Set("visible")
    UsdShade.MaterialBindingAPI.Apply(child.GetPrim())
    UsdShade.MaterialBindingAPI(child.GetPrim()).Bind(green)

    return stage


def _make_base_vis_overrides_purpose_vis_stage():
    """Stage where base visibility=invisible should override purpose visibility.

    /World/Object (Sphere, purpose=render, visibility=invisible, renderVisibility=inherited)

    Should be invisible — base visibility overrides purpose visibility.
    """
    stage = Usd.Stage.CreateInMemory()
    UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.y)

    cam = UsdGeom.Camera.Define(stage, "/World/Camera")
    cam.GetFocalLengthAttr().Set(35.0)
    cam.GetHorizontalApertureAttr().Set(36.0)
    cam.GetVerticalApertureAttr().Set(20.25)
    UsdGeom.Xformable(cam.GetPrim()).AddTranslateOp().Set(Gf.Vec3d(0, 2, 8))

    blue = _make_material(stage, "/World/Mats/Blue", (0.1, 0.2, 0.9))

    obj = UsdGeom.Sphere.Define(stage, "/World/Object")
    obj.GetRadiusAttr().Set(1.0)
    UsdGeom.Xformable(obj.GetPrim()).AddTranslateOp().Set(Gf.Vec3d(0, 1, 0))
    UsdGeom.Imageable(obj.GetPrim()).CreatePurposeAttr().Set(UsdGeom.Tokens.render)
    UsdGeom.Imageable(obj.GetPrim()).GetVisibilityAttr().Set("invisible")
    UsdShade.MaterialBindingAPI.Apply(obj.GetPrim())
    UsdShade.MaterialBindingAPI(obj.GetPrim()).Bind(blue)

    return stage


def _render_and_check_visibility(stage, purposes, expected_visible_paths):
    """Save stage, render with usdrecord, check which objects are visible.

    Returns dict of {prim_name: bool_visible}.
    """
    stage_path = "/tmp/test_purpose_vis_render.usda"
    stage.GetRootLayer().Export(stage_path)

    out_path = "/tmp/test_purpose_vis_render.png"
    env = os.environ.copy()
    env["DISPLAY"] = ":99"
    env["__NV_PRIME_RENDER_OFFLOAD"] = "1"
    env["__GLX_VENDOR_LIBRARY_NAME"] = "nvidia"
    env["PATH"] = os.path.join(USD_ROOT, "bin") + ":" + env.get("PATH", "")
    env["LD_LIBRARY_PATH"] = os.path.join(USD_ROOT, "lib") + ":" + env.get("LD_LIBRARY_PATH", "")
    env["PYTHONPATH"] = os.path.join(USD_ROOT, "lib", "python") + ":" + env.get("PYTHONPATH", "")

    purposes_arg = ",".join(purposes)
    cmd = [
        "usdrecord", "--camera", "/World/Camera", "--defaultTime",
        "--imageWidth", "960", "--purposes", purposes_arg,
        "--renderer", "Storm", stage_path, out_path,
    ]
    result = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, f"usdrecord failed: {result.stderr}"

    # Analyze rendered image
    from PIL import Image
    import numpy as np
    img = Image.open(out_path).convert("RGBA")
    arr = np.array(img)
    alpha = arr[:, :, 3]
    h, w = arr.shape[:2]

    visible = {}
    # Scan horizontal thirds for objects
    for prim in stage.Traverse():
        if not UsdGeom.Imageable(prim).GetPurposeAttr().HasAuthoredValue():
            continue
        xform = UsdGeom.Xformable(prim)
        ops = xform.GetOrderedXformOps()
        if not ops:
            continue
        pos = ops[0].Get()
        if pos is None:
            continue

        # Map world X to screen X (approximate — camera at z=8 looking at origin)
        screen_x = int(w * (0.5 + pos[0] / 12.0))
        screen_x = max(0, min(w - 1, screen_x))

        # Check a vertical column around this x for any non-transparent pixels
        col_alpha = alpha[:, max(0, screen_x - 30):min(w, screen_x + 30)]
        has_pixels = col_alpha.max() > 0

        name = str(prim.GetPath())
        visible[name] = has_pixels

    return visible


# ---------------------------------------------------------------------------
# Level 1: USD Computation (baseline — these should already pass)
# ---------------------------------------------------------------------------

class TestUSDComputation:
    """Verify ComputeEffectiveVisibility returns correct values.
    These pass today — they're the baseline."""

    def test_render_invisible_computed(self):
        stage = _make_purpose_vis_stage()
        left = UsdGeom.Imageable(stage.GetPrimAtPath("/World/Left"))
        assert left.ComputeEffectiveVisibility("render") == "invisible"

    def test_proxy_invisible_computed(self):
        stage = _make_purpose_vis_stage()
        centre = UsdGeom.Imageable(stage.GetPrimAtPath("/World/Centre"))
        assert centre.ComputeEffectiveVisibility("proxy") == "invisible"

    def test_render_visible_computed(self):
        stage = _make_purpose_vis_stage()
        right = UsdGeom.Imageable(stage.GetPrimAtPath("/World/Right"))
        assert right.ComputeEffectiveVisibility("render") == "inherited"

    def test_inherited_from_parent(self):
        stage = _make_inherited_purpose_vis_stage()
        child = UsdGeom.Imageable(stage.GetPrimAtPath("/World/Group/Child"))
        assert child.ComputeEffectiveVisibility("proxy") == "invisible"

    def test_child_overrides_parent(self):
        stage = _make_override_purpose_vis_stage()
        child = UsdGeom.Imageable(stage.GetPrimAtPath("/World/Group/Child"))
        assert child.ComputeEffectiveVisibility("proxy") == "visible"

    def test_base_vis_overrides_purpose(self):
        stage = _make_base_vis_overrides_purpose_vis_stage()
        obj = UsdGeom.Imageable(stage.GetPrimAtPath("/World/Object"))
        assert obj.ComputeEffectiveVisibility("render") == "invisible"


# ---------------------------------------------------------------------------
# Level 2: Rendering — Storm should respect purpose visibility
# These tests FAIL today (the bug). They should PASS after the fix.
# ---------------------------------------------------------------------------

@pytest.mark.skipif(
    not os.path.exists(os.path.join(USD_ROOT, "bin", "usdrecord")),
    reason="usdrecord not available"
)
class TestRendering:
    """Verify Storm rendering respects purpose visibility attributes."""

    def test_render_purpose_invisible_hides_prim(self):
        """A prim with purpose=render and renderVisibility=invisible
        should NOT be rendered when render purpose is included."""
        stage = _make_purpose_vis_stage()
        vis = _render_and_check_visibility(
            stage, ["render", "proxy"],
            expected_visible_paths=["/World/Right"]
        )
        assert vis.get("/World/Left") == False, \
            "Left prim (renderVisibility=invisible) should be hidden"

    def test_proxy_purpose_invisible_hides_prim(self):
        """A prim with purpose=proxy and proxyVisibility=invisible
        should NOT be rendered when proxy purpose is included."""
        stage = _make_purpose_vis_stage()
        vis = _render_and_check_visibility(
            stage, ["render", "proxy"],
            expected_visible_paths=["/World/Right"]
        )
        assert vis.get("/World/Centre") == False, \
            "Centre prim (proxyVisibility=invisible) should be hidden"

    def test_render_visible_stays_visible(self):
        """A prim with purpose=render and no visibility override
        should still be rendered."""
        stage = _make_purpose_vis_stage()
        vis = _render_and_check_visibility(
            stage, ["render", "proxy"],
            expected_visible_paths=["/World/Right"]
        )
        assert vis.get("/World/Right") == True, \
            "Right prim (renderVisibility=inherited) should be visible"

    def test_inherited_purpose_vis_hides_child(self):
        """proxyVisibility=invisible on parent should hide child with proxy purpose."""
        stage = _make_inherited_purpose_vis_stage()
        vis = _render_and_check_visibility(
            stage, ["render", "proxy"],
            expected_visible_paths=[]
        )
        assert vis.get("/World/Group/Child") == False, \
            "Child should be hidden via inherited proxyVisibility=invisible"

    def test_child_visible_overrides_parent_invisible(self):
        """proxyVisibility=visible on child should override parent's invisible."""
        stage = _make_override_purpose_vis_stage()
        vis = _render_and_check_visibility(
            stage, ["render", "proxy"],
            expected_visible_paths=["/World/Group/Child"]
        )
        assert vis.get("/World/Group/Child") == True, \
            "Child with proxyVisibility=visible should override parent's invisible"

    def test_base_visibility_overrides_purpose_visibility(self):
        """visibility=invisible should override purpose visibility regardless."""
        stage = _make_base_vis_overrides_purpose_vis_stage()
        vis = _render_and_check_visibility(
            stage, ["render"],
            expected_visible_paths=[]
        )
        assert vis.get("/World/Object") == False, \
            "Base visibility=invisible should override everything"
