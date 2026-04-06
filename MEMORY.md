# MEMORY.md - LOD Long-Term Memory

## Project Overview
- USD Level of Detail — implementing the Pixar LOD proposal as a Hydra scene index plugin
- GitHub repos:
  - POC + tests + demos: https://github.com/jensjebens/usd-lod-poc
  - OpenUSD fork (fixes + plugins): https://github.com/jensjebens/OpenUSD
- ALAB scene: `/home/horde/.openclaw/workspace-alab/alab/ALab-2.3.0/ALab/entry.usda`

## Key Builds
- **Purpose-visibility fixed USD build**: `/tmp/usd-purpose-vis-build/` (Python 3.10, built from source)
  - Source: `/tmp/usd-visapi-investigation/` on branch `fix/purpose-visibility-in-hydra`
  - Includes: purpose visibility fix (PR #8) + hdLod scene index plugin
  - UsdView: `python3 /tmp/usd-purpose-vis-build/bin/usdview`
- **Stock NVIDIA v25.08 binaries**: `/home/horde/.openclaw/workspace-alab/usd-bin/usd-v25.08/` (Python 3.12)
  - Does NOT have our fixes

## Completed Work

### Purpose-Specific Visibility Fix (PR #8) ✅
- **Issue**: https://github.com/jensjebens/OpenUSD/issues/7
- **PR**: https://github.com/jensjebens/OpenUSD/pull/8 — OPEN, all 12 tests passing
- **Branch**: `fix/purpose-visibility-in-hydra`
- Root cause: `UsdImagingDataSourcePrim` never reads VisibilityAPI purpose attrs
- Fix across 4 layers: HdVisibilitySchema, UsdImagingDataSourcePrim, HdFlattenedVisibilityDataSourceProvider, GetVisible() + render pass plugins
- Demo screenshots in PR showing UsdView with purpose visibility working
- **Gotcha**: Runtime VisibilityAPI changes via interpreter don't propagate dirty signals — attrs must be authored in USDA before load

### Issue #9 (VisibilityAPI demo screenshots) — CLOSED ✅
### Issue #15 (uniform visibility attrs should be animatable) — OPEN
- `renderVisibility`/`proxyVisibility`/`guideVisibility` are `uniform token` — can't animate
- Blocks LOD switching via purpose visibility; must use base `visibility` instead

### LOD Proposal POC (PR #17, Issue #16) ✅
- **PR**: https://github.com/jensjebens/OpenUSD/pull/17 — OPEN
- **Branch**: `poc/lod-proposal`
- Implements Pixar LOD proposal (https://github.com/PixarAnimationStudios/OpenUSD-proposals/pull/81)
- Python schema: `LodGroupAPI`, `LodItemAPI`, `LodDistanceHeuristicAPI`
- Python evaluator: distance-based selection, hysteresis (min/max thresholds), hierarchical evaluation (Axiom 1)
- 12/12 tests passing
- 100-frame animated demo GIF (camera dolly-out with LOD switching)
- Static frame-by-frame approach: evaluate → set visibility → usdrecord render

### hdLod Hydra Scene Index Plugin (Issue #18) — IN PROGRESS
- **Issue**: https://github.com/jensjebens/OpenUSD/issues/18
- **Code**: `pxr/imaging/hdLod/` on `poc/lod-proposal` branch
- **Build**: compiles and installs cleanly as `libusd_hdLod.so`
- C++ scene index filter (`HdSingleInputFilteringSceneIndexBase`)
- `_InvisibleDataSource`: wraps prim data source, overrides visibility to false
- `_descendantCache`: maps LodItem → renderable descendants (handles parent Xform items)
- `_EvaluateLod()`: camera distance, threshold selection, hysteresis state, batch dirty
- Hierarchical evaluation with inactive subtree gating
- Plugin registered at phase 0 for all renderers
- **Not yet tested in UsdView** — next step

## Architecture — Scene Index Chain

From 3-agent investigation (Newton + Units + LOD):
```
 1. UsdImagingStageSceneIndex (LOCAL data from USD)
 6.   └─ HdFlatteningSceneIndex ← flattens local→world
 9. AppendSceneIndicesForRenderer ← PLUGIN INSERTION
10.   └─ HdLodSceneIndex (LOD — our plugin)
11.   └─ HdExecComputedTransformSceneIndex (Newton physics)
12. HdCachingSceneIndex
13. Storm
```

### Critical Design Decisions
- **Post-flattening** (steps 9-11) — need world-space positions for distance calc
- **Descendant walk** required — LodItems are typically parent Xforms, not direct renderables; visibility overlay on parent doesn't affect already-flattened children
- **Base `visibility`** for LOD switching (not purpose-specific — those are `uniform`)
- **Batch dirty** — collect all LOD changes per frame, dirty once
- LOD runs BEFORE Newton (step 10 vs 11) so physics sees LOD state

## Cross-Repo PRs (jensjebens/OpenUSD)
| PR | Title | Branch | Status |
|----|-------|--------|--------|
| #8 | Purpose-specific visibility fix | fix/purpose-visibility-in-hydra | DRAFT |
| #10 | MetricsAPI Core | jjebens/metrics-api-core | OPEN |
| #11 | Units API | jjebens/units-api-poc | OPEN |
| #12 | OpenExec Units | jjebens/units-aware-value-resolution | OPEN |
| #13 | Newton GPU Physics | feature/newton-gpu-integration | OPEN |
| #17 | LOD Proposal POC | poc/lod-proposal | OPEN |

## Open Issues (relevant to LOD)
- #7: Purpose visibility not consumed by Hydra (our fix in PR #8)
- #15: VisibilityAPI attrs should be non-uniform (blocks purpose-based LOD switching)
- #16: LOD Proposal POC (delivered)
- #18: LOD Phase 2 Hydra scene index (hdLod compiles, needs UsdView testing)
- #19: Newton dual USD runtime crash (workaround: remove bundled usd-core)

## Collaborators
- **Newton**: Storm/Hydra pipeline, HdExec scene index, physics LOD use case (ALAB 235 bodies), ancestor walk pattern. Found dual USD runtime crash (#19).
- **Units**: Scene index chain architecture expert, schema patterns, reviewed flattening gotchas, offered to review hdLod filter
- **Alab**: ALAB scene setup knowledge

## Phase 1 Work (from April 5)
- Cone angle metric (radius/distance) for screen-space LOD heuristic
- Hysteresis dead zone prevents flickering
- 18 tests passing for heuristics
- Kit headless pipeline: compute in Kit → render with usdrecord
- Maps to `LodScreenSizeHeuristicAPI` in the Pixar proposal

## Key File Locations
| File | Description |
|------|-------------|
| `src/usd_lod.py` | Python LOD schema helpers |
| `src/lod_evaluator.py` | Python LOD evaluator with hysteresis |
| `src/lod_heuristics.py` | Phase 1 cone angle heuristics |
| `tests/test_lod_proposal.py` | 12 LOD proposal tests |
| `tests/test_purpose_visibility_hydra.py` | 12 purpose visibility tests |
| `plans/lod-proposal-poc.md` | LOD POC plan |
| `demo/lod_proposal_demo.gif` | Animated LOD switching demo |
| `demo/vis_ss1_final.png` → `vis_ss3_final.png` | Purpose visibility UsdView screenshots |

## Lessons Learned
- Unregistered API schemas: `GetAppliedSchemas()` filters them out — must read `apiSchemas` metadata directly via `prim.GetMetadata('apiSchemas').explicitItems`
- UsdView interpreter: `exit()` kills the whole app — toggle with `i` key or close via wmctrl
- `usdrecord --defaultTime` for single-frame capture (not `--frames 0:0`)
- `scrot -u` + `wmctrl -i -a <wid>` for focused window screenshots
- PyOpenGL needed for python3.12 UsdView: `python3.12 -m pip install PyOpenGL PyOpenGL-accelerate`
- plugInfo.json template variables: `@PLUG_INFO_LIBRARY_PATH@` etc must be resolved for manual installs
