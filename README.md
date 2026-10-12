# Bannerlord Prefab Processor

A Blender 4.5 addon for preparing Mount & Blade II: Bannerlord prefab exports. It merges intersecting kitbash pieces, removes buried interior geometry, simplifies the result while protecting detail, preserves materials and UVs, and generates a matching `bo_` physics mesh — all in one click.

## Why

A Bannerlord prefab is built by kitbashing many small meshes together. Exporting that straight to the engine leaves you with thousands of hidden interior faces, several materials on a single mesh, and no collision geometry. This addon turns the OBJ export into a clean render mesh plus a `bo_` physics mesh ready for the Modding Kit.

## Installation

1. Copy the `Blender-Prefab-Processor` folder to:
   ```
   C:\Users\<YourUsername>\AppData\Roaming\Blender Foundation\Blender\4.5\scripts\addons\
   ```
2. Open Blender 4.5.
3. Go to **Edit > Preferences > Add-ons**, search for "Bannerlord Prefab Processor", and enable the checkbox.

## Usage

1. **Import** your Bannerlord OBJ export (`File > Import > Wavefront (.obj)`).
2. **Select** all mesh objects you want to process.
3. Open the **N-panel** in the 3D Viewport (`N`) and switch to the **Bannerlord** tab.
4. Adjust settings if needed.
5. Click **Process Prefab**.

Settings persist across Blender sessions.

## Merge Methods

| Method | What it does | Result |
|--------|--------------|--------|
| **Cull Interior** (default) | Builds a cheap closed voxel shell (auto-sized to bounding-box/1000) and uses ray-cast parity to delete only provably buried faces. | Keeps the original surface, UVs, materials and thin details. Stays an open surface, like the source. |
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
| **Consolidate Materials** | Merge duplicate materials and remap faces |
| **bo_ Decimate Mode** | `Ratio` or `Target Faces` (physics mesh) |
| **bo_ Decimate Ratio** / **bo_ Target Face Count** | Physics-mesh reduction (whichever mode is active) |
| **bo_ Filter Detail** | Reverse-curvature decimation: collapse fine detail and creases first, keeping smooth bulky regions |
| **bo_ Filter Strength** | Strength of the above |
| **Export After Processing** | Automatically export FBX when processing finishes |
| **Export Path** | Output directory for the exported files |
| **Quick Export Path** | Separate output directory for the **Export Selected as FBX** button |

## Output

| File | Contents |
|------|----------|
| `<prefab_name>.fbx` | Merged visual mesh. Cull mode keeps the original surfaces; Voxel mode is a watertight resurface |
| `bo_<prefab_name>.fbx` | Physics mesh. No materials, no UVs, no vertex groups |

### `bo_` behaviour

- **Cull mode:** `bo_` is a decimated copy of the finished render mesh, so it tracks the real silhouette. Because the render mesh is an open surface, so is `bo_`.
- **Voxel mode:** `bo_` is watertight.
- Islands that are physically detached from the main assembly, and islands that decimate down to a few stray faces, are pruned from `bo_` only. The render mesh always keeps every island.
- `bo_ Filter Detail` cannot remove detached sticks on its own: reverse-curvature weighting protects the smooth parts of each piece, so a small isolated stick survives even at strength `1.0`. The island pruning is what removes them.

## Requirements

- Blender 4.5
- Mount & Blade II: Bannerlord Modding Kit (to export prefabs as OBJ)

## Notes

- A Bannerlord mesh may use only one material. Multi-material meshes are exported as automatically named submeshes, so **Consolidate Materials** is on by default.
- An "island" here is a topologically disconnected face component (faces joined through shared edges). That is *not* the same as a separate object: a kitbash is assembled from pieces that intersect without sharing an edge, so one physical object routinely arrives as dozens of islands.
