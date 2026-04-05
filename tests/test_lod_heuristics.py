"""Tests for LOD switching heuristics.

Tests both metrics:
  - compute_screen_size (primary — cone angle, fast)
  - compute_screen_fraction (secondary — NDC projection)
And the hysteresis decision function.
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

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from lod_heuristics import compute_screen_size, compute_screen_fraction, decide_purpose


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_cube_camera_stage(cube_size=2.0, camera_distance=10.0, fov=90.0):
    """Create a stage with a unit cube at origin and a camera looking at it."""
    stage = Usd.Stage.CreateInMemory()

    cube_prim = stage.DefinePrim("/World/Cube", "Cube")
    cube_geom = UsdGeom.Cube(cube_prim)
    cube_geom.GetSizeAttr().Set(cube_size)

    cam_prim = stage.DefinePrim("/World/Camera", "Camera")
    cam = UsdGeom.Camera(cam_prim)

    aperture = 20.0
    focal_length = aperture / (2.0 * math.tan(math.radians(fov / 2.0)))
    cam.GetFocalLengthAttr().Set(focal_length)
    cam.GetHorizontalApertureAttr().Set(aperture)
    cam.GetVerticalApertureAttr().Set(aperture)
    cam.GetClippingRangeAttr().Set(Gf.Vec2f(0.1, 1000.0))

    xformable = UsdGeom.Xformable(cam_prim)
    xformable.AddTranslateOp().Set(Gf.Vec3d(0, 0, camera_distance))

    return stage


# ---------------------------------------------------------------------------
# Tests: compute_screen_size (primary — cone angle)
# ---------------------------------------------------------------------------

class TestComputeScreenSize:
    """Test the fast bounding-sphere screen size metric."""

    def test_known_distance(self):
        """A 2-unit cube at distance 10 should have predictable screen_size."""
        stage = _make_cube_camera_stage(cube_size=2.0, camera_distance=10.0)

        size = compute_screen_size(
            stage, "/World/Cube", "/World/Camera",
            time=Usd.TimeCode.Default()
        )

        # Cube half-extent = 1.0, bounding sphere radius = sqrt(3) ≈ 1.732
        # Distance from eye (0,0,10) to centre (0,0,0) = 10
        # screen_size = 1.732 / 10 ≈ 0.1732
        expected = math.sqrt(3) / 10.0
        assert size == pytest.approx(expected, rel=0.01)

    def test_very_close_returns_one(self):
        """Camera inside bounding sphere → screen_size = 1.0."""
        stage = _make_cube_camera_stage(cube_size=100.0, camera_distance=1.0)

        size = compute_screen_size(
            stage, "/World/Cube", "/World/Camera",
            time=Usd.TimeCode.Default()
        )

        assert size == 1.0

    def test_very_far_near_zero(self):
        """Tiny cube far away → near-zero screen_size."""
        stage = _make_cube_camera_stage(cube_size=0.01, camera_distance=500.0)

        size = compute_screen_size(
            stage, "/World/Cube", "/World/Camera",
            time=Usd.TimeCode.Default()
        )

        assert size < 0.001

    def test_inversely_proportional_to_distance(self):
        """Doubling the distance should halve the screen_size."""
        stage1 = _make_cube_camera_stage(cube_size=2.0, camera_distance=10.0)
        stage2 = _make_cube_camera_stage(cube_size=2.0, camera_distance=20.0)

        s1 = compute_screen_size(stage1, "/World/Cube", "/World/Camera")
        s2 = compute_screen_size(stage2, "/World/Cube", "/World/Camera")

        assert s1 == pytest.approx(2 * s2, rel=0.01)

    def test_proportional_to_size(self):
        """Doubling the cube size should double the screen_size."""
        stage1 = _make_cube_camera_stage(cube_size=2.0, camera_distance=10.0)
        stage2 = _make_cube_camera_stage(cube_size=4.0, camera_distance=10.0)

        s1 = compute_screen_size(stage1, "/World/Cube", "/World/Camera")
        s2 = compute_screen_size(stage2, "/World/Cube", "/World/Camera")

        assert s2 == pytest.approx(2 * s1, rel=0.01)

    def test_returns_float_in_range(self):
        """Result should always be in [0, 1]."""
        stage = _make_cube_camera_stage()

        size = compute_screen_size(
            stage, "/World/Cube", "/World/Camera"
        )

        assert 0.0 <= size <= 1.0

    def test_invalid_prim_returns_zero(self):
        """Non-existent prim → 0.0."""
        stage = _make_cube_camera_stage()

        size = compute_screen_size(
            stage, "/World/NonExistent", "/World/Camera"
        )

        assert size == 0.0

    def test_camera_independent_of_fov(self):
        """screen_size shouldn't change with FOV (it's a geometric ratio)."""
        stage1 = _make_cube_camera_stage(cube_size=2.0, camera_distance=10.0, fov=60.0)
        stage2 = _make_cube_camera_stage(cube_size=2.0, camera_distance=10.0, fov=120.0)

        s1 = compute_screen_size(stage1, "/World/Cube", "/World/Camera")
        s2 = compute_screen_size(stage2, "/World/Cube", "/World/Camera")

        assert s1 == pytest.approx(s2, rel=0.001)


# ---------------------------------------------------------------------------
# Tests: compute_screen_fraction (secondary — NDC projection)
# ---------------------------------------------------------------------------

class TestComputeScreenFraction:
    """Test the full NDC projection method."""

    def test_cube_at_known_distance(self):
        stage = _make_cube_camera_stage(cube_size=2.0, camera_distance=10.0, fov=90.0)

        fraction = compute_screen_fraction(
            stage, "/World/Cube", "/World/Camera",
            time=Usd.TimeCode.Default(),
            image_width=1024, image_height=1024
        )

        assert fraction == pytest.approx(0.01, abs=0.005)

    def test_cube_very_close_fills_screen(self):
        stage = _make_cube_camera_stage(cube_size=100.0, camera_distance=1.0, fov=90.0)

        fraction = compute_screen_fraction(
            stage, "/World/Cube", "/World/Camera",
            time=Usd.TimeCode.Default(),
            image_width=1024, image_height=1024
        )

        assert fraction >= 0.9

    def test_cube_very_far_near_zero(self):
        stage = _make_cube_camera_stage(cube_size=0.01, camera_distance=500.0, fov=90.0)

        fraction = compute_screen_fraction(
            stage, "/World/Cube", "/World/Camera",
            time=Usd.TimeCode.Default(),
            image_width=1024, image_height=1024
        )

        assert fraction < 0.001

    def test_prim_behind_camera_returns_zero(self):
        stage = _make_cube_camera_stage(cube_size=2.0, camera_distance=10.0, fov=90.0)
        cube = stage.GetPrimAtPath("/World/Cube")
        UsdGeom.Xformable(cube).AddTranslateOp().Set(Gf.Vec3d(0, 0, 20))

        fraction = compute_screen_fraction(
            stage, "/World/Cube", "/World/Camera",
            time=Usd.TimeCode.Default(),
            image_width=1024, image_height=1024
        )

        assert fraction == 0.0

    def test_returns_float_between_0_and_1(self):
        stage = _make_cube_camera_stage()

        fraction = compute_screen_fraction(
            stage, "/World/Cube", "/World/Camera",
            time=Usd.TimeCode.Default(),
            image_width=1024, image_height=1024
        )

        assert 0.0 <= fraction <= 1.0


# ---------------------------------------------------------------------------
# Tests: decide_purpose (hysteresis)
# ---------------------------------------------------------------------------

class TestDecidePurpose:
    """Test purpose switching with hysteresis dead zone."""

    def test_proxy_to_render_above_high(self):
        assert decide_purpose(0.10, "proxy", 0.05, 0.02) == "render"

    def test_render_to_proxy_below_low(self):
        assert decide_purpose(0.01, "render", 0.05, 0.02) == "proxy"

    def test_proxy_stays_in_dead_zone(self):
        assert decide_purpose(0.03, "proxy", 0.05, 0.02) == "proxy"

    def test_render_stays_in_dead_zone(self):
        assert decide_purpose(0.03, "render", 0.05, 0.02) == "render"

    def test_proxy_stays_below_low(self):
        assert decide_purpose(0.001, "proxy", 0.05, 0.02) == "proxy"

    def test_render_stays_above_high(self):
        assert decide_purpose(0.10, "render", 0.05, 0.02) == "render"

    def test_exact_high_threshold_switches(self):
        assert decide_purpose(0.05, "proxy", 0.05, 0.02) == "render"

    def test_exact_low_threshold_switches(self):
        assert decide_purpose(0.02, "render", 0.05, 0.02) == "proxy"

    def test_full_dolly_sequence(self):
        """Simulate camera dollying away then back — verify no flicker."""
        # Start close (render)
        purpose = "render"
        high, low = 0.05, 0.02

        # Camera pulls back: 0.10 → 0.04 → 0.03 → 0.019 → 0.01
        for val in [0.10, 0.04, 0.03, 0.019, 0.01]:
            purpose = decide_purpose(val, purpose, high, low)

        assert purpose == "proxy"  # Should have switched at 0.019 (≤ 0.02)

        # Camera pushes forward: 0.01 → 0.03 → 0.04 → 0.051
        for val in [0.01, 0.03, 0.04]:
            purpose = decide_purpose(val, purpose, high, low)
            assert purpose == "proxy"  # Dead zone — shouldn't switch yet

        purpose = decide_purpose(0.051, purpose, high, low)
        assert purpose == "render"  # Now above high → switch


# ---------------------------------------------------------------------------
# Tests: ALAB integration
# ---------------------------------------------------------------------------

ALAB_PATH = "/home/horde/.openclaw/workspace-alab/alab/ALab-2.3.0/ALab/entry.usda"


@pytest.mark.skipif(not os.path.exists(ALAB_PATH), reason="ALAB scene not available")
class TestALABIntegration:
    """Smoke tests against real ALAB assets."""

    def _make_alab_camera(self, stage):
        """Add a test camera to the ALAB stage."""
        cam_prim = stage.DefinePrim("/TestCamera", "Camera")
        cam = UsdGeom.Camera(cam_prim)
        cam.GetFocalLengthAttr().Set(50.0)
        cam.GetHorizontalApertureAttr().Set(36.0)
        cam.GetVerticalApertureAttr().Set(24.0)
        xf = UsdGeom.Xformable(cam_prim)
        xf.AddTranslateOp().Set(Gf.Vec3d(0, 150, 300))
        return "/TestCamera"

    def _find_proxy_prim(self, stage):
        """Find the first prim with proxy purpose."""
        for prim in stage.Traverse():
            img = UsdGeom.Imageable(prim)
            if img:
                pa = img.GetPurposeAttr()
                if pa and pa.HasAuthoredValue() and pa.Get() == "proxy":
                    return str(prim.GetPath())
        return None

    def test_alab_screen_size(self):
        """compute_screen_size works on an ALAB proxy prim."""
        stage = Usd.Stage.Open(ALAB_PATH)
        cam_path = self._make_alab_camera(stage)
        proxy_path = self._find_proxy_prim(stage)
        assert proxy_path is not None

        size = compute_screen_size(stage, proxy_path, cam_path)
        assert isinstance(size, float)
        assert 0.0 <= size <= 1.0

    def test_alab_screen_fraction(self):
        """compute_screen_fraction works on an ALAB proxy prim."""
        stage = Usd.Stage.Open(ALAB_PATH)
        cam_path = self._make_alab_camera(stage)
        proxy_path = self._find_proxy_prim(stage)
        assert proxy_path is not None

        fraction = compute_screen_fraction(
            stage, proxy_path, cam_path,
            image_width=1920, image_height=1080
        )
        assert isinstance(fraction, float)
        assert 0.0 <= fraction <= 1.0
