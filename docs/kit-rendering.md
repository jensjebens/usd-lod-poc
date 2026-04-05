# Rendering USD Sequences via Omniverse Kit

## Overview

Omniverse Kit is NVIDIA's application framework built on OpenUSD. It provides GPU-accelerated rendering (RTX / Storm) and a Python extension system. For our LOD switching POC, Kit gives us:

1. **High-quality RTX rendering** (path-traced or real-time) vs Storm's rasterisation
2. **Headless operation** — Kit can run without a display via `--no-window`  
3. **Frame capture** — render to PNG/EXR per-frame via `omni.kit.renderer_capture`
4. **Extension system** — inject our LOD heuristic as a per-frame callback
5. **Movie Maker** — built-in `omni.kit.window.movie_maker` extension for sequence rendering

## Kit Installation on This Machine

Kit kernel is cached at:
```
/home/horde/.cache/packman/chk/kit-kernel/110.0.0+feature.manylinux_2_35_x86_64.release/
```

Binary: `kit` (ELF 64-bit, x86-64)

Available app configs:
- `omni.app.viewport.kit` — single viewport (lightest)
- `omni.app.mini.kit` — minimal
- `omni.app.full.kit` — full editor  
- `omni.app.hydra.kit` — Hydra-focused

Extension data at: `~/.local/share/ov/data/`

## Approach: Three Options

### Option A: Kit + Script Execution (Recommended for POC)

Launch Kit headless, open the stage, run a Python script that:
1. Iterates timeline frames
2. Computes `screen_size` per prim per frame  
3. Toggles visibility (purpose proxy ↔ render)
4. Captures each frame to PNG

```bash
KIT=/home/horde/.cache/packman/chk/kit-kernel/110.0.0+feature.manylinux_2_35_x86_64.release/kit

DISPLAY=:99 __NV_PRIME_RENDER_OFFLOAD=1 __GLX_VENDOR_LIBRARY_NAME=nvidia \
  $KIT omni.app.viewport.kit \
    --no-window \
    --exec "capture_lod_sequence.py --stage demo/lod_demo.usda --output demo/kit_frames/"
```

The script uses Kit's Python environment:
```python
import omni.usd
import omni.kit.app
import omni.timeline
import omni.kit.renderer_capture
from omni.kit.viewport.utility import get_active_viewport_window

# Open stage
omni.usd.get_context().open_stage("path/to/stage.usda")

# Get capture interface
capture_iface = omni.kit.renderer_capture.acquire_renderer_capture_interface()

# Per-frame callback
def on_frame(event):
    frame = event["frame_number"]
    # ... compute screen_size, toggle visibility ...
    capture_iface.capture_next_frame_swapchain(f"output/frame_{frame:04d}.png")
```

### Option B: Kit Extension (For Interactive Use)

Create a Kit extension (`omni.lod.switcher`) that:
- Subscribes to viewport update events
- Computes screen_size for tagged prims each frame
- Dynamically sets purpose visibility via `UsdGeom.Imageable.GetVisibilityAttr()`
- Provides a UI panel for threshold configuration

Extension structure:
```
omni.lod.switcher/
├── config/
│   └── extension.toml
└── omni/
    └── lod/
        └── switcher/
            ├── __init__.py
            └── extension.py
```

`extension.toml`:
```toml
[package]
title = "LOD Purpose Switcher"
version = "0.1.0"

[dependencies]
"omni.kit.viewport.window" = {}
"omni.usd" = {}

[[python.module]]
name = "omni.lod.switcher"
```

### Option C: Multi-Process Capture (For Large Sequences)

Kit ships with `multi_process_capture.py` which distributes frames across Kit instances. Pattern found at:
```
~/.local/share/ov/data/exts/v2/omni.usd-*/scripts/multi_process_capture.py
```

This uses `omni.kit.renderer_capture.acquire_renderer_capture_interface().capture_next_frame_swapchain()` — the same capture API.

## Key Kit APIs

### Stage Management
```python
import omni.usd
ctx = omni.usd.get_context()
ctx.open_stage("path/to/stage.usda")   # async
stage = ctx.get_stage()                  # returns Usd.Stage
```

### Timeline Control
```python
import omni.timeline
tl = omni.timeline.get_timeline_interface()
tl.set_start_time(0)
tl.set_end_time(60 / 24.0)  # 60 frames at 24fps
tl.set_current_time(frame / 24.0)
tl.play()
tl.pause()
```

### Frame Capture
```python
import omni.kit.renderer_capture
iface = omni.kit.renderer_capture.acquire_renderer_capture_interface()
iface.capture_next_frame_swapchain("/path/to/frame.png")
```

### Viewport Camera
```python
from omni.kit.viewport.utility import get_active_viewport_window
vp = get_active_viewport_window()
vp.set_active_camera("/World/Camera")
```

### Rendering Events (Per-Frame Callback)
```python
import carb.eventdispatcher

def on_render(event):
    frame = event["frame_number"]
    # do work per frame

sub = carb.eventdispatcher.get_event_dispatcher().observe(
    "omni.kit.app.rendering",
    on_render
)
```

### Purpose / Visibility Control
```python
from pxr import UsdGeom, Usd

prim = stage.GetPrimAtPath("/World/LODObject/HighDetail")
img = UsdGeom.Imageable(prim)
img.GetVisibilityAttr().Set(UsdGeom.Tokens.invisible)  # hide
img.GetVisibilityAttr().Set(UsdGeom.Tokens.inherited)   # show
```

## Headless Mode

Kit supports `--no-window` for headless GPU rendering. Still requires:
```bash
export DISPLAY=:99
export __NV_PRIME_RENDER_OFFLOAD=1
export __GLX_VENDOR_LIBRARY_NAME=nvidia
```

The viewport renders off-screen and the capture API writes frames to disk.

## Renderer Selection

Kit supports multiple renderers via settings:
```bash
# RTX Real-time (fast, rasterised + ray-traced)
--/renderer/active=rtx
--/renderer/enabled=rtx

# RTX Path-traced (highest quality, slower)
--/renderer/active=rtx  
--/rtx/pathtracing/spp=64

# Storm (OpenGL, matches usdrecord output)
--/renderer/active=pxrStorm
```

## Sequence Rendering Workflow

1. Build the USD scene with animated camera + LOD prims (already done in `demo/lod_demo.usda`)
2. Write a Kit capture script that:
   - Opens the stage
   - Sets the camera
   - For each frame: advance timeline, compute screen_size, toggle visibility, capture
3. Launch Kit headless with the script
4. Stitch frames into GIF/video with ffmpeg

## Comparison: usdrecord vs Kit

| Aspect | usdrecord | Kit |
|--------|-----------|-----|
| Renderer | Storm (OpenGL) | RTX (path-traced or real-time) + Storm |
| Quality | Good (rasterised) | Best (ray-traced reflections, GI) |
| Speed | Fast | Slower (RTX convergence) |
| Python version | 3.12 (USD binaries) | Kit's bundled Python |
| Dependencies | PySide6 | Self-contained |
| Headless | Needs DISPLAY + GL context | `--no-window` + GPU |
| Frame control | `--frames` flag | Timeline API + capture callback |
| Per-frame logic | Must pre-bake visibility into stage | Can compute live per frame |

**Key advantage of Kit for LOD:** We can compute `screen_size` and switch purposes **live per frame** instead of pre-baking all visibility keyframes into the USD file. This better simulates what a real-time application would do.

## Next Steps

1. Write the Kit capture script (`demo/kit_capture_lod.py`)
2. Test headless rendering with the existing `lod_demo.usda`
3. Compare Kit RTX output vs Storm usdrecord output
4. If Kit works well, build the interactive extension (Option B) for Phase 2

## Open Questions

- Does the Kit installation on this machine have RTX support, or only Storm?
- Is `omni.kit.renderer_capture` available in the cached kit-kernel, or does it need to be fetched from the extension registry?
- What's the warmup time for RTX shader compilation on first run?
