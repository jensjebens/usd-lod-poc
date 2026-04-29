#!/bin/bash
export PYTHONPATH=$HOME/builds/usd-lod-install/lib/python
export LD_LIBRARY_PATH=$HOME/builds/usd-lod-install/lib
export PXR_PLUGINPATH_NAME=$HOME/builds/usd-lod-install/lib/usd
export DISPLAY=:99
export __NV_PRIME_RENDER_OFFLOAD=1
export __GLX_VENDOR_LIBRARY_NAME=nvidia
export QT_QPA_PLATFORM=offscreen

cd /home/horde/.openclaw/workspace-lod
python3 demo/alab_lod/bake_lod_screenshots.py
