#!/bin/bash
# Render ALAB + LOD screenshots at different camera distances
# Uses NVIDIA L40 via PRIME offload

export PYTHONPATH=$HOME/builds/usd-lod-install/lib/python
export LD_LIBRARY_PATH=$HOME/builds/usd-lod-install/lib
export PXR_PLUGINPATH_NAME=$HOME/builds/usd-lod-install/lib/usd
export DISPLAY=:99
export __NV_PRIME_RENDER_OFFLOAD=1
export __GLX_VENDOR_LIBRARY_NAME=nvidia
export QT_QPA_PLATFORM=offscreen

SCENE="/home/horde/.openclaw/workspace-lod/demo/alab_lod/alab_benchmark.usda"
USDRECORD="$HOME/builds/usd-lod-install/bin/usdrecord"
OUTDIR="/home/horde/.openclaw/workspace-lod/demo/alab_lod/screenshots"

mkdir -p "$OUTDIR"

echo "=== ALAB + LOD Screenshot Capture ==="
echo "Scene: $SCENE"
echo ""

# Try each camera
for CAM in bench_close bench_mid bench_wide; do
    echo "Rendering $CAM..."
    python3 "$USDRECORD" \
        --defaultTime \
        --camera "/$CAM" \
        --imageWidth 1280 \
        --complexity low \
        "$SCENE" \
        "$OUTDIR/${CAM}.png" 2>&1 | grep -v "Warning (secondary" | tail -5
    
    if [ -f "$OUTDIR/${CAM}.png" ]; then
        SIZE=$(stat -c%s "$OUTDIR/${CAM}.png")
        echo "  OK: ${CAM}.png ($SIZE bytes)"
    else
        echo "  FAILED: ${CAM}.png not created"
        # Try with smaller resolution
        echo "  Retrying at 640px..."
        python3 "$USDRECORD" \
            --defaultTime \
            --camera "/$CAM" \
            --imageWidth 640 \
            --complexity low \
            "$SCENE" \
            "$OUTDIR/${CAM}.png" 2>&1 | grep -v "Warning (secondary" | tail -5
        if [ -f "$OUTDIR/${CAM}.png" ]; then
            SIZE=$(stat -c%s "$OUTDIR/${CAM}.png")
            echo "  OK (640px): ${CAM}.png ($SIZE bytes)"
        else
            echo "  STILL FAILED at 640px"
        fi
    fi
    echo ""
done

# Also render with the existing renderCam
echo "Rendering renderCam..."
python3 "$USDRECORD" \
    --frames 1004:1004 \
    --camera /root/camera01/GEO/renderCam_hrc/renderCam_buffer/renderCam_srt/renderCam \
    --imageWidth 1280 \
    --complexity low \
    "$SCENE" \
    "$OUTDIR/rendercam_####.png" 2>&1 | grep -v "Warning (secondary" | tail -5

if [ -f "$OUTDIR/rendercam_1004.png" ]; then
    SIZE=$(stat -c%s "$OUTDIR/rendercam_1004.png")
    echo "  OK: rendercam_1004.png ($SIZE bytes)"
else
    echo "  FAILED: rendercam_1004.png"
fi

echo ""
echo "=== Results ==="
ls -la "$OUTDIR"/*.png 2>/dev/null || echo "No screenshots produced"
