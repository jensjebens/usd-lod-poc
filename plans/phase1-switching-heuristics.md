# Plan: Phase 1 — LOD Switching Heuristics

## Motivation

USD has `render` and `proxy` purposes built into the scene graph. ALAB and other production assets already author both — `render` for high-detail geometry, `proxy` for lightweight stand-ins. Today, purpose visibility is set statically at the viewer level (e.g. "show render" or "show proxy"). There's no dynamic switching based on how large an object actually appears on screen.

This phase builds the heuristic engine: given a camera and a prim, compute its screen-space size and decide which purpose to activate.

## Acceptance Criteria

1. **Document** (`docs/switching-heuristics.md`) that explains:
   - What render/proxy purposes are in USD
   - The screen-space size metric (bounding box → NDC projection → pixel coverage)
   - The switching threshold model (hysteresis to avoid flickering)
   - The math: world bbox → clip space → NDC → screen fraction

2. **Python module** (`src/lod_heuristics.py`) with:
   - `compute_screen_fraction(stage, prim_path, camera_path, time, image_width, image_height)` → float (0.0–1.0)
   - `decide_purpose(screen_fraction, high_threshold, low_threshold)` → "render" | "proxy"
   - Hysteresis support (current state + thresholds)

3. **Tests** (`tests/test_lod_heuristics.py`) using `pytest`:
   - Test `compute_screen_fraction` with a known camera + cube at known distance → expected fraction ± tolerance
   - Test `decide_purpose` state machine (hysteresis transitions)
   - Test against ALAB assets (at least one proxy/render prim pair)
   - Edge cases: prim behind camera → 0.0, prim filling screen → ~1.0

## Approach

### Screen-Space Size Computation

1. Open the stage, get the prim and camera at the given time.
2. Use `UsdGeom.BBoxCache` with `includedPurposes=["default", "render", "proxy"]` to get the world bounding box of the prim.
3. Get the camera's `Gf.Frustum` via `UsdGeom.Camera.GetCamera()` at time.
4. Extract the projection matrix from the frustum.
5. Project the 8 corners of the world bounding box through the MVP (view × projection) matrix into NDC space.
6. Clamp to [-1, 1] (clip to frustum), compute the 2D axis-aligned bounding rectangle in NDC.
7. Screen fraction = `(ndc_width * ndc_height) / 4.0` (NDC range is [-1,1] so full screen = 2×2 = 4).

### Hysteresis

Two thresholds: `high_threshold` (switch to render) and `low_threshold` (switch to proxy), where `low < high`. This prevents flickering at the boundary.

- If currently proxy and `screen_fraction >= high_threshold` → switch to render
- If currently render and `screen_fraction <= low_threshold` → switch to proxy
- Otherwise → keep current purpose

### Testing Strategy

- Create a minimal USD stage with a unit cube and a perspective camera at known distance.
- Compute expected screen fraction analytically.
- Assert `compute_screen_fraction` matches within tolerance.
- Test hysteresis state machine exhaustively.
- Load ALAB, pick a prim with both purposes, compute screen fraction from a camera — smoke test.

## Open Questions

- Should the screen fraction be based on the **area** of the projected bbox or the **max dimension**? Area is more standard for LOD (matches traditional "pixel coverage" heuristic). Starting with area.
- For ALAB, do proxy/render prims share a common parent? Need to explore the hierarchy to understand how to pair them.

## Dependencies

- USD Python bindings (available at `/home/horde/.openclaw/workspace-alab/usd-bin/usd-v25.08/`)
- ALAB scene (available at `/home/horde/.openclaw/workspace-alab/alab/ALab-2.3.0/ALab/entry.usda`)
- pytest
