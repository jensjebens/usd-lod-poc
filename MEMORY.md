# MEMORY.md - LOD Long-Term Memory

## 2026-04-05 — Project Kickoff
- USD Level of Detail POC — repurposing USD purposes (render/proxy) for dynamic LOD switching
- GitHub: https://github.com/jensjebens/usd-lod-poc
- ALAB scene available at: /home/horde/.openclaw/workspace-alab/alab/ALab-2.3.0/ALab/entry.usda
- USD binaries at: /home/horde/.openclaw/workspace-alab/usd-bin/usd-v25.08/

## Phase 1: Switching Heuristics
- Goal: document and implement screen-space size heuristics for LOD switching
- Key metric: object bounding box projected to camera NDC space
- Switch between render purpose (high detail) and proxy purpose (low detail)
- Test against ALAB assets

## Phase 2 (future): Kit extension + Hydra/OpenExec implementation
- Dynamic purpose switching at runtime based on camera distance/screen size

## Collaborators
- Alab agent has ALAB scene setup knowledge
- Newton agent has Storm/Hydra rendering pipeline knowledge
- Units agent has Hydra 2.0 scene index chain expertise
