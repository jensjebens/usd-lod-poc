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

## The Screen-Space Size Metric

### Why Screen-Space Size?

The fundamental insight behind LOD is: **if an object is small on screen, the viewer can't perceive its full detail.** A 10-million-polygon model rendered at 20×20 pixels is indistinguishable from a 500-polygon proxy at the same size.

Screen-space size captures this directly. It answers: *what fraction of the screen does this object's bounding box cover?*

### Computing Screen Fraction

Given:
- A prim `P` on a stage
- A camera `C` with known projection
- An output image of dimensions `W × H` pixels

The computation proceeds in five steps:

#### Step 1: World Bounding Box

Use `UsdGeom.BBoxCache` to compute the axis-aligned bounding box (AABB) of `P` in world space:

```python
bbox_cache = UsdGeom.BBoxCache(time, ["default", "render", "proxy"])
world_bbox = bbox_cache.ComputeWorldBound(prim)
world_range = world_bbox.ComputeAlignedRange()
```

This gives us the 3D min/max corners: `(xmin, ymin, zmin)` and `(xmax, ymax, zmax)`.

#### Step 2: Camera Frustum & Matrices

Extract the camera's view and projection matrices:

```python
usd_camera = UsdGeom.Camera(camera_prim)
gf_camera = usd_camera.GetCamera(time)
frustum = gf_camera.frustum

view_matrix = frustum.ComputeViewMatrix()
proj_matrix = frustum.ComputeProjectionMatrix()
```

#### Step 3: Project Bounding Box Corners to Clip Space

The world bounding box has 8 corners. Transform each through `view × projection`:

```python
corners_3d = world_range.GetCorners()  # 8 Gf.Vec3d points
vp = view_matrix * proj_matrix

for corner in corners_3d:
    clip = Gf.Vec4d(corner[0], corner[1], corner[2], 1.0) * Gf.Matrix4d(vp)
    if clip[3] > 0:
        ndc_x = clip[0] / clip[3]
        ndc_y = clip[1] / clip[3]
```

#### Step 4: NDC Bounding Rectangle

Collect all valid NDC points (those with `w > 0`, i.e. in front of the camera) and compute the axis-aligned 2D bounding box. Clamp to `[-1, 1]`:

```
ndc_min_x = max(-1, min(all ndc_x values))
ndc_max_x = min( 1, max(all ndc_x values))
ndc_min_y = max(-1, min(all ndc_y values))
ndc_max_y = min( 1, max(all ndc_y values))
```

#### Step 5: Screen Fraction

The full NDC range is `[-1, 1]` on each axis, so the total area is `2 × 2 = 4`:

```
ndc_width  = ndc_max_x - ndc_min_x
ndc_height = ndc_max_y - ndc_min_y
screen_fraction = (ndc_width * ndc_height) / 4.0
```

A `screen_fraction` of:
- **1.0** means the object fills the entire screen
- **0.0** means the object is invisible (behind camera or zero-size)
- **0.01** means the object covers ~1% of the screen area

## Switching Decision: Hysteresis Model

### The Problem: Flickering

A naive threshold (e.g. "if `screen_fraction < 0.05`, use proxy") causes **flickering** when the camera is near the threshold. Small movements toggle between purposes every frame.

### The Solution: Two Thresholds

Use a **hysteresis band** with two thresholds:

- `high_threshold` — switch from proxy → render when screen fraction exceeds this
- `low_threshold` — switch from render → proxy when screen fraction drops below this

Where `low_threshold < high_threshold`.

```
Screen fraction:   0.0 ----[low]--------[high]---- 1.0

                          proxy zone  |  dead zone  |  render zone
```

The **dead zone** between thresholds means: *keep the current purpose*. This eliminates flickering.

### State Machine

```
Current: proxy
  IF screen_fraction >= high_threshold → SWITCH to render
  ELSE → STAY proxy

Current: render
  IF screen_fraction <= low_threshold → SWITCH to proxy
  ELSE → STAY render
```

### Recommended Default Thresholds

| Parameter        | Value | Rationale |
|------------------|-------|-----------|
| `high_threshold` | 0.05  | 5% screen coverage — object is clearly visible, worth full detail |
| `low_threshold`  | 0.02  | 2% screen coverage — object is small enough that proxy suffices |

These are starting points. In practice, thresholds should be tunable per-asset or per-purpose-group.

## Pixel Coverage (Optional Metric)

For applications that need absolute pixel counts rather than fractions:

```
pixel_coverage = screen_fraction * W * H
```

This lets you set thresholds like "switch to proxy below 2000 pixels" which may be more intuitive for artists.

## Edge Cases

| Scenario | Result |
|----------|--------|
| Prim entirely behind camera | `screen_fraction = 0.0` → proxy |
| Prim partially behind camera | Use only the corners in front of camera for NDC projection |
| Prim has no bounding box | Skip (no switching) |
| Camera inside the bounding box | `screen_fraction = 1.0` → render |
| Orthographic camera | Same algorithm — projection matrix handles it |

## Integration Points

### Phase 1 (this POC)
- Python-only evaluation against static stages
- Process: load stage → query camera → compute screen fractions → report purpose decisions

### Phase 2 (future)
- **Kit Extension**: UI panel to configure thresholds, real-time purpose toggling in viewport
- **Hydra Scene Index / OpenExec**: inject purpose switching into the render pipeline at the scene index level, so the renderer receives already-switched purposes
- Collaborate with Newton agent (Hydra rendering) and Units agent (scene index chain)

## References

- [USD Purpose Documentation](https://openusd.org/release/glossary.html#purpose)
- `UsdGeom.BBoxCache` — efficient bounding box computation with purpose filtering
- `Gf.Frustum` — camera projection utilities
- ALAB scene: both `render` and `proxy` purposes are authored on circuit board and decoration assets
