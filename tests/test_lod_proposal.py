"""
Tests for LOD Proposal POC — LodGroupAPI, LodItemAPI, LodHeuristicAPI

These tests define expected behavior BEFORE implementation.
All should FAIL initially (proves they're testing something real).

Issue: https://github.com/jensjebens/OpenUSD/issues/16
Proposal: https://github.com/PixarAnimationStudios/OpenUSD-proposals/pull/81
"""

import unittest
import os
import sys

# Add the src directory to path for our LOD module
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from pxr import Usd, UsdGeom, Sdf, Gf


class TestLodSchemaAuthoring(unittest.TestCase):
    """Test that LOD schemas can be authored and read back correctly."""

    def setUp(self):
        self.stage = Usd.Stage.CreateInMemory()
        self.stage.SetMetadata('upAxis', 'Y')

    def test_apply_lod_group_api(self):
        """LodGroupAPI can be applied to a prim and stores lodItems relationship."""
        from usd_lod import LodGroupAPI

        prim = self.stage.DefinePrim('/World/Vehicle', 'Xform')
        group = LodGroupAPI.Apply(self.stage, prim.GetPath())

        self.assertTrue(group.IsApplied())
        # Should have lodItems relationship
        items_rel = group.GetLodItemsRel()
        self.assertIsNotNone(items_rel)

    def test_apply_lod_item_api(self):
        """LodItemAPI can be applied to a prim."""
        from usd_lod import LodItemAPI

        prim = self.stage.DefinePrim('/World/Vehicle/HighDetail', 'Xform')
        item = LodItemAPI.Apply(self.stage, prim.GetPath())

        self.assertTrue(item.IsApplied())

    def test_apply_distance_heuristic(self):
        """LodDistanceHeuristicAPI can be applied with min/max thresholds."""
        from usd_lod import LodDistanceHeuristicAPI

        prim = self.stage.DefinePrim('/World/Vehicle/HighDetail', 'Xform')
        heuristic = LodDistanceHeuristicAPI.Apply(
            self.stage, prim.GetPath(), instance_name='graphics'
        )

        heuristic.SetDistanceMinThresholds([5.0, 15.0, 30.0])
        heuristic.SetDistanceMaxThresholds([7.0, 17.0, 32.0])

        self.assertEqual(heuristic.GetDistanceMinThresholds(), [5.0, 15.0, 30.0])
        self.assertEqual(heuristic.GetDistanceMaxThresholds(), [7.0, 17.0, 32.0])

    def test_lod_group_items_relationship(self):
        """LodGroupAPI's lodItems relationship references LodItem prims in order."""
        from usd_lod import LodGroupAPI, LodItemAPI

        group_prim = self.stage.DefinePrim('/World/Vehicle', 'Xform')
        high = self.stage.DefinePrim('/World/Vehicle/High', 'Xform')
        mid = self.stage.DefinePrim('/World/Vehicle/Mid', 'Xform')
        low = self.stage.DefinePrim('/World/Vehicle/Low', 'Xform')

        LodItemAPI.Apply(self.stage, high.GetPath())
        LodItemAPI.Apply(self.stage, mid.GetPath())
        LodItemAPI.Apply(self.stage, low.GetPath())

        group = LodGroupAPI.Apply(self.stage, group_prim.GetPath())
        group.SetLodItems([
            high.GetPath(),
            mid.GetPath(),
            low.GetPath(),
        ])

        items = group.GetLodItems()
        self.assertEqual(len(items), 3)
        self.assertEqual(items[0], Sdf.Path('/World/Vehicle/High'))
        self.assertEqual(items[1], Sdf.Path('/World/Vehicle/Mid'))
        self.assertEqual(items[2], Sdf.Path('/World/Vehicle/Low'))

    def test_round_trip_usda(self):
        """LOD schema survives export/import to USDA."""
        from usd_lod import LodGroupAPI, LodItemAPI, LodDistanceHeuristicAPI

        # Author
        group_prim = self.stage.DefinePrim('/World/Vehicle', 'Xform')
        high = self.stage.DefinePrim('/World/Vehicle/High', 'Xform')

        LodItemAPI.Apply(self.stage, high.GetPath())
        group = LodGroupAPI.Apply(self.stage, group_prim.GetPath())
        group.SetLodItems([high.GetPath()])

        heuristic = LodDistanceHeuristicAPI.Apply(
            self.stage, group_prim.GetPath(), instance_name='graphics'
        )
        heuristic.SetDistanceMinThresholds([10.0, 50.0])

        # Export and reimport
        path = '/tmp/test_lod_roundtrip.usda'
        self.stage.GetRootLayer().Export(path)

        stage2 = Usd.Stage.Open(path)
        group2 = LodGroupAPI(stage2, Sdf.Path('/World/Vehicle'))
        self.assertTrue(group2.IsApplied())
        items = group2.GetLodItems()
        self.assertEqual(len(items), 1)


class TestLodEvaluator(unittest.TestCase):
    """Test the LOD evaluator — selects active LOD item based on heuristics."""

    def setUp(self):
        """Create a stage with a 3-level LOD group."""
        from usd_lod import LodGroupAPI, LodItemAPI, LodDistanceHeuristicAPI

        self.stage = Usd.Stage.CreateInMemory()
        self.stage.SetMetadata('upAxis', 'Y')

        # Create group
        group_prim = self.stage.DefinePrim('/World/Object', 'Xform')
        self.group = LodGroupAPI.Apply(self.stage, group_prim.GetPath())

        # Create 3 LOD items at origin
        self.high = self.stage.DefinePrim('/World/Object/High', 'Xform')
        self.mid = self.stage.DefinePrim('/World/Object/Mid', 'Xform')
        self.low = self.stage.DefinePrim('/World/Object/Low', 'Xform')

        for p in [self.high, self.mid, self.low]:
            LodItemAPI.Apply(self.stage, p.GetPath())

        self.group.SetLodItems([
            self.high.GetPath(),
            self.mid.GetPath(),
            self.low.GetPath(),
        ])

        # Distance heuristic: High <10, Mid 10-30, Low >30
        heuristic = LodDistanceHeuristicAPI.Apply(
            self.stage, group_prim.GetPath(), instance_name='graphics'
        )
        heuristic.SetDistanceMinThresholds([10.0, 30.0])
        heuristic.SetDistanceMaxThresholds([12.0, 32.0])

    def test_close_distance_selects_high(self):
        """Camera at distance 5 → selects High detail (index 0)."""
        from lod_evaluator import evaluate_lod

        result = evaluate_lod(self.stage, camera_pos=Gf.Vec3d(0, 0, 5))
        self.assertEqual(result[Sdf.Path('/World/Object')], 0)

    def test_mid_distance_selects_mid(self):
        """Camera at distance 20 → selects Mid detail (index 1)."""
        from lod_evaluator import evaluate_lod

        result = evaluate_lod(self.stage, camera_pos=Gf.Vec3d(0, 0, 20))
        self.assertEqual(result[Sdf.Path('/World/Object')], 1)

    def test_far_distance_selects_low(self):
        """Camera at distance 50 → selects Low detail (index 2)."""
        from lod_evaluator import evaluate_lod

        result = evaluate_lod(self.stage, camera_pos=Gf.Vec3d(0, 0, 50))
        self.assertEqual(result[Sdf.Path('/World/Object')], 2)

    def test_hysteresis_prevents_oscillation(self):
        """At threshold boundary, hysteresis prevents flickering.

        Min threshold at 10, max at 12.
        - Moving away at distance 11: should stay at High (was High)
        - Moving closer at distance 11: should stay at Mid (was Mid)
        """
        from lod_evaluator import evaluate_lod

        # Coming from close (was High=0), at distance 11 (between min=10, max=12)
        result = evaluate_lod(
            self.stage,
            camera_pos=Gf.Vec3d(0, 0, 11),
            prev_state={Sdf.Path('/World/Object'): 0}
        )
        self.assertEqual(result[Sdf.Path('/World/Object')], 0)  # stays High

        # Coming from far (was Mid=1), at distance 11
        result = evaluate_lod(
            self.stage,
            camera_pos=Gf.Vec3d(0, 0, 11),
            prev_state={Sdf.Path('/World/Object'): 1}
        )
        self.assertEqual(result[Sdf.Path('/World/Object')], 1)  # stays Mid

    def test_no_prev_state_uses_min_thresholds(self):
        """Without previous state, uses min thresholds (no hysteresis)."""
        from lod_evaluator import evaluate_lod

        # At distance 11, no prev state → use min threshold (10) → Mid
        result = evaluate_lod(self.stage, camera_pos=Gf.Vec3d(0, 0, 11))
        self.assertEqual(result[Sdf.Path('/World/Object')], 1)


class TestLodHierarchical(unittest.TestCase):
    """Test hierarchical LOD evaluation (Axiom 1)."""

    def test_child_group_only_active_if_parent_active(self):
        """Nested LOD group: child only evaluated if parent's item is active.

        /World/City (LodGroup) → items: DetailedCity, SimplifiedCity
          /World/City/DetailedCity/Building (LodGroup) → items: HighBuilding, LowBuilding
        
        If camera is far (SimplifiedCity active), Building group is NOT evaluated.
        """
        from usd_lod import LodGroupAPI, LodItemAPI, LodDistanceHeuristicAPI
        from lod_evaluator import evaluate_lod

        stage = Usd.Stage.CreateInMemory()

        # Parent group: City
        city = stage.DefinePrim('/World/City', 'Xform')
        detailed = stage.DefinePrim('/World/City/DetailedCity', 'Xform')
        simplified = stage.DefinePrim('/World/City/SimplifiedCity', 'Xform')

        LodItemAPI.Apply(stage, detailed.GetPath())
        LodItemAPI.Apply(stage, simplified.GetPath())

        city_group = LodGroupAPI.Apply(stage, city.GetPath())
        city_group.SetLodItems([detailed.GetPath(), simplified.GetPath()])

        h1 = LodDistanceHeuristicAPI.Apply(stage, city.GetPath(), 'graphics')
        h1.SetDistanceMinThresholds([100.0])
        h1.SetDistanceMaxThresholds([100.0])

        # Child group: Building (inside DetailedCity)
        building = stage.DefinePrim('/World/City/DetailedCity/Building', 'Xform')
        high_b = stage.DefinePrim('/World/City/DetailedCity/Building/High', 'Xform')
        low_b = stage.DefinePrim('/World/City/DetailedCity/Building/Low', 'Xform')

        LodItemAPI.Apply(stage, high_b.GetPath())
        LodItemAPI.Apply(stage, low_b.GetPath())

        b_group = LodGroupAPI.Apply(stage, building.GetPath())
        b_group.SetLodItems([high_b.GetPath(), low_b.GetPath()])

        h2 = LodDistanceHeuristicAPI.Apply(stage, building.GetPath(), 'graphics')
        h2.SetDistanceMinThresholds([20.0])
        h2.SetDistanceMaxThresholds([20.0])

        # Far camera (200 units) → City selects SimplifiedCity
        # Building group should NOT be in the result (parent inactive)
        result = evaluate_lod(stage, camera_pos=Gf.Vec3d(0, 0, 200))
        self.assertEqual(result[Sdf.Path('/World/City')], 1)  # SimplifiedCity
        self.assertNotIn(Sdf.Path('/World/City/DetailedCity/Building'), result)

        # Close camera (10 units) → City selects DetailedCity
        # Building group SHOULD be evaluated → High
        result = evaluate_lod(stage, camera_pos=Gf.Vec3d(0, 0, 10))
        self.assertEqual(result[Sdf.Path('/World/City')], 0)  # DetailedCity
        self.assertEqual(
            result[Sdf.Path('/World/City/DetailedCity/Building')], 0  # High building
        )


class TestLodVisibilityApplication(unittest.TestCase):
    """Test that LOD evaluation results are applied as visibility."""

    def test_active_item_visible_others_invisible(self):
        """After applying LOD result, only the active item is visible."""
        from usd_lod import LodGroupAPI, LodItemAPI, LodDistanceHeuristicAPI
        from lod_evaluator import evaluate_lod, apply_lod_visibility

        stage = Usd.Stage.CreateInMemory()

        group_prim = stage.DefinePrim('/World/Obj', 'Xform')
        high = stage.DefinePrim('/World/Obj/High', 'Sphere')
        low = stage.DefinePrim('/World/Obj/Low', 'Cube')

        LodItemAPI.Apply(stage, high.GetPath())
        LodItemAPI.Apply(stage, low.GetPath())

        group = LodGroupAPI.Apply(stage, group_prim.GetPath())
        group.SetLodItems([high.GetPath(), low.GetPath()])

        h = LodDistanceHeuristicAPI.Apply(stage, group_prim.GetPath(), 'graphics')
        h.SetDistanceMinThresholds([20.0])
        h.SetDistanceMaxThresholds([20.0])

        # Evaluate at close distance → High active
        result = evaluate_lod(stage, camera_pos=Gf.Vec3d(0, 0, 5))
        apply_lod_visibility(stage, result)

        high_img = UsdGeom.Imageable(high)
        low_img = UsdGeom.Imageable(low)

        self.assertEqual(high_img.GetVisibilityAttr().Get(), 'inherited')
        self.assertEqual(low_img.GetVisibilityAttr().Get(), 'invisible')


if __name__ == '__main__':
    unittest.main()
