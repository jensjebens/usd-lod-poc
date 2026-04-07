# MEMORY.md - LOD Long-Term Memory

## Project Overview
- USD Level of Detail — implementing the Pixar LOD proposal as a Hydra scene index plugin
- GitHub repos:
  - POC + tests + demos: https://github.com/jensjebens/usd-lod-poc
  - OpenUSD fork (fixes + plugins): https://github.com/jensjebens/OpenUSD
- ALAB scene: `/home/horde/.openclaw/workspace-alab/alab/ALab-2.3.0/ALab/entry.usda`

## Key Builds
- **Clean fork build** (April 7): `/tmp/usd-fork-clean-build/` (Python 3.10, from-source, consistent ABI)
  - Source: `/tmp/usd-visapi-investigation/` on branch `poc/lod-proposal`
  - Includes: purpose visibility fix (PR #8) + hdLod scene index plugin
  - UsdView: `python3 /tmp/usd-fork-clean-build/bin/usdview`
- **Vanilla USD v26.03**: `/tmp/usd-vanilla-build/` (stock release, no fork changes)
  - Used for issue #22 investigation (confirmed xform reads work on vanilla)
- **Stock NVIDIA v25.08 binaries**: `/home/horde/.openclaw/workspace-alab/usd-bin/usd-v25.08/` (Python 3.12)
  - Does NOT have our fixes
- **⚠️ OLD build (ABI broken)**: `/tmp/usd-purpose-vis-build/` — DO NOT USE, partial rebuild corrupted ABI

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

### hdLod Hydra Scene Index Plugin (Issue #18) — COMPLETE ✅
- **Issue**: https://github.com/jensjebens/OpenUSD/issues/18 — CLOSED
- **Code**: `pxr/imaging/hdLod/` on `poc/lod-proposal` branch
- **Build**: compiles and installs as `libusd_hdLod.so`, auto-loads via Hybrid plugin ordering
- C++ scene index filter (`HdSingleInputFilteringSceneIndexBase`)
- `_InvisibleDataSource`: wraps prim data source, overrides visibility to false (thread-safe static singleton)
- `_descendantCache`: maps LodItem → renderable descendants (handles parent Xform items)
- `_EvaluateLod()`: camera distance, threshold selection, hysteresis state, batch dirty
- Hierarchical evaluation with inactive subtree gating
- Plugin registered at phase 0 for all renderers
- **Live UsdView demo**: red sphere → green cube → blue cube during playback
- **Commits**: b851e26 → 0be748c (10 commits on poc/lod-proposal)

### Issue #22 (xform GetTypedValue crash) — CLOSED ✅
- **Root cause**: ABI mismatch from partial rebuild of `libusd_hd.so` (HD_API_VERSION 95→97)
- NOT a bug in `_MatrixCombinerDataSource` or the flattening pipeline
- Vanilla USD v26.03 and clean fork build both pass `GetTypedValue(0.0f)` without crash
- Reverted unnecessary null-check commit (52e98b2)
- **Lesson**: Never partially rebuild USD when `hd/dataSource.h` changes

### Issue #25 (UsdView playback LOD re-evaluation) — CLOSED ✅
- UsdView's `_PrimsDirtied` doesn't propagate to scene index plugins during playback
  (only fires for prims with registered time-varying locators via `FlagAsTimeVarying()`)
- **Fix 1** (Newton's pattern): check ANY xform dirty signal in `_PrimsDirtied`, no path filtering
- **Fix 2** (Newton's Option 4): lazy `GetPrim()` evaluation — read camera xform from Hydra on
  each render pass, re-evaluate LOD if position changed
- Reentrancy guard prevents infinite loop (_EvaluateLod → dirty → render → GetPrim → evaluate)
- `usdviewApi.frame` is read-only in from-source builds; use `ac.setFrame()` or Space bar

### Key Rendering/Capture Lessons (April 7)
- `grabFrameBuffer()` returns stale GL content when multiple UsdView instances run
- `x11grab` CAN capture OpenGL viewport via VNC, but ONLY with a single UsdView instance
- Never run multiple UsdView instances on the same VNC display
- `scrot -u` captures the window frame but not GL content on VNC
- `usdrecord` works reliably for frame-by-frame capture with hdLod plugin loaded

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
| #17 | LOD Proposal POC + hdLod plugin | poc/lod-proposal | OPEN |

## Open Issues (relevant to LOD)
- #7: Purpose visibility not consumed by Hydra (our fix in PR #8)
- #15: VisibilityAPI attrs should be non-uniform (blocks purpose-based LOD switching)
- #19: Newton dual USD runtime crash (workaround: remove bundled usd-core)
- #24: Upstream engagement: key Pixar developers

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
- **Never partially rebuild USD** — HD_API_VERSION bump requires full rebuild of ALL dependent libs
- **HdVisibilitySchema::Builder::Build() is NOT thread-safe** in TBB contexts — use HdRetainedContainerDataSource::New() directly
- **Single UsdView instance on VNC** — multiple instances corrupt GL compositing, x11grab captures garbage
- **`usdviewApi.frame` is read-only** in from-source builds — use `ac.setFrame()` or Space bar
- **`_PrimsDirtied` doesn't fire during UsdView playback** unless prims have time-varying locators — use lazy GetPrim() evaluation instead
- **x11grab CAN capture OpenGL on VNC** but only with a single GL context active
