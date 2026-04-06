# Plan: LOD Proposal POC

**Issue:** https://github.com/jensjebens/OpenUSD/issues/16
**Branch:** `poc/lod-proposal`
**Proposal:** https://github.com/PixarAnimationStudios/OpenUSD-proposals/pull/81

## Motivation

Pixar's LOD proposal (PR #81) defines a schema for Level of Detail management in USD. It introduces:

- **LodGroupAPI** — marks a prim as an LOD group with ordered items
- **LodItemAPI** — marks a prim as a selectable LOD representation
- **LodHeuristicAPI** — defines selection logic (distance, screen-size, etc.)

No implementation exists yet. This POC proves the schema works end-to-end: author LOD data in USD, evaluate heuristics at runtime, switch LOD items in Hydra.

## Acceptance Criteria

1. **Schema definition**: Python module implementing `LodGroupAPI`, `LodItemAPI`, `LodDistanceHeuristicAPI` as applied API schemas (using `Usd.SchemaBase` patterns or pure attribute authoring)
2. **Sample stage**: USDA file with a multi-LOD object (3 levels: high=Sphere, mid=low-poly Mesh, low=Cube) with distance thresholds and hysteresis
3. **LOD evaluator**: Python function that, given a camera position and stage, returns which LOD item is active for each group — respecting:
   - Distance-based thresholds (min/max for hysteresis)
   - Hierarchical evaluation (Axiom 1: child only active if parent active)
   - Domain independence (Axiom 2: geometry domain only for POC)
4. **Hydra scene index integration**: A scene index filter (Python or C++) that consumes the LOD schema and hides/shows LOD items by setting visibility
5. **Visual demo**: Animated rendering (GIF or UsdView capture) showing LOD switching as camera moves
6. **Tests**: All pass, covering schema authoring, evaluator logic, edge cases

## Approach

### Phase A: Schema + Evaluator (Python)

1. Define helper module `usdLod.py` that:
   - Applies `LodGroupAPI` attributes to a prim (`lodItems` relationship, etc.)
   - Applies `LodItemAPI` to item prims
   - Applies `LodDistanceHeuristicAPI` with `distanceMinThresholds` / `distanceMaxThresholds`
2. Write `lod_evaluator.py`:
   - `evaluate_lod(stage, camera_pos, prev_state=None)` → returns `{group_path: active_item_index}`
   - Implements distance-from-camera to item center/bbox
   - Hysteresis: uses min thresholds for downgrade, max thresholds for upgrade
   - Hierarchical: walks groups top-down
3. Write tests first (TDD):
   - Test schema application and round-trip
   - Test evaluator with known distances → expected LOD selections
   - Test hysteresis prevents oscillation
   - Test hierarchical: nested groups respect parent activation

### Phase B: Sample Stage

1. Create `lod_proposal_demo.usda` with:
   - `/World/Vehicle` — LodGroup with 3 items:
     - `/World/Vehicle/HighDetail` — Sphere (red), LodItem
     - `/World/Vehicle/MedDetail` — low-poly mesh (green), LodItem  
     - `/World/Vehicle/LowDetail` — Cube (blue), LodItem
   - Distance heuristic: thresholds [5, 15, 30], hysteresis ±2
   - Camera that dollies out from 2 to 50 units
2. Ground plane + materials for visual clarity

### Phase C: Hydra Integration

1. **Option A (simpler)**: Python script that evaluates LOD per frame, sets `visibility` on non-active items, renders with `usdrecord`
2. **Option B (proper)**: Scene index filter plugin (C++ or Python) that reads LOD schema and filters prims — requires building into the USD install
3. Start with Option A for the POC, document Option B design

### Phase D: Demo

1. Render 100-frame animation with camera dolly-out
2. Show LOD switching at distance thresholds
3. Create annotated GIF

## Open Questions

1. **Schema generation**: Should we use `usdGenSchema` for proper C++ schema, or keep it Python-only for the POC? → Python-only for speed
2. **Hydra 2.0 scene index**: The proposal mentions scene indices — should the POC build a real `HdSceneIndexPlugin`? → Defer to Phase C Option B
3. **Relationship to our existing work**: Our Phase 1 cone-angle heuristic maps to `LodScreenSizeHeuristicAPI` — should we integrate? → Note the mapping but keep POC focused on the proposal's distance-based heuristic
4. **VisibilityAPI vs base visibility**: For LOD item activation, should we use `visibility` (animatable) or purpose-specific visibility (uniform, issue #15)? → Use base `visibility` for now since purpose vis is uniform

## Dependencies

- USD Python bindings (pxr.Usd, pxr.UsdGeom, pxr.Sdf, pxr.Gf)
- Storm renderer for demo captures
- Our fixed USD build at `/tmp/usd-purpose-vis-build/` (has latest Hydra fixes)
