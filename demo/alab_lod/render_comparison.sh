#!/bin/bash
# Render comparison: with LOD overlay vs without
# Shows the same cameras but on the base ALAB scene (no LOD switching)

export PYTHONPATH=$HOME/builds/usd-lod-install/lib/python
export LD_LIBRARY_PATH=$HOME/builds/usd-lod-install/lib
export PXR_PLUGINPATH_NAME=$HOME/builds/usd-lod-install/lib/usd
export DISPLAY=:99
export __NV_PRIME_RENDER_OFFLOAD=1
export __GLX_VENDOR_LIBRARY_NAME=nvidia
export QT_QPA_PLATFORM=offscreen

USDRECORD="$HOME/builds/usd-lod-install/bin/usdrecord"
OUTDIR="/home/horde/.openclaw/workspace-lod/demo/alab_lod/screenshots"

# We need a scene file that has cameras but NO LOD overlay — just base ALAB + cams
cat > /tmp/alab_base_cams.usda << 'EOF'
#usda 1.0
(
    "Base ALAB + benchmark cameras (no LOD overlay)"
    subLayers = [
        @/home/horde/.openclaw/workspace-alab/alab/ALab-2.3.0/ALab/entry.usda@
    ]
    defaultPrim = "root"
    startTimeCode = 1
    endTimeCode = 1
)

def Camera "bench_close" (
    doc = "Close-up - electronics shelf area where LOD groups are"
)
{
    float focalLength = 50
    float horizontalAperture = 36
    float verticalAperture = 24
    float2 clippingRange = (1, 100000)
    double3 xformOp:translate = (260, 88, -10)
    float3 xformOp:rotateXYZ = (0, 160, 0)
    token[] xformOpOrder = ["xformOp:translate", "xformOp:rotateXYZ"]
}

def Camera "bench_mid" (
    doc = "Mid-distance - lab bench view"
)
{
    float focalLength = 35
    float horizontalAperture = 36
    float verticalAperture = 24
    float2 clippingRange = (1, 100000)
    double3 xformOp:translate = (150, 120, 200)
    float3 xformOp:rotateXYZ = (-10, 20, 0)
    token[] xformOpOrder = ["xformOp:translate", "xformOp:rotateXYZ"]
}

def Camera "bench_wide" (
    doc = "Wide establishing shot"
)
{
    float focalLength = 24
    float horizontalAperture = 36
    float verticalAperture = 24
    float2 clippingRange = (1, 100000)
    double3 xformOp:translate = (400, 250, 500)
    float3 xformOp:rotateXYZ = (-20, 25, 0)
    token[] xformOpOrder = ["xformOp:translate", "xformOp:rotateXYZ"]
}
EOF

echo "=== Rendering base ALAB (no LOD overlay) ==="
for CAM in bench_close bench_mid bench_wide; do
    echo "Rendering base_${CAM}..."
    python3 "$USDRECORD" \
        --defaultTime \
        --camera "/$CAM" \
        --imageWidth 1280 \
        --complexity low \
        /tmp/alab_base_cams.usda \
        "$OUTDIR/base_${CAM}.png" 2>&1 | grep -v "Warning" | tail -3
    
    if [ -f "$OUTDIR/base_${CAM}.png" ]; then
        SIZE=$(stat -c%s "$OUTDIR/base_${CAM}.png")
        echo "  OK: base_${CAM}.png ($SIZE bytes)"
    else
        echo "  FAILED"
    fi
done

echo ""
echo "=== Also render LOD version with refined close-up camera ==="

# Update the LOD benchmark scene with a better close-up camera
cat > /tmp/alab_lod_refined.usda << 'EOF'
#usda 1.0
(
    "ALAB + LOD overlay + refined benchmark cameras"
    subLayers = [
        @/home/horde/.openclaw/workspace-lod/demo/alab_lod/alab_lod_overlay.usda@,
        @/home/horde/.openclaw/workspace-alab/alab/ALab-2.3.0/ALab/entry.usda@
    ]
    defaultPrim = "root"
    startTimeCode = 1
    endTimeCode = 1
)

def Camera "bench_close" (
    doc = "Close-up - electronics shelf where LOD groups live"
)
{
    float focalLength = 50
    float horizontalAperture = 36
    float verticalAperture = 24
    float2 clippingRange = (1, 100000)
    double3 xformOp:translate = (260, 88, -10)
    float3 xformOp:rotateXYZ = (0, 160, 0)
    token[] xformOpOrder = ["xformOp:translate", "xformOp:rotateXYZ"]
}

def Camera "bench_mid" (
    doc = "Mid-distance lab bench view"
)
{
    float focalLength = 35
    float horizontalAperture = 36
    float verticalAperture = 24
    float2 clippingRange = (1, 100000)
    double3 xformOp:translate = (150, 120, 200)
    float3 xformOp:rotateXYZ = (-10, 20, 0)
    token[] xformOpOrder = ["xformOp:translate", "xformOp:rotateXYZ"]
}

def Camera "bench_wide" (
    doc = "Wide establishing shot"
)
{
    float focalLength = 24
    float horizontalAperture = 36
    float verticalAperture = 24
    float2 clippingRange = (1, 100000)
    double3 xformOp:translate = (400, 250, 500)
    float3 xformOp:rotateXYZ = (-20, 25, 0)
    token[] xformOpOrder = ["xformOp:translate", "xformOp:rotateXYZ"]
}
EOF

for CAM in bench_close; do
    echo "Rendering lod_${CAM}..."
    python3 "$USDRECORD" \
        --defaultTime \
        --camera "/$CAM" \
        --imageWidth 1280 \
        --complexity low \
        /tmp/alab_lod_refined.usda \
        "$OUTDIR/lod_${CAM}.png" 2>&1 | grep -v "Warning" | tail -3
    
    if [ -f "$OUTDIR/lod_${CAM}.png" ]; then
        SIZE=$(stat -c%s "$OUTDIR/lod_${CAM}.png")
        echo "  OK: lod_${CAM}.png ($SIZE bytes)"
    else
        echo "  FAILED"
    fi
done

echo ""
echo "=== All screenshots ==="
ls -la "$OUTDIR"/*.png 2>/dev/null | grep -v "alab_test"
