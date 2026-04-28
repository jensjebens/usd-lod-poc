#!/bin/bash
export PYTHONPATH=$HOME/builds/usd-lod-install/lib/python:$PYTHONPATH
export LD_LIBRARY_PATH=$HOME/builds/usd-lod-install/lib:$LD_LIBRARY_PATH
export PXR_PLUGINPATH_NAME=$HOME/builds/usd-lod-install/lib/usd
cd /home/horde/.openclaw/workspace-lod
python3 demo/alab_lod/benchmark_hdlod.py
