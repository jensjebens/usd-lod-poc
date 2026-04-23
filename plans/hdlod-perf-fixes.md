# hdLod Performance Fix Plan

## Context

Performance analysis (`docs/hdlod-performance-analysis.md`) identified 4 key bottlenecks.
Newton reviewed from HdExec experience (ALAB scale, 16 bodies + ~471 prims).
This plan captures Newton's recommendations and our implementation approach.

## Issues

| # | Title | Priority | Effort |
|---|-------|----------|--------|
| #41 | Read xforms from Hydra, not USD stage | P0 | Small |
| #42 | Camera-change guard for dirty signals | P0 | Small |
| #40 | Incremental cache rebuild | P1 | Medium |
| #43 | Singleton _InvisibleDataSource | P1 | Small |

---

## Fix 1: Read xforms from Hydra (#41)

**Newton's pattern** (from HdExec ancestor walk):
```cpp
HdSceneIndexPrim groupPrim = _GetInputSceneIndex()->GetPrim(groupPath);
HdXformSchema xs = HdXformSchema::GetFromParent(groupPrim.dataSource);
if (xs.IsDefined()) {
    groupPos = xs.GetMatrix()->GetTypedValue(0).ExtractTranslation();
}
```

**Key learnings from Newton:**
- `GetTypedValue(0)` — the `0` is a **shutter offset**, NOT a USD time code. `0` = current frame.
- Read from `_GetInputSceneIndex()` (upstream), NOT from `this->GetPrim()` — avoids recursion into our own overlay.
- The flattened matrix already reflects whatever time `UsdImagingStageSceneIndex::SetTime()` set.
- This also **fixes animated LOD groups** (vehicles, characters) for free — no more stale `UsdTimeCode::Default()`.

**Change:** Replace `ComputeLocalToWorldTransform` in `_EvaluateLod()` with Hydra read.
Keep USD stage fallback only for `_UpdateCameraPosition()` initial-load path.

---

## Fix 2: Camera-change guard (#42)

**Newton's recommendation:** Two-tier approach.

**Tier 1 — Camera guard (easy):**
```cpp
void HdLodSceneIndex::_PrimsDirtied(...) {
    if (xformDirty && !_cameraPath.IsEmpty()) {
        GfVec3d prevPos = _cachedCameraPos;
        _UpdateCameraPosition();
        if ((_cachedCameraPos - prevPos).GetLength() > 1e-6) {
            _EvaluateLod();
        }
    }
}
```

**Tier 2 — Moving LOD groups (future):**
On `_PrimsDirtied`, check if any dirtied xform path is a prefix of a LOD group path.
If so, mark that specific group for re-evaluation. Most frames in a static scene = zero re-evals.

```cpp
// In _PrimsDirtied, after checking camera:
for (const auto &e : entries) {
    if (e.dirtyLocators.Contains(HdXformSchema::GetDefaultLocator())) {
        for (const auto &[gp, gd] : _lodGroups) {
            if (gp.HasPrefix(e.primPath) || e.primPath.HasPrefix(gp)) {
                _groupsDirty.insert(gp);
            }
        }
    }
}
if (!_groupsDirty.empty()) {
    _EvaluateLod();  // only re-evaluate dirty groups
    _groupsDirty.clear();
}
```

**Newton's insight:** HdExec uses `UniversalSet()` (dirty everything) because they have few bodies.
LOD should be smarter because we're camera-driven, not simulation-driven.

---

## Fix 3: Incremental cache rebuild (#40)

**Newton's pattern** (from HdExec `_hasComputationCache`):
- `_PrimsAdded`: evict added paths from cache, don't rebuild
- `_PrimsRemoved`: evict removed paths
- Lazy rebuild on next `GetPrim()` / `_EvaluateLod()`

**Our approach:**
1. `_RebuildGroupCache()` runs ONCE on first `_PrimsAdded` (the big scene-load batch)
2. Subsequent `_PrimsAdded`: only check if added paths have `lod:lodItems` → add to `_lodGroups`
3. `_descendantCache`: invalidate entries whose item path is a prefix of any added path
4. Lazy re-collect renderables on next `_EvaluateLod()` when a cache entry is missing

```cpp
void _PrimsAdded(...) {
    for (const auto &e : entries) {
        // Check if this is a new LOD group
        if (_stage) {
            UsdPrim p = _stage->GetPrimAtPath(e.primPath);
            if (p) {
                UsdRelationship rel = p.GetRelationship(TfToken("lod:lodItems"));
                if (rel && rel.HasAuthoredTargets()) {
                    _UpdateSingleGroupData(p);
                }
            }
        }
        // Invalidate descendant cache for affected items
        for (auto it = _descendantCache.begin(); it != _descendantCache.end();) {
            if (e.primPath.HasPrefix(it->first)) {
                it = _descendantCache.erase(it);
            } else {
                ++it;
            }
        }
    }
    // ... camera discovery + LOD eval as before ...
}
```

---

## Fix 4: Singleton _InvisibleDataSource (#43)

**Newton's recommendation:** All invisible prims get the same visibility value (`false`).
Create ONE wrapper, reuse for all.

**Current:** `_InvisibleDataSource::New(prim.dataSource)` wraps each prim's data source individually
(because it delegates non-visibility queries to `_input`).

**Problem:** Can't share a single instance because `_input` differs per prim.

**Solution:** Don't wrap the whole prim. Use `HdOverlayContainerDataSource` to overlay just the visibility:

```cpp
static HdContainerDataSourceHandle sInvisVis =
    HdRetainedContainerDataSource::New(
        HdVisibilitySchemaTokens->visibility,
        HdRetainedContainerDataSource::New(
            HdVisibilitySchemaTokens->visibility,
            HdRetainedTypedSampledDataSource<bool>::New(false)));

// In GetPrim:
if (_hiddenRenderables.count(primPath) && prim.dataSource) {
    prim.dataSource = HdOverlayContainerDataSource::New(sInvisVis, prim.dataSource);
}
```

`HdOverlayContainerDataSource` checks the first source for a key, falls back to the second.
The visibility overlay is a static singleton. The overlay itself is one allocation per call,
but it's a lightweight container (two pointers, no deep copy).

This is Newton's pattern from HdExec:
```cpp
prim.dataSource = HdOverlayContainerDataSource::New(xformOverlay, prim.dataSource);
```

---

## Implementation Order

1. **#41 + #42 together** — both touch `_EvaluateLod` and `_PrimsDirtied`, small changes, biggest win
2. **#43** — simple refactor of GetPrim overlay, independent
3. **#40** — more involved refactor of `_PrimsAdded` + cache management

## Testing

- Existing 18 Python + 5 C++ pipeline tests must still pass
- Add timing test: create scene with 500 LOD groups, measure `_EvaluateLod` time before/after
- Profile with ALAB scene (if feasible) to validate at production scale
