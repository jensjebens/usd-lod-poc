# Plan: Nested LOD Test & Demo ("City Block")

## Motivation

Current LOD tests only exercise single-level LOD groups. The Pixar LOD proposal's
**Axiom 1 (hierarchical gating)** — child groups are only evaluated when their parent
item is active — is only tested in the Python evaluator (`test_child_group_only_active_if_parent_active`).

There is:
- No C++ pipeline test for nested LOD via hdLod + Storm
- No visual demo (screenshots/GIF) showing hierarchical LOD switching
- No 3-state transition demo (the existing demo only shows 3 items in ONE group)

## Acceptance Criteria

1. **Python evaluator test**: nested LOD scene → 3 camera distances → correct active indices + gating
2. **C++ pipeline test**: `usdrecord` renders at 3 distances produce visually distinct images
3. **USDA scene**: `demo/nested_lod_scene.usda` with outer + inner LOD groups, animated camera
4. **Screenshots**: 3 static frames (close/mid/far) showing the 3 LOD states
5. **GIF**: animated camera dolly-out showing all 3 transitions

## Scene Design

```
/World/CityBlock (LodGroup, thresholds ~30)
├── DetailedBlock (Xform, LodItem)         ← active when close
│   └── Building (LodGroup, thresholds ~12)
│       ├── HighBuilding (LodItem)         ← red sphere+cone tower
│       └── LowBuilding (LodItem)          ← blue cube
└── SimplifiedBlock (LodItem)              ← grey box, active when far
```

### 3 LOD States

| Camera Z | Outer active    | Inner active   | You see                |
|----------|-----------------|----------------|------------------------|
| 5        | DetailedBlock   | HighBuilding   | Red tower (sphere+cone)|
| 20       | DetailedBlock   | LowBuilding    | Blue cube              |
| 45       | SimplifiedBlock | NOT EVALUATED  | Grey box               |

### Distance Thresholds

- **CityBlock (outer)**: min=28, max=32 (hysteresis band)
- **Building (inner)**: min=10, max=14

## Approach

1. Write failing Python evaluator tests in `tests/test_lod_proposal.py` (new `TestLodNestedHierarchy` class)
2. Write failing C++ pipeline tests in `tests/test_hdlod_pipeline.py` (new `TestHdLodNestedRendering` class)
3. Create the nested USDA scene (`demo/nested_lod_scene.usda`)
4. Verify all existing tests still pass
5. Render 3 static frames + animated GIF for the PR

## Open Questions

- None — the C++ `inactiveSubtrees` logic already handles this; tests just need to exercise it
