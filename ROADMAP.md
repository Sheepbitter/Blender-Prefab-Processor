# Roadmap

Versioning note: **v1.0 is the first complete release.** Everything before it was `0.x`
development. `v1.0` is tagged on the remote; `bl_info["version"]` should be aligned to
`(1, 0, 0)` (it currently reads `(1, 2, 0)`).

| Version | Theme | Status |
|---------|-------|--------|
| v1.0 | First complete release | shipped (tagged) |
| v1.0.1 | Recommended settings become the defaults | **done**, pending release |
| v1.0.2 | Settings actually persist across sessions | planned |
| v1.1 | Auto LODs | **implemented** |
| v1.2 | Weld overlapping faces → complete interior cull | planned |
| v1.3 | Batch processing | planned |
| v2.0 | Standalone tool (no Blender) | concept |

Order matters: **1.0.2 first.** The persistence fix is the foundation the other work
stands on (and is a prerequisite for the standalone config in 2.0).

---

## v1.0.1 — Recommended settings become the defaults

**Status: done.** Defaults were changed in both places they live
(`ui.register()` scene properties and `BANNERLORD_AddonPreferences`):

| Setting | Value |
|---|---|
| Merge Method | Cull Interior |
| Simplify Method | Curvature-Weighted |
| Detail Weight | 0.7 |
| Decimate Mode | Ratio |
| Decimate Passes | 10 |
| Consolidate Materials | on |
| bo_ Decimate Mode | Ratio |
| bo_ Decimate Ratio | 0.05 |
| Filter Detail | on |
| bo_ Filter Strength | 0.7 |
| Export After Processing | on |

Remaining for release: bump `bl_info["version"]` to `(1, 0, 1)` and tag `v1.0.1`.

---

## v1.0.2 — Fix settings persistence

### Symptom
Settings do not come back after restarting Blender.

### Where it lives now
- **Values:** `Scene.bl_*` properties in `ui.py` (the panel binds to these).
- **Storage:** `BANNERLORD_AddonPreferences` in `__init__.py`, saved by Blender into
  `userpref.blend`.
- **Write path:** `ui.save_preferences()` — called from **one place only**,
  `BANNERLORD_OT_process_prefab.execute()` (`operators.py` ~L222).
- **Read path:** `ui.load_preferences()` — registered once as a timer,
  `bpy.app.timers.register(load_preferences, first_interval=0.1)` (`ui.py` L258).

### Verified facts (Blender 4.5)
- `bpy.app.handlers` has **no `save_prefs`** handler. It has `load_post`,
  `load_factory_startup_post`, `load_factory_preferences_post`, `save_pre`, `save_post`.
- `bpy.context.preferences.use_preferences_save` is `True` by default, so
  AddonPreferences are auto-written. **The save side is not the primary problem.**

### Root cause (leading hypothesis — confirm in GUI before fixing)
The panel edits **Scene** properties, which are stored **per `.blend`**. The timer only
runs once at startup, on whatever scene happens to be open. So:

1. Open any existing `.blend` → its saved `bl_*` values load *after* the timer fires
   (or the timer fired for a different scene) → settings are stale.
2. Any setting changed but not followed by **Process Prefab** is never copied to prefs at
   all (write path is only in `execute`).
3. `load_preferences()` returns `None` on its early exits (`if not bpy.context.scene`,
   `if not addon`) — returning `None` unregisters a Blender timer, so a single bad tick
   means it never retries.

### Approach — make AddonPreferences the single source of truth
Delete the scene mirror. This is the clean fix and the one that survives opening `.blend`
files and the standalone port.

- Panel draws the prefs directly: `prefs = context.preferences.addons[ADDON_ID].preferences`,
  then `col.prop(prefs, "simplify_method")` (no `bl_`-prefixed Scene properties).
- `execute()` reads `self.x = prefs.x` instead of `scene.bl_x`.
- Delete `PREF_FIELDS`, `load_preferences`, `save_preferences`, and the timer.
- Remove the `Scene.bl_*` property registration/unregistration.
- Keep `AddonPreferences.draw()` minimal; give the panel a "Reset to defaults" button.

Why this is correct: prefs already auto-save (`use_preferences_save`), are global (not
per-file), and are exactly what a standalone tool would also load.

### Alternatives (only if prefs-as-truth is rejected)
- Keep the mirror, but re-apply on `load_post` **and** `load_factory_startup_post`
  instead of a timer, and save whenever a value changes (a `update=` callback per
  property, debounced).
- Or manage a JSON settings file in the addon dir (read on `register`, write on change).
  This is the most portable option and the natural bridge to v2.0, but it is more code.

### Verification (must be a real GUI restart, not `--background`)
1. Change every setting, quit Blender, relaunch → all values restored.
2. Open an unrelated existing `.blend` → values restored (the current bug).
3. Change settings and quit **without** running the processor → still restored.
4. Blender headless (`--background`) must not crash on enable (timers do not tick there,
   so any timer dependency masks the bug — another reason to drop the timer).

---

## v1.1 — Auto LODs

> **Status: implemented.** As designed below, with these outcomes: LOD 0 **is** the main
> mesh and is never modified; ratios are measured against LOD 0 (defaults 0.9 / 0.8 /
> 0.6 / 0.4 / 0.2 / 0.05, editable, `0` skips a LOD); LODs keep UVs and materials; `bo_`
> is not LOD'd; all LODs are exported into the same FBX as LOD 0; the `.lodN` suffix is
> set on both the object and its mesh data.

### Goal
Generate Bannerlord LOD meshes automatically: pick how many, decimate each, optionally
fine-tune, and export with the correct names so the engine associates them.

### Engine convention
Bannerlord recognises LODs by name suffix: `<name>.lod1`, `<name>.lod2`, … (confirm the
exact separator — `.lodN` vs `_lodN` — against a shipped Bannerlord LOD asset before
implementing; the naming is the whole feature, so get it from a real asset, not a guess).

### Design
- New settings: `lod_enabled`, `lod_count` (e.g. 0–4 extra LODs), and a decimation
  schedule. Two options, pick one:
  - **Simple:** one `lod_decay` factor (each LOD = previous × decay, default ≈ 0.5),
    giving 100% / 50% / 25% / 12.5%.
  - **Fine-tunable:** per-slot mode+ratio (a fixed array of slots is far easier in Blender
    UI than a dynamic property list), defaulting to the decay schedule.
- Generate **LOD0** = the existing simplified main mesh. Each `lodN` is a *duplicate of
  LOD0* decimated to its cumulative ratio (decimating from LOD0 each time avoids
  compounding artifacts; chaining from the previous LOD is cheaper but drifts). Reuse the
  existing `_simplify_mesh` / `_decimate_physics` machinery on the duplicate.
- **LODs keep UVs and materials** (they are visual). Only `bo_` is stripped.
- **`bo_` is not LOD'd:** Bannerlord physics is a single mesh; leave the existing single
  `bo_` behaviour untouched.
- Export each LOD as its own FBX with the same flags as `_export_obj` (`operators.py`
  ~L1129), named `<base>.lodN`. Keep the object name inside the FBX as `<base>.lodN` too.

### Risks / notes
- LODs must share the base mesh's material set and UV layout or the engine seams/flickers;
  verify material slot order is identical across LODs.
- Very low LODs on thin kitbash detail can collapse to noise — the bo_ island-pruning
  logic (`_drop_small_islands`) is a good reference for a "LOD cleanup" pass.

### Verification
Export a multi-LOD asset, confirm file count/names, face counts descending, identical
material slots, and load it in the Modding Kit to see LOD switching.

---

## v1.2 — Weld overlapping faces → complete interior cull

### Goal
Remove the "safety net" in the interior cull so it becomes complete and total, without
introducing holes.

### Background: what the safety net is
`_cull_interior` (`operators.py` L631) deletes a face only when **every** vertex is
provably buried. Two of its steps are a deliberate margin:
- **Step 2** propagates "exterior" one face-hop through adjacency *before* ray-casting.
- **Step 4** propagates once more, then deletes all-interior faces.

That margin exists because the kitbash is a set of **disconnected islands that merely
interpenetrate** — there are no shared edges between pieces. Removing a face adjacent to a
kept surface could open a gap, so the cull errs toward keeping. The docstring already
records why propagation is exactly one hop (a Gauss-Seidel sweep cascades and rescues
whole islands: 30.4% → 8.7% culled).

### The idea
If the intersecting pieces were **genuinely welded** (real shared edges along the
intersection curves), the topology would be connected, interior faces would be truly
enclosed, and the margin could be dropped — letting the cull delete everything provably
buried.

### Candidate implementation
1. After joining, cut the mesh against itself to create the intersection edges:
   - `bpy.ops.mesh.intersect(mode='SELECT_UNSELECT', separate_mode='CUT',
     solver='EXACT')` in edit mode, all faces selected.
   - Params confirmed present in 4.5: `mode`, `separate_mode`, `threshold`, `solver`.
     Note `bmesh.ops` has **no** intersect ops in 4.5, so this must be the operator.
2. `bpy.ops.mesh.remove_doubles` at a small threshold to merge the coincident
   intersection vertices coming from the two surfaces → shared edges between pieces.
   (The cull already welds with `remove_doubles(0.0001)` near L788.)
3. Run `_cull_interior` **without** the step-2/step-4 propagation margin.

### Risks (this is the riskiest item — spike it before committing)
- `mesh.intersect` on large kitbashes is potentially slow and fragile; it can emit
  degenerate/tiny faces and non-manifold results.
- **Coplanar / near-coplanar overlaps** are ill-defined for intersection; real kitbashes
  contain them.
- The operator interpolates UVs/materials at the cuts — check the render mesh still looks
  right (this is a modification of the original surface, unlike the current cull which
  never resamples).
- Welding can also join pieces that *look* separate, changing island semantics that bo_
  pruning relies on.

### Verification
- Metric: % of faces culled (before vs after), boundary / 1-face edge count,
  non-manifold edge count.
- **Hole test:** ray-cast from outside along many directions; assert no ray reaches an
  interior point through a deleted region (this is the property the safety net protected).
- Visual check on the earthworks exports **and** the fence kitbash (the thin-stick case).
- Measure intersect cost (seconds, face-count growth) on the largest asset you have.

---

## v1.3 — Clean batch processing

### Goal
Process a folder of OBJ exports unattended, with a reliable per-file report.

### Design
- New operator (e.g. `bannerlord.batch_process`) plus a panel section:
  - `input_dir`, `output_dir`, optional `pattern` (default `*.obj`), `recursive`.
  - `skip_existing` and `dry_run` options.
- Loop per file: import OBJ → select imported meshes → run the existing `_run_pipeline`
  → export → remove the imported objects/meshes.
- Uses the **single set of saved settings** for all files (uniform pipeline), with an
  optional per-file JSON override later.
- **Report:** one line per file (name, input faces → main faces + bo faces, status,
  seconds) and a summary at the end; always list failures explicitly, never a silent
  no-op (the single-file path already does this at `operators.py` ~L1159).
- **Headless:** must run under `blender --background --python`, which also means not
  depending on UI/selection quirks — manage `context.view_layer` explicitly.

### Risks / notes
- Name collisions and partial failures across a long run → continue-on-error and a
  returned failure count.
- This is where the v1.0.2 prefs-as-truth change pays off: no scene to set up per file.

### Verification
Run a folder of the test assets, confirm output file counts and that the summary matches
the individual runs.

---

## v2.0 — Standalone tool (concept, no Blender)

The pipeline (join → cull interior → simplify → materials → bo_ → FBX) is mostly geometry
math; Blender is the current host, not a requirement. Target a hybrid: a standalone core
that can run without Blender, plus the Blender addon as an optional front end for manual
touch-ups.

Not planned in detail yet. Prerequisites that make it cheaper later:
- **v1.0.2** — a settings format not tied to Blender preferences.
- **v1.2** — decide the final cull algorithm (with or without the safety margin) before
  porting it.
- Keep the algorithm functions free of UI/context where possible.

The core would reimplement: parity-based interior cull (BVH ray casts), collapse
decimation, material consolidation, and FBX I/O — the last being the biggest unknown
outside Blender.
