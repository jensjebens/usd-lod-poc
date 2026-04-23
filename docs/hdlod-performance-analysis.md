# Performance Analysis: hdLod Scene Index Plugin

## Executive Summary

The current hdLod implementation is a **correct POC** that works well for small-to-medium scenes (dozens of LOD groups, hundreds of renderables). It will hit scaling walls at **production scale** (thousands of LOD groups, millions of renderables). The bottlenecks are well-understood and fixable without architectural changes.

---

## Current Complexity

### Per-frame: `_EvaluateLod()` — called every time camera moves

| Operation | Complexity | Notes |
|-----------|-----------|-------|
| Loop over `_lodGroups` | O(G) | G = number of LOD groups |
| Axiom 1 gating check | O(G × S) | S = size of `inactiveSubtrees` set, `HasPrefix()` per entry |
| `ComputeLocalToWorldTransform` per group | O(G × D) | D = depth of xform hierarchy — reads USD stage! |
| Distance + threshold selection | O(G × T) | T = number of thresholds (typically 1-3, negligible) |
| Insert hidden renderables | O(G × R_avg) | R_avg = average renderables per inactive item |
| Diff `_hiddenRenderables` (old vs new) | O(H) | H = total hidden renderables |
| `_SendPrimsDirtied` | O(Δ) | Δ = number of changed visibility states |

**Effective per-frame cost:** O(G × (S + D + R_avg))

For a scene with 100 LOD groups, 3 items each, ~10 renderables per item: ~3000 path operations per frame. Fine.

For ALAB with 235 physics bodies, if each had LOD: ~235 × (235 + depth + 50) ≈ ~67K operations. Starting to feel it.

### Per-GetPrim: visibility overlay

| Operation | Complexity | Notes |
|-----------|-----------|-------|
| `_hiddenRenderables.count(primPath)` | O(1) amortized | Hash set lookup |
| `_InvisibleDataSource::New()` | O(1) | Allocation per hidden prim per frame |
| Camera position check (lazy eval) | O(1) | Cached, only re-evaluates on position change |

**This is the hot path** — called for EVERY prim EVERY frame by Storm. The hash set lookup is fine. The `_InvisibleDataSource::New()` allocation is a concern at scale.

### Startup: `_RebuildGroupCache()`

| Operation | Complexity | Notes |
|-----------|-----------|-------|
| `_stage->Traverse()` | O(N) | N = all prims on stage |
| Per-group attribute scan | O(G × A) | A = attributes per group prim |
| `_CollectRenderables()` recursive walk | O(Σ subtree sizes) | Walks entire subtree per item |

Called once on scene load and on every `_PrimsAdded`. The full stage traverse + recursive descendant collection is the most expensive one-time cost.

---

## Bottleneck #1: `_RebuildGroupCache()` on every `_PrimsAdded`

**Severity: HIGH for interactive use**

```cpp
void HdLodSceneIndex::_PrimsAdded(...) {
    if (_stage) {
        _RebuildGroupCache();  // ← full stage traverse!
    }
    ...
    _SendPrimsAdded(entries);
}
```

Every time ANY prim is added (which happens frequently during scene loading, scrubbing, composition changes), we do a **full stage traverse** to rebuild the group cache. For ALAB (~50K prims), this is devastating during interactive use.

**Fix:** Incremental cache update — only process the added prim paths, check if they have `lod:lodItems`, add/update accordingly. Only rebuild descendants for affected items.

```cpp
void _PrimsAdded(...) {
    for (const auto &e : entries) {
        UsdPrim prim = _stage->GetPrimAtPath(e.primPath);
        if (prim && prim.GetRelationship(TfToken("lod:lodItems"))) {
            _UpdateGroupData(prim);  // incremental
        }
    }
}
```

---

## Bottleneck #2: `ComputeLocalToWorldTransform` per group per frame

**Severity: MEDIUM-HIGH**

```cpp
groupPos = xf.ComputeLocalToWorldTransform(
    UsdTimeCode::Default()).ExtractTranslation();
```

This reads the USD stage (not Hydra) and computes the full xform chain every frame for every LOD group. `ComputeLocalToWorldTransform` walks up the prim hierarchy concatenating matrices. For deeply nested scenes, this is expensive.

Worse: it uses `UsdTimeCode::Default()`, so it doesn't track animated group positions at all — a group that moves (e.g. a vehicle with LOD) won't get re-evaluated correctly.

**Fix:** Read the flattened xform from Hydra instead (like we do for the camera in `_UpdateCameraPosition`). The xform is already computed and cached by `HdFlatteningSceneIndex`:

```cpp
HdSceneIndexPrim groupPrim = _GetInputSceneIndex()->GetPrim(groupPath);
HdXformSchema xs = HdXformSchema::GetFromParent(groupPrim.dataSource);
if (xs.IsDefined()) {
    groupPos = xs.GetMatrix()->GetTypedValue(0.0f).ExtractTranslation();
}
```

This eliminates the USD stage read entirely and handles animated groups.

---

## Bottleneck #3: Axiom 1 gating — linear scan of `inactiveSubtrees`

**Severity: LOW-MEDIUM (scales with nesting depth)**

```cpp
for (const auto &is : inactiveSubtrees)
    if (groupPath.HasPrefix(is)) { skip = true; break; }
```

For each LOD group, we scan ALL inactive subtrees and call `HasPrefix()` (string prefix comparison). With G groups and S inactive subtrees, this is O(G × S). In a deeply nested scene with many inactive branches, S grows linearly.

**Fix:** Sort groups by path depth and process top-down. Once a parent is gated, skip all descendants without checking `inactiveSubtrees`:

```cpp
// Sort _lodGroups by path (depth-first order, guaranteed by SdfPath comparison)
// Then: if a group is gated, all children with that prefix are automatically skipped
```

Or use a trie/prefix tree for O(D) lookup (D = path depth) instead of O(S).

---

## Bottleneck #4: `_InvisibleDataSource::New()` per hidden prim per `GetPrim()` call

**Severity: LOW-MEDIUM at scale**

```cpp
if (_hiddenRenderables.count(primPath) && prim.dataSource) {
    prim.dataSource = _InvisibleDataSource::New(prim.dataSource);
}
```

Every `GetPrim()` call for a hidden renderable allocates a new `_InvisibleDataSource`. In a typical frame, Storm calls `GetPrim()` multiple times per prim (for different data source queries). For 10K hidden renderables × ~3 calls each = 30K allocations per frame.

The visibility container itself is a `static` singleton (good), but the wrapper `_InvisibleDataSource` is fresh each time.

**Fix:** Cache `_InvisibleDataSource` instances per path:

```cpp
std::unordered_map<SdfPath, HdContainerDataSourceHandle, SdfPath::Hash>
    _invisibleDataSourceCache;
```

Or use a single shared `_InvisibleDataSource` that looks up the input on demand.

---

## Bottleneck #5: `_PrimsDirtied` triggers LOD eval on ANY xform dirty

**Severity: MEDIUM for physics-heavy scenes**

```cpp
for (const auto &e : entries) {
    if (e.dirtyLocators.Contains(HdXformSchema::GetDefaultLocator())) {
        xformDirty = true;
        break;
    }
}
if (xformDirty && !_cameraPath.IsEmpty()) {
    _UpdateCameraPosition();
    _EvaluateLod();
}
```

Any xform dirty signal (a physics body moving, a character animating, anything) triggers a full LOD re-evaluation. In a Newton physics scene with 235 bodies, every physics step fires 235 xform dirty entries, and each one triggers `_EvaluateLod()` — but only the camera position matters for LOD.

**Fix:** Only re-evaluate when the camera position actually changed:

```cpp
_UpdateCameraPosition();
if (_cachedCameraPos != _prevCameraPos) {
    _EvaluateLod();
    _prevCameraPos = _cachedCameraPos;
}
```

(The lazy `GetPrim()` path already has this check, but `_PrimsDirtied` doesn't.)

---

## Bottleneck #6: `_CollectRenderables` recursive walk

**Severity: MEDIUM at startup, for large subtrees**

```cpp
void _CollectRenderables(const SdfPath &path, std::vector<SdfPath> &out) const {
    const auto &input = _GetInputSceneIndex();
    HdSceneIndexPrim p = input->GetPrim(path);
    if (_IsRenderable(p.primType)) out.push_back(path);
    for (const SdfPath &c : input->GetChildPrimPaths(path))
        _CollectRenderables(c, out);
}
```

For each LOD item, we recursively walk its entire Hydra subtree. For a complex LOD item (e.g. a detailed vehicle with 500 meshes), this walks all 500 paths. With 3 items × 100 groups = 300 subtree walks.

**Fix:** Walk lazily or incrementally. Or maintain the descendant cache via `_PrimsAdded`/`_PrimsRemoved` instead of rebuilding from scratch.

---

## What's Already Good

1. **Visibility overlay is O(1) per prim** — hash set lookup, static singleton for the visibility data source
2. **Batch dirty** — collects all changes, diffs against previous state, only dirties the delta
3. **Hysteresis** — prevents thrashing at boundaries (no wasted GPU work from flickering)
4. **Reentrancy guard** — prevents infinite GetPrim→evaluate→dirty→render→GetPrim loops
5. **Camera position caching** — only re-evaluates when position actually changes (in GetPrim path)
6. **Axiom 1 gating** — correctly skips evaluation of entire sub-hierarchies

---

## Scaling Estimates

| Scene size | Groups | Hidden renderables | Per-frame cost | Verdict |
|-----------|--------|-------------------|----------------|---------|
| Demo (current) | 2 | ~5 | <0.01ms | ✅ Trivial |
| Small game level | 50 | ~500 | ~0.1ms | ✅ Fine |
| ALAB-scale | 200 | ~5K | ~1-2ms | ⚠️ OK but tight |
| Open world | 2K | ~50K | ~10-20ms | ❌ Needs optimization |
| Film city (nested) | 10K | ~200K | ~100ms+ | ❌ Needs redesign |

The main cost driver at scale is `ComputeLocalToWorldTransform` (bottleneck #2) and `_RebuildGroupCache` (bottleneck #1). Fix those two and the open-world tier becomes feasible.

---

## Priority Order for Optimization

1. **#2: Read xform from Hydra, not USD** — biggest win, simplest fix, also fixes animated groups
2. **#5: Only re-evaluate on camera change** — trivial fix, big win for physics scenes
3. **#1: Incremental cache rebuild** — critical for interactive editing
4. **#4: Cache _InvisibleDataSource** — moderate win at scale
5. **#3: Sort groups for Axiom 1** — niche win for deeply nested scenes
6. **#6: Incremental descendant tracking** — startup optimization

---

## Not Covered (Future Considerations)

- **Screen-space LOD heuristic** (`LodScreenSizeHeuristicAPI`) — needs bounding box + projection matrix, more expensive than distance
- **Multi-threaded evaluation** — `_EvaluateLod` is single-threaded; TBB parallelism for large group counts
- **Spatial indexing** — BVH/octree for "which groups are near the camera" instead of evaluating all groups
- **LOD transition blending** — cross-fade or dithered transitions (GPU cost, not CPU)
- **Multi-camera** — VR/multi-viewport needs per-camera LOD state, not a single `_cachedCameraPos`
