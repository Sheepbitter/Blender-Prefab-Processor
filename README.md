# Bannerlord Prefab Processor

A Blender 4.5 add-on for preparing Mount & Blade II: Bannerlord prefab exports. It merges intersecting kitbash pieces, removes buried interior geometry, simplifies the result while protecting detail, preserves materials and UVs, and generates a matching `bo_` physics mesh — all in one click.

## Why

A Bannerlord prefab built from kitbashing within the editor leaves you with tons of wasted interior faces and high asset usage that hurts performance and is unnecessary. This add-on turns the OBJ export into a clean render FBX mesh plus a `bo_` physics mesh ready for the Modding Kit.

## How it works

It takes the mesh and creates a voxel mesh copy. It then compares the original mesh against the voxel mesh to determine what from the original mesh should be kept. Then it also keeps any vertices that shares a face from the vertices that are kept from the comparison, this is a cheap way to ensure no holes form where the meshes from the prefab intersect. Then it raycasts the remaining vertices against the voxel mesh to determine what to keep; interior vertices will always have an odd number of collisions with the voxel mesh; exterior vertices will always have an even number. Finally, it decimates the mesh and produces a physics body according to the user's settings. 
## Installation

1. Copy the `Blender-Prefab-Processor` folder to:
   ```
   C:\Users\<YourUsername>\AppData\Roaming\Blender Foundation\Blender\4.5\scripts\addons\
   ```
2. Open Blender 4.5. (May work on other versions of blender, but has not been tested. Will likely need some changes to account for API updates)
3. Go to **Edit > Preferences > Add-ons**, search for "Bannerlord Prefab Processor", and enable the checkbox.

## Usage

1. **Import** your Bannerlord OBJ export (`File > Import > Wavefront (.obj)`).
2. **Select** the mesh.
3. Open the **N-panel** in the 3D Viewport (`Press N`) and switch to the **Bannerlord** tab.
4. Adjust settings.
5. Click **Process Prefab**.


## Recommended Settings:
- Merge Method: Cull Interior
- Simplify Method: Curvature-Weighted
- Detail Weight: 0.7
- Decimate Mode: Whichever you prefer. Note, the number of faces the mesh has already is displayed at the top of the panel
- Decimate Passes: 3-10
- Consolidate Materials: Enabled
- bo_ Decimate Mode: Whichever you prefer. Note the ratio is based on how many faces the original mesh was decimated to, so a 20k mesh decimated to 6k with a 0.1 ratio should have ~600 faces for the body object
- Filter Detail: Enabled
- bo_ Filter Strength: 0.7
- Export After Processing: Enabled
- Export Path: The Assets folder (or a sub-folder) of your module.

## Merge Methods

| Method | What it does | Result |
|--------|--------------|--------|
| **Cull Interior** (default) | Builds a cheap closed voxel shell (auto-sized to bounding-box/1000) and uses ray-cast parity to delete only provably buried faces. | Keeps the original surface, UVs, materials and thin details. Stays an open surface, like the source.|
| **Voxel Remesh** | Resurfaces everything into one watertight shell at the chosen Voxel Size. | Closed and clean, but blockier and can lose sub-voxel detail. |

Use **Cull Interior** when the exported mesh already looks right and you only want the hidden interior gone: it never resamples, so there is no blockiness and no loss of detail.

Use **Voxel Remesh** when the kitbash has bad self-intersections or you need a guaranteed watertight hull.

## Settings

| Setting | Description |
|---------|-------------|
| **Merge Method** | `Cull Interior` or `Voxel Remesh` (see above) |
| **Voxel Size** / **Voxel Adaptivity** | Shell/resurfacing resolution. Also sizes the bo_ shell in Cull mode. Adaptivity drops faces in flat regions |
| **Cull Floaters** | `Voxel Remesh` only: deletes islands physically detached from the main assembly. `Cull Interior` always keeps every island |
| **Simplify Method** | `Planar Pre-Pass`, `Curvature-Weighted`, or `Standard Decimate` |
| **Detail Weight** | `Curvature-Weighted` only: how strongly smooth, bulky regions are protected while fine detail is collapsed |
| **Decimate Mode** | `Ratio` or `Target Faces` (main mesh) |
| **Decimate Ratio** / **Target Face Count** | Main-mesh reduction (whichever mode is active) |
| **Decimate Passes** | Number of collapse passes |
| **Auto Generate LODs** | Generate `<name>.lod1` … `<name>.lod6` from the finished main mesh (see [Auto LODs](#auto-lods)). Enabled by default |
| **LOD1–LOD6 Ratio** | Faces kept vs LOD 0. Defaults `0.9 / 0.8 / 0.6 / 0.4 / 0.2 / 0.05`. Set a ratio to `0` to skip that LOD |
| **Consolidate Materials** | Merge duplicate materials and remap faces |
| **bo_ Decimate Mode** | `Ratio` or `Target Faces` (physics mesh) |
| **bo_ Decimate Ratio** / **bo_ Target Face Count** | Physics-mesh reduction (whichever mode is active) |
| **bo_ Filter Detail** | Reverse-curvature decimation: collapse fine detail and creases first, keeping smooth bulky regions |
| **bo_ Filter Strength** | Strength of the above |
| **Export After Processing** | Automatically export FBX when processing finishes |
| **Export Path** | Output directory for the exported files |
| **Quick Export Path** | Separate output directory for the **Export Selected as FBX** button |

## Auto LODs

**Auto Generate LODs** (on by default) builds the Bannerlord LOD chain from the finished main mesh. LOD 0 **is** the main mesh — it is never modified. Each higher LOD is a fresh copy of LOD 0 decimated to its ratio of LOD 0's face count, using the same simplify method, Detail Weight and pass count as the main decimation. UVs and materials are preserved on every LOD.

| LOD | Default ratio | Faces kept vs LOD 0 |
|-----|---------------|---------------------|
| LOD1 | 0.9 | 90% |
| LOD2 | 0.8 | 80% |
| LOD3 | 0.6 | 60% |
| LOD4 | 0.4 | 40% |
| LOD5 | 0.2 | 20% |
| LOD6 | 0.05 | 5% |

- Ratios are measured against **LOD 0**, not against the previous LOD, so editing one does not shift the others.
- Set a ratio to `0` to skip that LOD.
- LODs are named `<prefab_name>.lod1` … `.lod6` and are written into the **same FBX** as LOD 0 — the engine finds them by that suffix.
- `bo_` is never LOD'd: Bannerlord physics is a single mesh.

For reference, the default LOD distances in the Bannerlord scene editor are 15, 22.5, 30, 50, 70, 130 and 210 m — LOD 0 is shown from 0–15 m, LOD 1 from 15–22.5 m, and so on. Those distances live in the scene editor rather than the FBX, so the add-on does not write them.

## Output

| File | Contents |
|------|----------|
| `<prefab_name>.fbx` | All render meshes: LOD 0 (the main mesh) plus every generated LOD. Cull mode keeps the original surfaces; Voxel mode is a watertight resurface |
| `bo_<prefab_name>.fbx` | Physics mesh. No materials, no UVs, no vertex groups |

### `bo_` behaviour

- **Cull mode:** `bo_` is a decimated copy of the finished render mesh, so it tracks the real silhouette. Because the render mesh is an open surface, so is `bo_`.
- **Voxel mode:** `bo_` is watertight.
- Islands that are physically detached from the main assembly, and islands that decimate down to a few stray faces, are pruned from `bo_` only. The render mesh always keeps every island.
- `bo_ Filter Detail` cannot remove detached sticks on its own: reverse-curvature weighting protects the smooth parts of each piece, so a small isolated stick survives even at strength `1.0`. The island pruning is what removes them.

### To Do (one day)
- Get the settings to save and persist
- Improve the tool to create/weld overlapping faces for new edges. This will allow the safety net of keeping any vertices that share a face with the first pass known good vertices to be removed and let the interior culling be complete and total without introducing any potential holes/gaps.
- Add clean batch processing.
- Make the add-on a standalone tool, cause all this stuff doesn't actually need blender. I've already done half or so of this in another project for a different standalone tool, so I don't see a reason blender would actually be required. Maybe a hybrid that can be run standalone and hooks into blender as an addon so people who prefer to use it that way can. After all, you can make your own adjustments manually in blender directly, so there's good reason to keep it.
