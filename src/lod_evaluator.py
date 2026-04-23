"""
lod_evaluator.py — LOD Proposal POC: Runtime LOD selection

Evaluates LOD heuristics and selects the active item per group.
Respects hierarchical evaluation (Axiom 1) and hysteresis.

Based on: https://github.com/PixarAnimationStudios/OpenUSD-proposals/pull/81
"""

from pxr import Usd, UsdGeom, Sdf, Gf

from usd_lod import LodGroupAPI, LodItemAPI, LodDistanceHeuristicAPI


def _compute_item_center(stage, item_path):
    """Compute world-space center of an LOD item.

    Uses the item's bounding box center. Falls back to world-space
    translation if no geometry exists.
    """
    prim = stage.GetPrimAtPath(item_path)
    if not prim:
        return Gf.Vec3d(0, 0, 0)

    # Try to get the xform
    xformable = UsdGeom.Xformable(prim)
    if xformable:
        world_xform = xformable.ComputeLocalToWorldTransform(Usd.TimeCode.Default())
        return world_xform.ExtractTranslation()

    return Gf.Vec3d(0, 0, 0)


def _compute_group_center(stage, group_path, item_paths):
    """Compute the center of an LOD group.

    Uses the group prim's world-space position, or the first item's center.
    """
    prim = stage.GetPrimAtPath(group_path)
    if prim:
        xformable = UsdGeom.Xformable(prim)
        if xformable:
            world_xform = xformable.ComputeLocalToWorldTransform(
                Usd.TimeCode.Default()
            )
            pos = world_xform.ExtractTranslation()
            if pos.GetLength() > 1e-6:
                return pos

    # Fall back to first item center
    if item_paths:
        return _compute_item_center(stage, item_paths[0])

    return Gf.Vec3d(0, 0, 0)


def _find_distance_heuristic(stage, group_path):
    """Find a LodDistanceHeuristicAPI on a group prim.

    Searches applied schemas for any LodDistanceHeuristicAPI instance.
    Returns (instance_name, min_thresholds, max_thresholds) or None.
    """
    prim = stage.GetPrimAtPath(group_path)
    if not prim:
        return None

    schemas = LodGroupAPI._get_api_schemas_from_prim(prim)
    for schema in schemas:
        if schema.startswith(LodDistanceHeuristicAPI.SCHEMA_NAME_PREFIX + ':'):
            instance = schema.split(':')[1]
            h = LodDistanceHeuristicAPI(stage, group_path, instance)
            min_t = h.GetDistanceMinThresholds()
            max_t = h.GetDistanceMaxThresholds()
            if min_t:
                return (instance, min_t, max_t if max_t else min_t)

    return None


def _select_lod_index(distance, min_thresholds, max_thresholds, prev_index=None):
    """Select LOD index based on distance and thresholds with hysteresis.

    For N items, there are N-1 thresholds.
    - Index 0: distance < threshold[0]
    - Index i: threshold[i-1] <= distance < threshold[i]
    - Index N-1: distance >= threshold[N-2]

    Hysteresis:
    - To move to HIGHER index (less detail): use MAX thresholds
    - To move to LOWER index (more detail): use MIN thresholds
    This creates a dead zone between min and max where the previous state holds.
    """
    n_thresholds = len(min_thresholds)

    if prev_index is None:
        # No previous state — use min thresholds (standard evaluation)
        for i, t in enumerate(min_thresholds):
            if distance < t:
                return i
        return n_thresholds  # last item

    # With hysteresis — determine what index we'd be at using each threshold set
    # Use max thresholds to check if we should go UP (to higher index / less detail)
    # Use min thresholds to check if we should go DOWN (to lower index / more detail)

    # What index would max thresholds give? (for going UP from current)
    max_index = n_thresholds
    for i, t in enumerate(max_thresholds):
        if distance < t:
            max_index = i
            break

    # What index would min thresholds give? (for going DOWN from current)
    min_index = n_thresholds
    for i, t in enumerate(min_thresholds):
        if distance < t:
            min_index = i
            break

    # If max says go higher than current, go higher (use max thresholds)
    if max_index > prev_index:
        return max_index

    # If min says go lower than current, go lower (use min thresholds)
    if min_index < prev_index:
        return min_index

    # Otherwise stay at current (we're in the hysteresis dead zone)
    return prev_index


def _find_all_lod_groups(stage):
    """Find all prims with LodGroupAPI applied, in depth-first order."""
    groups = []
    for prim in stage.Traverse():
        schemas = LodGroupAPI._get_api_schemas_from_prim(prim)
        if LodGroupAPI.SCHEMA_NAME in schemas:
            groups.append(prim.GetPath())
    return groups


def evaluate_lod(stage, camera_pos, prev_state=None):
    """Evaluate LOD for all groups in the stage.

    Args:
        stage: USD stage
        camera_pos: Gf.Vec3d camera world position
        prev_state: dict of {group_path: active_index} from previous frame

    Returns:
        dict of {group_path: active_index}

    Implements hierarchical evaluation (Axiom 1): child groups are only
    evaluated if their parent group's active item contains them.
    """
    if prev_state is None:
        prev_state = {}

    result = {}
    inactive_subtrees = set()  # paths whose children should be skipped

    for group_path in _find_all_lod_groups(stage):
        # Axiom 1: skip if inside an inactive subtree
        skip = False
        for inactive_path in inactive_subtrees:
            if group_path.HasPrefix(inactive_path):
                skip = True
                break
        if skip:
            continue

        group = LodGroupAPI(stage, group_path)
        item_paths = group.GetLodItems()
        if not item_paths:
            continue

        # Find heuristic
        heuristic = _find_distance_heuristic(stage, group_path)
        if not heuristic:
            # No heuristic — default to first item
            result[group_path] = 0
            continue

        instance, min_t, max_t = heuristic

        # Compute distance from camera to group center
        center = _compute_group_center(stage, group_path, item_paths)
        distance = (camera_pos - center).GetLength()

        # Select LOD index
        prev_idx = prev_state.get(group_path)
        active_idx = _select_lod_index(distance, min_t, max_t, prev_idx)
        result[group_path] = active_idx

        # Mark non-active item subtrees as inactive (Axiom 1)
        for i, item_path in enumerate(item_paths):
            if i != active_idx:
                inactive_subtrees.add(item_path)

    return result


def apply_lod_visibility(stage, lod_result):
    """Apply LOD evaluation results as visibility on the stage.

    Active items get visibility="inherited", non-active get "invisible".
    Items belonging to gated groups (Axiom 1 — parent inactive) are also
    set to invisible.

    Args:
        stage: USD stage
        lod_result: dict from evaluate_lod()
    """
    # Collect inactive subtrees from evaluated groups
    inactive_subtrees = set()
    for group_path, active_idx in lod_result.items():
        group = LodGroupAPI(stage, group_path)
        item_paths = group.GetLodItems()
        for i, item_path in enumerate(item_paths):
            if i != active_idx:
                inactive_subtrees.add(item_path)

    # Apply visibility for evaluated groups
    for group_path, active_idx in lod_result.items():
        group = LodGroupAPI(stage, group_path)
        item_paths = group.GetLodItems()

        for i, item_path in enumerate(item_paths):
            prim = stage.GetPrimAtPath(item_path)
            if not prim:
                continue

            img = UsdGeom.Imageable(prim)
            if not img:
                continue

            if i == active_idx:
                img.GetVisibilityAttr().Set('inherited')
            else:
                img.GetVisibilityAttr().Set('invisible')

    # Hide items of gated groups (groups inside inactive subtrees)
    for group_path in _find_all_lod_groups(stage):
        if group_path in lod_result:
            continue  # already handled above

        # Check if this group is inside an inactive subtree
        gated = False
        for inactive_path in inactive_subtrees:
            if group_path.HasPrefix(inactive_path):
                gated = True
                break
        if not gated:
            continue

        # All items of a gated group should be invisible
        group = LodGroupAPI(stage, group_path)
        for item_path in group.GetLodItems():
            prim = stage.GetPrimAtPath(item_path)
            if not prim:
                continue
            img = UsdGeom.Imageable(prim)
            if img:
                img.GetVisibilityAttr().Set('invisible')
