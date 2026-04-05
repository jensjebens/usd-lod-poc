# LOD Switching Heuristics — Screen-Space Size

## Overview

OpenUSD provides a built-in mechanism for geometric Level of Detail through **purposes**. Every `UsdGeom.Imageable` prim carries a `purpose` attribute with one of four values:

| Purpose   | Intent |
|-----------|--------|
| `default` | Normal geometry — always visible unless explicitly hidden |
| `render`  | High-fidelity geometry for final-quality rendering |
| `proxy`   | Lightweight stand-in for viewport/interactive use |
| `guide`   | Construction/helper geometry (axis indicators, etc.) |

In production assets like ALAB, artists author both `render` and `proxy` geometry under the same parent. Renderers and viewers select which purposes to display, but this selection is **static** — set once at the session level.

This document describes heuristics for **dynamic** purpose switching based on how large an object appears on screen.

## Primary Metric: Cone Angle (Bounding Sphere)

### Why Cone Angle?

The cone angle approach asks a simple geometric question: *how large does this object's bounding sphere appear from the camera's point of view?*

It's the standard approach in game engines (Unreal, Unity) and is used by Pixar's Hydra for draw-call sorting. The key advantages:

- **Fast** — one distance calculation and one division. No matrix multiplications, no 8-corner projection.
- **Camera-parameter independent** — the result is a pure geometric measure. It doesn't change with FOV, resolution, or aspect ratio, making thresholds portable across different render setups.
- **Intuitive** — "this object subtends 2° from the camera" is easy to reason about.

### The Math

Given a prim with a world-space bounding sphere of radius `r`, and the camera eye at distance `d` from the sphere centre:

```
screen_size = radius / distance
```

This is the tangent of the half-cone-angle (for small angles, `tan(θ) ≈ θ`, so this approximates the half-angle in radians directly). It's dimensionless and ranges from 0 (infinitely far) to ∞ (inside the sphere), though in practice we clamp to [0, 1].

The full solid angle subtended by the sphere is `Ω = π × (r/d)²` steradians, but the linear `r/d` ratio is simpler to threshold and is what most engines use.

### Computing It

```python
from pxr import UsdGeom, Gf

def compute_screen_size(stage, prim_path, camera_path, time):
    """Compute bounding-sphere screen size ratio (radius / distance)."""
    prim = stage.GetPrimAtPath(prim_path)
    camera_prim = stage.GetPrimAtPath(camera_path)

    # World bounding box → bounding sphere
    bbox_cache = UsdGeom.BBoxCache(time, ["default", "render", "proxy"])
    world_bbox = bbox_cache.ComputeWorldBound(prim)
    aligned = world_bbox.ComputeAlignedRange()

    if aligned.IsEmpty():
        return 0.0

    centre = (Gf.Vec3d(aligned.GetMin()) + Gf.Vec3d(aligned.GetMax())) * 0.5
    radius = (Gf.Vec3d(aligned.GetMax()) - centre).GetLength()

    # Camera eye position
    usd_camera = UsdGeom.Camera(camera_prim)
    gf_camera = usd_camera.GetCamera(time)
    eye = gf_camera.frustum.GetPosition()

    distance = (centre - eye).GetLength()

    if distance <= radius:
        return 1.0  # Camera inside bounding sphere

    return radius / distance
```

**Cost:** one bbox lookup (already cached by Hydra), one vector subtraction, one length, one division.

### Thresholds

Because `screen_size` is a ratio rather than a fraction of screen area, the threshold values are different from NDC-based metrics:

| screen_size | Approximate meaning |
|-------------|---------------------|
| 1.0         | Camera inside the object |
| 0.1         | Object subtends ~11° — very prominent |
| 0.01        | Object subtends ~1° — small but visible |
| 0.001       | Object subtends ~0.06° — barely perceptible |

Reasonable starting defaults for purpose switching:

| Parameter        | Value  | Rationale |
|------------------|--------|-----------|
| `high_threshold` | 0.02   | Object subtends ~2° — clearly visible, use full detail |
| `low_threshold`  | 0.008  | Object subtends ~0.5° — small enough for proxy |

### Converting to Pixels (Optional)

If you need pixel-based thresholds, multiply by the vertical FOV factor:

```
pixel_diameter = screen_size * image_height / tan(vfov/2)
```

This bridges the gap between the camera-independent metric and resolution-aware artist controls.

## Switching Decision: Hysteresis

### The Problem

Imagine a camera slowly dollying away from an object. At some point the object crosses the threshold and switches from render → proxy. The camera drifts back slightly — it switches to render. Back again — proxy. This **flickering** is visually distracting and can cause frame-rate hitches (each switch may trigger geometry loading).

With a single threshold at `t = 0.02`:

```
Frame 1: screen_size = 0.0201 → render
Frame 2: screen_size = 0.0199 → proxy   ← SWITCH
Frame 3: screen_size = 0.0201 → render  ← SWITCH
Frame 4: screen_size = 0.0198 → proxy   ← SWITCH
```

Four frames, three switches. That's unacceptable.

### The Solution: Dead Zone

Use **two thresholds** with a gap between them:

- `high_threshold` — switch proxy → render when `screen_size ≥ high`
- `low_threshold` — switch render → proxy when `screen_size ≤ low`
- Between them: **keep whatever purpose is currently active**

```
screen_size:  0.0 ----[low=0.008]----[dead zone]----[high=0.02]---- 1.0

              ← proxy stays proxy →  ← no change →  ← render stays render →
```

The dead zone means the camera has to move a **significant distance** past the switching point before a reverse switch happens. The object has to shrink below `low` to become proxy, but then it has to grow past `high` to become render again — that's a meaningful visual change, not noise.

### State Machine

```
Current: proxy
  IF screen_size >= high_threshold → SWITCH to render
  ELSE → STAY proxy

Current: render  
  IF screen_size <= low_threshold → SWITCH to proxy
  ELSE → STAY render
```

### Why Not Just a Larger Single Threshold?

A single higher threshold delays the switch but doesn't prevent flickering — it just moves the flicker zone further from the camera. The dead zone **eliminates** it entirely because the switch-up and switch-down happen at different values.

### Tuning the Dead Zone Width

- **Narrow dead zone** (e.g. high=0.02, low=0.018): responsive switching, slight flicker risk in very dynamic scenes
- **Wide dead zone** (e.g. high=0.02, low=0.005): very stable, but objects stay at the "wrong" LOD longer
- **Rule of thumb**: `low ≈ 0.3× to 0.5× high` gives a good balance

### Real-World Analogy

It's the same principle as a thermostat. Your heating doesn't turn on at 20°C and off at 20°C — it turns on at 18°C and off at 22°C. Without that gap, the furnace would cycle on and off every few seconds.

## Edge Cases

| Scenario | Result |
|----------|--------|
| Prim entirely behind camera | `distance` is negative or prim not in frustum → `screen_size = 0.0` → proxy |
| Camera inside bounding sphere | `distance < radius` → `screen_size = 1.0` → render |
| Prim has no bounding box | Skip — no switching |
| Orthographic camera | `screen_size = radius / distance` still works geometrically, though the visual meaning is slightly different since ortho has no perspective foreshortening |

## Integration Points

### Phase 1 (this POC)
- Python-only evaluation against static stages
- Process: load stage → query camera → compute screen sizes → report purpose decisions

### Phase 2 (future)
- **Kit Extension**: UI panel to configure thresholds, real-time purpose toggling in viewport
- **Hydra Scene Index / OpenExec**: inject purpose switching into the render pipeline at the scene index level, so the renderer receives already-switched purposes
- Collaborate with Newton agent (Hydra rendering) and Units agent (scene index chain)

## References

- [USD Purpose Documentation](https://openusd.org/release/glossary.html#purpose)
- `UsdGeom.BBoxCache` — efficient bounding box computation with purpose filtering
- `Gf.Frustum.GetPosition()` — camera eye position
- ALAB scene: both `render` and `proxy` purposes are authored on circuit board and decoration assets
- Unreal Engine LOD Screen Size: uses bounding sphere radius / distance as the core metric

---

## Appendix A: NDC Projection Method (Full Frustum)

An alternative, more precise but slower method projects all 8 corners of the world AABB through the full view-projection matrix to compute the exact NDC bounding rectangle.

### Computing Screen Fraction via NDC Projection

Given a prim `P`, camera `C`, and output dimensions `W × H`:

1. `UsdGeom.BBoxCache` → world AABB → 8 corners
2. `UsdGeom.Camera.GetCamera().frustum` → view matrix + projection matrix
3. For each corner: `clip = [x,y,z,1] × (view × proj)` → perspective divide → NDC (skip if `w ≤ 0`)
4. Clamp NDC to `[-1, 1]`, compute axis-aligned 2D bounding box
5. `screen_fraction = (ndc_width × ndc_height) / 4.0`

### When to Use This Instead

- When you need **exact pixel coverage** accounting for frustum clipping
- For non-convex or very elongated objects where the bounding sphere is a poor fit
- When you want thresholds in screen-area-fraction (e.g. "switch below 1% of screen")

### Cost

8 matrix-vector multiplications + perspective divides + clamping. Roughly 10× slower than the cone angle method, but still fast enough for per-frame evaluation of hundreds of prims.

### Code

```python
def compute_screen_fraction(stage, prim_path, camera_path, time, image_width, image_height):
    """Compute fraction of screen covered by prim's projected AABB."""
    prim = stage.GetPrimAtPath(prim_path)
    camera_prim = stage.GetPrimAtPath(camera_path)

    bbox_cache = UsdGeom.BBoxCache(time, ["default", "render", "proxy"])
    world_bbox = bbox_cache.ComputeWorldBound(prim)
    world_range = world_bbox.ComputeAlignedRange()
    if world_range.IsEmpty():
        return 0.0

    usd_camera = UsdGeom.Camera(camera_prim)
    gf_camera = usd_camera.GetCamera(time)
    frustum = gf_camera.frustum
    vp = frustum.ComputeViewMatrix() * frustum.ComputeProjectionMatrix()

    bbox_min, bbox_max = world_range.GetMin(), world_range.GetMax()
    corners = [Gf.Vec3d(x, y, z)
               for x in (bbox_min[0], bbox_max[0])
               for y in (bbox_min[1], bbox_max[1])
               for z in (bbox_min[2], bbox_max[2])]

    ndc_xs, ndc_ys = [], []
    for c in corners:
        clip = Gf.Vec4d(c[0], c[1], c[2], 1.0) * Gf.Matrix4d(vp)
        if clip[3] <= 0:
            continue
        ndc_xs.append(clip[0] / clip[3])
        ndc_ys.append(clip[1] / clip[3])

    if not ndc_xs:
        return 0.0

    w = min(1, max(ndc_xs)) - max(-1, min(ndc_xs))
    h = min(1, max(ndc_ys)) - max(-1, min(ndc_ys))
    return max(0, min(1, max(0, w) * max(0, h) / 4.0))
```
