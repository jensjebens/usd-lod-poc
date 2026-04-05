"""Tests for LOD switching heuristics.

These tests MUST fail initially (no implementation exists yet).
"""
import pytest
import math
import os
import sys

# Add USD to path
USD_ROOT = "/home/horde/.openclaw/workspace-alab/usd-bin/usd-v25.08"
sys.path.insert(0, os.path.join(USD_ROOT, "lib", "python"))
os.environ["LD_LIBRARY_PATH"] = os.path.join(USD_ROOT, "lib") + ":" + os.environ.get("LD_LIBRARY_PATH", "")

from pxr import Usd, UsdGeom, Gf, Sdf

# Import the module under test (doesn't exist yet → ImportError = expected failure)
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from lod_heuristics import compute_screen_fraction, decide_purpose


# ---------------------------------------------------------------------------
# Helpers: create minimal test stages
# ---------------------------------------------------------------------------

def _make_cube_camera_stage(cube_size=2.0, camera_distance=10.0, fov=90.0):
    """Create a stage with a unit cube at origin and a camera looking at it."""
    stage = Usd.Stage.CreateInMemory()

    # Cube centered at origin, size cube_size (half-extent = cube_size/2)
    cube_prim = stage.DefinePrim("/World/Cube", "Cube")
    cube_geom = UsdGeom.Cube(cube_prim)
    cube_geom.GetSizeAttr().Set(cube_size)

    # Camera at (0, 0, camera_distance) looking toward -Z (toward origin)
    cam_prim = stage.DefinePrim("/World/Camera", "Camera")
    cam = UsdGeom.Camera(cam_prim)

    # Set focal length and aperture to achieve desired FOV
    # FOV = 2 * atan(aperture / (2 * focalLength))
    # For 90° FOV with 20mm aperture: focalLength = 10mm
    aperture = 20.0  # mm
    focal_length = aperture / (2.0 * math.tan(math.radians(fov / 2.0)))
    cam.GetFocalLengthAttr().Set(focal_length)
    cam.GetHorizontalApertureAttr().Set(aperture)
    cam.GetVerticalApertureAttr().Set(aperture)  # square sensor
    cam.GetClippingRangeAttr().Set(Gf.Vec2f(0.1, 1000.0))

    # Position camera
    xformable = UsdGeom.Xformable(cam_prim)
    xformable.AddTranslateOp().Set(Gf.Vec3d(0, 0, camera_distance))

    return stage


# ---------------------------------------------------------------------------
# Tests: compute_screen_fraction
# ---------------------------------------------------------------------------

class TestComputeScreenFraction:
    """Test screen-space size computation."""

    def test_cube_at_known_distance(self):
        """A 2-unit cube at distance 10 with 90° FOV should have a predictable screen fraction."""
        stage = _make_cube_camera_stage(cube_size=2.0, camera_distance=10.0, fov=90.0)

        fraction = compute_screen_fraction(
            stage, "/World/Cube", "/World/Camera",
            time=Usd.TimeCode.Default(),
            image_width=1024, image_height=1024
        )

        # With 90° FOV, at distance 10, a 2-unit cube subtends:
        # angular half-size = atan(1/10) ≈ 5.71°
        # NDC half-extent ≈ tan(5.71°) / tan(45°) ≈ 0.1
        # NDC full extent ≈ 0.2 on each axis
        # screen_fraction ≈ (0.2 * 0.2) / 4.0 = 0.01
        assert fraction == pytest.approx(0.01, abs=0.005)

    def test_cube_very_close_fills_screen(self):
        """A cube very close to the camera should approach screen_fraction = 1.0."""
        stage = _make_cube_camera_stage(cube_size=100.0, camera_distance=1.0, fov=90.0)

        fraction = compute_screen_fraction(
            stage, "/World/Cube", "/World/Camera",
            time=Usd.TimeCode.Default(),
            image_width=1024, image_height=1024
        )

        assert fraction >= 0.9

    def test_cube_very_far_near_zero(self):
        """A tiny cube far from camera should have near-zero screen fraction."""
        stage = _make_cube_camera_stage(cube_size=0.01, camera_distance=500.0, fov=90.0)

        fraction = compute_screen_fraction(
            stage, "/World/Cube", "/World/Camera",
            time=Usd.TimeCode.Default(),
            image_width=1024, image_height=1024
        )

        assert fraction < 0.001

    def test_prim_behind_camera_returns_zero(self):
        """If the object is entirely behind the camera, screen fraction = 0."""
        stage = _make_cube_camera_stage(cube_size=2.0, camera_distance=10.0, fov=90.0)

        # Move cube behind camera (camera at Z=10, cube at Z=20)
        cube = stage.GetPrimAtPath("/World/Cube")
        UsdGeom.Xformable(cube).AddTranslateOp().Set(Gf.Vec3d(0, 0, 20))

        fraction = compute_screen_fraction(
            stage, "/World/Cube", "/World/Camera",
            time=Usd.TimeCode.Default(),
            image_width=1024, image_height=1024
        )

        assert fraction == 0.0

    def test_returns_float_between_0_and_1(self):
        """Screen fraction should always be in [0, 1]."""
        stage = _make_cube_camera_stage()

        fraction = compute_screen_fraction(
            stage, "/World/Cube", "/World/Camera",
            time=Usd.TimeCode.Default(),
            image_width=1024, image_height=1024
        )

        assert 0.0 <= fraction <= 1.0


# ---------------------------------------------------------------------------
# Tests: decide_purpose (hysteresis state machine)
# ---------------------------------------------------------------------------

class TestDecidePurpose:
    """Test purpose switching with hysteresis."""

    def test_proxy_to_render_above_high(self):
        """When proxy and screen_fraction >= high_threshold → switch to render."""
        result = decide_purpose(
            screen_fraction=0.10,
            current_purpose="proxy",
            high_threshold=0.05,
            low_threshold=0.02
        )
        assert result == "render"

    def test_render_to_proxy_below_low(self):
        """When render and screen_fraction <= low_threshold → switch to proxy."""
        result = decide_purpose(
            screen_fraction=0.01,
            current_purpose="render",
            high_threshold=0.05,
            low_threshold=0.02
        )
        assert result == "proxy"

    def test_proxy_stays_in_dead_zone(self):
        """When proxy and screen_fraction is between thresholds → stay proxy."""
        result = decide_purpose(
            screen_fraction=0.03,
            current_purpose="proxy",
            high_threshold=0.05,
            low_threshold=0.02
        )
        assert result == "proxy"

    def test_render_stays_in_dead_zone(self):
        """When render and screen_fraction is between thresholds → stay render."""
        result = decide_purpose(
            screen_fraction=0.03,
            current_purpose="render",
            high_threshold=0.05,
            low_threshold=0.02
        )
        assert result == "render"

    def test_proxy_stays_below_low(self):
        """When proxy and screen_fraction < low_threshold → stay proxy."""
        result = decide_purpose(
            screen_fraction=0.001,
            current_purpose="proxy",
            high_threshold=0.05,
            low_threshold=0.02
        )
        assert result == "proxy"

    def test_render_stays_above_high(self):
        """When render and screen_fraction > high_threshold → stay render."""
        result = decide_purpose(
            screen_fraction=0.10,
            current_purpose="render",
            high_threshold=0.05,
            low_threshold=0.02
        )
        assert result == "render"

    def test_exact_high_threshold_switches(self):
        """Exactly at high_threshold from proxy → switch to render."""
        result = decide_purpose(
            screen_fraction=0.05,
            current_purpose="proxy",
            high_threshold=0.05,
            low_threshold=0.02
        )
        assert result == "render"

    def test_exact_low_threshold_switches(self):
        """Exactly at low_threshold from render → switch to proxy."""
        result = decide_purpose(
            screen_fraction=0.02,
            current_purpose="render",
            high_threshold=0.05,
            low_threshold=0.02
        )
        assert result == "proxy"


# ---------------------------------------------------------------------------
# Tests: ALAB integration (smoke test)
# ---------------------------------------------------------------------------

ALAB_PATH = "/home/horde/.openclaw/workspace-alab/alab/ALab-2.3.0/ALab/entry.usda"


@pytest.mark.skipif(not os.path.exists(ALAB_PATH), reason="ALAB scene not available")
class TestALABIntegration:
    """Smoke tests against real ALAB assets."""

    def test_alab_proxy_prim_computes_fraction(self):
        """Can compute screen fraction for an ALAB prim with proxy purpose."""
        stage = Usd.Stage.Open(ALAB_PATH)
        assert stage is not None

        # Find a prim with proxy purpose
        proxy_path = None
        for prim in stage.Traverse():
            img = UsdGeom.Imageable(prim)
            if img:
                purpose_attr = img.GetPurposeAttr()
                if purpose_attr and purpose_attr.HasAuthoredValue():
                    if purpose_attr.Get() == "proxy":
                        proxy_path = str(prim.GetPath())
                        break

        assert proxy_path is not None, "No proxy prim found in ALAB"

        # We need a camera — create one at a reasonable position
        cam_prim = stage.OverridePrim("/TestCamera")
        cam_prim = stage.DefinePrim("/TestCamera", "Camera")
        cam = UsdGeom.Camera(cam_prim)
        cam.GetFocalLengthAttr().Set(50.0)
        cam.GetHorizontalApertureAttr().Set(36.0)
        cam.GetVerticalApertureAttr().Set(24.0)
        xf = UsdGeom.Xformable(cam_prim)
        xf.AddTranslateOp().Set(Gf.Vec3d(0, 150, 300))

        fraction = compute_screen_fraction(
            stage, proxy_path, "/TestCamera",
            time=Usd.TimeCode.Default(),
            image_width=1920, image_height=1080
        )

        # Should be a valid number
        assert isinstance(fraction, float)
        assert 0.0 <= fraction <= 1.0
