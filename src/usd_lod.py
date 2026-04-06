"""
usd_lod.py — LOD Proposal POC: Schema helpers

Implements LodGroupAPI, LodItemAPI, and LodDistanceHeuristicAPI
as applied API schemas using pure USD attribute/relationship authoring.

Based on: https://github.com/PixarAnimationStudios/OpenUSD-proposals/pull/81
"""

from pxr import Usd, Sdf, Tf


# Namespace tokens matching the proposal
LOD_GROUP_API_NAME = 'LodGroupAPI'
LOD_ITEM_API_NAME = 'LodItemAPI'
LOD_HEURISTIC_NS = 'Heuristic'
LOD_DISTANCE_HEURISTIC_NS = 'distanceHeuristic'


class LodGroupAPI:
    """API for configuring Level of Detail on a prim.

    Applied as a single-apply API schema. Stores a `lodItems` relationship
    pointing to ordered LodItem prims (high → low detail).
    """

    SCHEMA_NAME = LOD_GROUP_API_NAME
    REL_LOD_ITEMS = 'lod:lodItems'

    def __init__(self, stage, prim_path):
        self._stage = stage
        self._path = Sdf.Path(prim_path) if isinstance(prim_path, str) else prim_path
        self._prim = stage.GetPrimAtPath(self._path)

    @classmethod
    def Apply(cls, stage, prim_path):
        """Apply LodGroupAPI to a prim."""
        path = Sdf.Path(prim_path) if isinstance(prim_path, str) else prim_path
        prim = stage.GetPrimAtPath(path)
        if not prim:
            raise ValueError(f"No prim at {path}")

        # Read existing schemas from metadata (not GetAppliedSchemas which filters)
        schemas = cls._get_api_schemas_from_prim(prim)
        if cls.SCHEMA_NAME not in schemas:
            schemas.append(cls.SCHEMA_NAME)
            prim.SetMetadata('apiSchemas', Sdf.TokenListOp.CreateExplicit(schemas))

        return cls(stage, path)

    def IsApplied(self):
        """Check if LodGroupAPI is applied to this prim."""
        return self.SCHEMA_NAME in self._get_api_schemas()

    @staticmethod
    def _get_api_schemas_from_prim(prim):
        """Get apiSchemas metadata directly (works for unregistered schemas)."""
        listOp = prim.GetMetadata('apiSchemas')
        if listOp:
            # Try explicitItems first, then prependedItems
            items = listOp.explicitItems
            if items:
                return list(items)
            items = listOp.prependedItems
            if items:
                return list(items)
            # Try GetAppliedItems if available
            if hasattr(listOp, 'GetAppliedItems'):
                items = listOp.GetAppliedItems()
                if items:
                    return list(items)
        return []

    def _get_api_schemas(self):
        return self._get_api_schemas_from_prim(self._prim)

    def GetLodItemsRel(self):
        """Get the lodItems relationship."""
        return self._prim.GetRelationship(self.REL_LOD_ITEMS) or \
               self._prim.CreateRelationship(self.REL_LOD_ITEMS)

    def SetLodItems(self, paths):
        """Set ordered LOD item paths (high → low detail)."""
        rel = self._prim.CreateRelationship(self.REL_LOD_ITEMS)
        rel.SetTargets([Sdf.Path(p) if isinstance(p, str) else p for p in paths])

    def GetLodItems(self):
        """Get ordered LOD item paths."""
        rel = self._prim.GetRelationship(self.REL_LOD_ITEMS)
        if rel:
            return rel.GetTargets()
        return []


class LodItemAPI:
    """Declares that a prim participates as a singular LOD item.

    Applied as a single-apply API schema.
    """

    SCHEMA_NAME = LOD_ITEM_API_NAME

    def __init__(self, stage, prim_path):
        self._stage = stage
        self._path = Sdf.Path(prim_path) if isinstance(prim_path, str) else prim_path
        self._prim = stage.GetPrimAtPath(self._path)

    @classmethod
    def Apply(cls, stage, prim_path):
        """Apply LodItemAPI to a prim."""
        path = Sdf.Path(prim_path) if isinstance(prim_path, str) else prim_path
        prim = stage.GetPrimAtPath(path)
        if not prim:
            raise ValueError(f"No prim at {path}")

        schemas = LodGroupAPI._get_api_schemas_from_prim(prim)
        if cls.SCHEMA_NAME not in schemas:
            schemas.append(cls.SCHEMA_NAME)
            prim.SetMetadata('apiSchemas', Sdf.TokenListOp.CreateExplicit(schemas))

        return cls(stage, path)

    def IsApplied(self):
        """Check if LodItemAPI is applied to this prim."""
        return self.SCHEMA_NAME in LodGroupAPI._get_api_schemas_from_prim(self._prim)


class LodDistanceHeuristicAPI:
    """Distance-based LOD selection heuristic.

    Multi-apply API schema (instance_name = domain, e.g. 'graphics').
    Stores min/max distance thresholds for hysteresis.

    Thresholds are in ascending order. For N items, there are N-1 thresholds.
    - Item 0 active when distance < threshold[0]
    - Item i active when threshold[i-1] <= distance < threshold[i]
    - Item N-1 active when distance >= threshold[N-2]
    """

    SCHEMA_NAME_PREFIX = 'LodDistanceHeuristicAPI'

    def __init__(self, stage, prim_path, instance_name):
        self._stage = stage
        self._path = Sdf.Path(prim_path) if isinstance(prim_path, str) else prim_path
        self._prim = stage.GetPrimAtPath(self._path)
        self._instance = instance_name
        self._ns = f'lod:Heuristic:{instance_name}:distance'

    @classmethod
    def Apply(cls, stage, prim_path, instance_name='graphics'):
        """Apply LodDistanceHeuristicAPI to a prim for a given domain."""
        path = Sdf.Path(prim_path) if isinstance(prim_path, str) else prim_path
        prim = stage.GetPrimAtPath(path)
        if not prim:
            raise ValueError(f"No prim at {path}")

        schema_name = f'{cls.SCHEMA_NAME_PREFIX}:{instance_name}'
        schemas = LodGroupAPI._get_api_schemas_from_prim(prim)
        if schema_name not in schemas:
            schemas.append(schema_name)
            prim.SetMetadata('apiSchemas', Sdf.TokenListOp.CreateExplicit(schemas))

        return cls(stage, path, instance_name)

    def _attr_name(self, suffix):
        return f'{self._ns}:{suffix}'

    def SetDistanceMinThresholds(self, thresholds):
        """Set min thresholds (used when transitioning from higher to lower LOD)."""
        attr = self._prim.CreateAttribute(
            self._attr_name('minThresholds'), Sdf.ValueTypeNames.FloatArray
        )
        attr.Set(thresholds)

    def GetDistanceMinThresholds(self):
        """Get min thresholds."""
        attr = self._prim.GetAttribute(self._attr_name('minThresholds'))
        if attr and attr.HasValue():
            return list(attr.Get())
        return []

    def SetDistanceMaxThresholds(self, thresholds):
        """Set max thresholds (used when transitioning from lower to higher LOD)."""
        attr = self._prim.CreateAttribute(
            self._attr_name('maxThresholds'), Sdf.ValueTypeNames.FloatArray
        )
        attr.Set(thresholds)

    def GetDistanceMaxThresholds(self):
        """Get max thresholds."""
        attr = self._prim.GetAttribute(self._attr_name('maxThresholds'))
        if attr and attr.HasValue():
            return list(attr.Get())
        return []

    def GetInstanceName(self):
        return self._instance
