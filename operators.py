import bpy
import bmesh
import math
import os
from mathutils import Vector
from mathutils.bvhtree import BVHTree
from bpy.props import FloatProperty, BoolProperty, EnumProperty, StringProperty
from bpy.types import Operator

# Two islands closer than this are treated as physically touching. Measured on
# the earthworks exports, results are identical from 0.0 to 0.01, so this only
# has to bridge coincident surfaces rather than model a fuzzy distance.
ISLAND_MERGE_EPS = 0.001

# bo_ collision-proxy size threshold. An island smaller than this fraction of
# the largest island is a stick, not a collision shape. See _drop_small_islands.
BO_ISLAND_MIN_FRACTION = 0.10


class BANNERLORD_OT_process_prefab(Operator):
    """Process Bannerlord prefab: merge meshes, generate bo_ physics mesh, consolidate materials"""
    bl_idname = "bannerlord.process_prefab"
    bl_label = "Process Prefab"
    bl_options = {'REGISTER', 'UNDO'}

    decimate_ratio: FloatProperty(
        name="Decimate Ratio",
        description="Ratio of faces to keep on the main mesh (lower = fewer polys)",
        default=0.5,
        min=0.01,
        max=1.0,
        step=0.01,
    )

    voxel_size: FloatProperty(
        name="Voxel Size",
        description="Size of voxels for remeshing (lower = more detail, higher = smaller mesh). 0.005 preserves fine details",
        default=0.01,
        min=0.001,
        max=1.0,
        step=0.001,
    )

    simplify_method: EnumProperty(
        name="Simplify Method",
        description="How to simplify the mesh while preserving detail",
        items=[
            ('PLANAR', "Planar Pre-Pass", "Merges flat regions first, then decimates. Good balance of speed and quality"),
            ('CURVATURE', "Curvature-Weighted", "Protects high-curvature areas during decimation. Best detail preservation"),
            ('STANDARD', "Standard Decimate", "Plain ratio-based decimation. Fastest but may lose detail"),
        ],
        default='CURVATURE',
    )

    decimate_passes: bpy.props.IntProperty(
        name="Decimate Passes",
        description="Number of decimation passes (higher = better silhouette preservation)",
        default=10,
        min=1,
        max=10,
        step=1,
    )

    target_faces: bpy.props.IntProperty(
        name="Target Face Count",
        description="Target face count for decimation (used when Decimate Mode is Target Faces)",
        default=0,
        min=1,
        max=1000000,
    )

    decimate_mode: EnumProperty(
        name="Decimate Mode",
        description="How to size the main mesh",
        items=[
            ('RATIO', "Ratio", "Keep a ratio of the original faces"),
            ('TARGET', "Target Faces", "Reduce to an absolute face count"),
        ],
        default='RATIO',
    )

    detail_weight: FloatProperty(
        name="Detail Weight",
        description="How strongly to protect fine details during decimation (0 = no protection, 1 = maximum protection)",
        default=0.7,
        min=0.0,
        max=1.0,
        step=0.05,
    )

    voxel_adaptivity: FloatProperty(
        name="Voxel Adaptivity",
        description="Removes voxels in flat regions to cut face count while keeping curved detail. 0 = off. Note this disables Fix Poles",
        default=0.0,
        min=0.0,
        max=1.0,
        step=0.01,
    )

    bo_decimate_mode: EnumProperty(
        name="bo_ Decimate Mode",
        description="How to size the physics mesh",
        items=[
            ('RATIO', "Ratio", "Keep a ratio of the main mesh faces"),
            ('TARGET', "Target Faces", "Reduce to an absolute face count"),
        ],
        default='RATIO',
    )

    bo_decimate_ratio: FloatProperty(
        name="bo_ Decimate Ratio",
        description="Ratio of main mesh faces to keep for the physics mesh",
        default=0.05,
        min=0.001,
        max=1.0,
        step=0.005,
    )

    bo_target_faces: bpy.props.IntProperty(
        name="bo_ Target Face Count",
        description="Target face count for the physics mesh",
        default=500,
        min=1,
        max=1000000,
    )

    bo_filter_detail: BoolProperty(
        name="Filter Detail",
        description="Reverse-curvature decimation: collapse fine detail and creases first, keeping smooth bulky regions. Better collision proxy at the same face budget",
        default=True,
    )

    bo_filter_strength: FloatProperty(
        name="bo_ Filter Strength",
        description="How aggressively detail is filtered. 0 = uniform collapse, 1 = maximum detail removal",
        default=0.7,
        min=0.0,
        max=1.0,
        step=0.05,
    )

    lod_enabled: BoolProperty(
        name="Auto Generate LODs",
        description="Generate <name>.lod1 ... <name>.lod6 from the finished main mesh. LOD 0 is the main mesh itself and is never modified",
        default=True,
    )

    # These are a transfer bag, synced from the scene in execute() and never
    # drawn in UI, so they skip the description/step/precision ceremony.
    lod1_enabled: BoolProperty(name="LOD1", default=True)
    lod2_enabled: BoolProperty(name="LOD2", default=True)
    lod3_enabled: BoolProperty(name="LOD3", default=True)
    lod4_enabled: BoolProperty(name="LOD4", default=True)
    lod5_enabled: BoolProperty(name="LOD5", default=True)
    lod6_enabled: BoolProperty(name="LOD6", default=True)

    lod1_ratio: FloatProperty(name="LOD1 Ratio", default=0.9, min=0.01, max=1.0)
    lod2_ratio: FloatProperty(name="LOD2 Ratio", default=0.8, min=0.01, max=1.0)
    lod3_ratio: FloatProperty(name="LOD3 Ratio", default=0.6, min=0.01, max=1.0)
    lod4_ratio: FloatProperty(name="LOD4 Ratio", default=0.4, min=0.01, max=1.0)
    lod5_ratio: FloatProperty(name="LOD5 Ratio", default=0.2, min=0.01, max=1.0)
    lod6_ratio: FloatProperty(name="LOD6 Ratio", default=0.05, min=0.01, max=1.0)

    merge_method: EnumProperty(
        name="Merge Method",
        description="How overlapping kitbash parts are merged",
        items=[
            ('CULL', "Cull Interior", "Build a cheap closed voxel shell, then delete only provably buried faces (distance + ray-cast parity). Keeps the original surface, UVs and thin details. Result is an open surface, like the source"),
            ('VOXEL', "Voxel Remesh", "Resurface everything into one watertight shell at Voxel Size. Closed and overlap-free, but blocky and can lose sub-voxel detail"),
        ],
        default='CULL',
    )

    island_culling: BoolProperty(
        name="Cull Floaters",
        description="Voxel Remesh mode only: delete islands that are physically detached from the main assembly. Cull Interior always keeps every island",
        default=True,
    )

    consolidate_materials: BoolProperty(
        name="Consolidate Materials",
        description="Merge duplicate materials and remap faces",
        default=True,
    )

    export_after: BoolProperty(
        name="Export After Processing",
        description="Export processed meshes as OBJ after completion",
        default=True,
    )

    export_path: bpy.props.StringProperty(
        name="Export Path",
        description="Output directory for OBJ export",
        default="",
        subtype='DIR_PATH',
    )

    @classmethod
    def poll(cls, context):
        return context.selected_objects and any(o.type == 'MESH' for o in context.selected_objects)

    def execute(self, context):
        scene = context.scene

        # Sync operator properties from scene properties
        self.decimate_ratio = scene.bl_decimate_ratio
        self.voxel_size = scene.bl_voxel_size
        self.voxel_adaptivity = scene.bl_voxel_adaptivity
        self.simplify_method = scene.bl_simplify_method
        self.decimate_passes = scene.bl_decimate_passes
        self.target_faces = scene.bl_target_faces
        self.decimate_mode = scene.bl_decimate_mode
        self.detail_weight = scene.bl_detail_weight
        self.bo_target_faces = scene.bl_bo_target_faces
        self.bo_decimate_mode = scene.bl_bo_decimate_mode
        self.bo_decimate_ratio = scene.bl_bo_decimate_ratio
        self.bo_filter_detail = scene.bl_bo_filter_detail
        self.bo_filter_strength = scene.bl_bo_filter_strength
        self.merge_method = scene.bl_merge_method
        self.island_culling = scene.bl_island_culling
        self.consolidate_materials = scene.bl_consolidate_materials
        self.export_after = scene.bl_export_after
        self.export_path = scene.bl_export_path
        self.lod_enabled = scene.bl_lod_enabled
        for i in range(1, 7):
            setattr(self, f"lod{i}_enabled", getattr(scene, f"bl_lod{i}_enabled"))
            setattr(self, f"lod{i}_ratio", getattr(scene, f"bl_lod{i}_ratio"))

        # Store original selection
        original_selection = context.selected_objects.copy()

        # Filter to mesh objects only
        mesh_objects = [o for o in original_selection if o.type == 'MESH']
        if not mesh_objects:
            self.report({'ERROR'}, "No mesh objects selected")
            return {'CANCELLED'}

        # Ensure we're in object mode
        if context.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')

        # Remember the starting size so the result can be reported as a before/after
        self.source_faces = sum(len(o.data.polygons) for o in mesh_objects)

        # Persist the settings used for this run. Never let a persistence
        # problem block the actual processing.
        try:
            from .ui import save_preferences
            save_preferences(context)
        except Exception:
            pass

        try:
            self._run_pipeline(mesh_objects, context)
        except Exception as exc:
            # Surface the failure in the UI. Blender's default behaviour is to
            # dump a traceback to the system console, which is easy to miss and
            # leaves the user thinking nothing happened.
            self.report(
                {'ERROR'},
                f"Processing failed: {type(exc).__name__}: {exc}. "
                f"Full traceback is in the system console (Window > Toggle System Console).",
            )
            raise
        return {'FINISHED'}

    def _run_pipeline(self, mesh_objects, context):
        # Step 1: Apply all modifiers and transforms
        self._apply_modifiers_and_transforms(mesh_objects)

        # Step 2: Join all mesh objects into one
        merged_obj = self._join_meshes(mesh_objects, context)

        if self.merge_method == 'CULL':
            # No island culling here, deliberately. This mode already decides
            # what belongs to the asset by other means: buried faces are deleted
            # by the voxel-shell + parity test, and exterior pieces the
            # voxelizer missed are rescued by the same test. Island culling
            # would only add a third, worse opinion -- a small stick resting
            # against the body is a legitimate part of the kitbash, and a kit
            # that shouldn't be there should be fixed in the kitbash. Anything
            # genuinely unwanted is interior and already removed.
            #
            # Step 3: delete provably buried interior faces
            merged_obj = self._cull_interior(merged_obj, context)

            # Step 5: Simplify mesh while preserving detail
            self._simplify_mesh(merged_obj)

            # Step 5b: Re-clean after decimation (decimation creates new loose specks)
            self._cleanup_mesh(merged_obj)

            # Step 6: physics is a decimated copy of this result
            bo_obj = self._generate_physics_mesh_cull(merged_obj, context)
        else:
            # Step 3: Merge intersecting geometry (voxel remesh always produces a single shell)
            merged_obj = self._voxel_remesh(merged_obj, context)

            # Step 4: Clean up mesh
            self._cleanup_mesh(merged_obj)

            # Step 5: Simplify mesh while preserving detail
            self._simplify_mesh(merged_obj)

            # Step 5b: Re-clean after decimation (decimation creates new loose specks)
            self._cleanup_mesh(merged_obj)

            # Step 6: Generate bo_ physics mesh
            bo_obj = self._generate_physics_mesh(merged_obj, context)

        # Step 6b: Clean up the physics mesh too (decimation creates floaters)
        self._cleanup_mesh(bo_obj)

        # Step 7: Consolidate materials (bo_ is stripped, so main mesh only)
        if self.consolidate_materials:
            self._consolidate_materials(merged_obj)

        # Step 7b: auto LODs. Deliberately AFTER consolidation so every LOD
        # inherits the same deduplicated material slots as LOD 0.
        lod_objs = self._generate_lods(merged_obj, context)

        # Step 8: Export if requested
        if self.export_after:
            if not self.export_path:
                self.report(
                    {'WARNING'},
                    "Export After Processing is on but Export Path is empty - "
                    "nothing was written. Set a path in the Bannerlord panel.",
                )
            else:
                self._export_obj(merged_obj, bo_obj, context, lod_objs)

        # Select the results
        bpy.ops.object.select_all(action='DESELECT')
        merged_obj.select_set(True)
        bo_obj.select_set(True)
        for lod in lod_objs:
            lod.select_set(True)
        context.view_layer.objects.active = merged_obj

        src_faces = getattr(self, "source_faces", 0)
        main_faces = len(merged_obj.data.polygons)
        bo_faces = len(bo_obj.data.polygons)
        lod_txt = ", ".join(
            f"{o.name}={len(o.data.polygons):,}" for o in lod_objs
        ) or "none"
        self.report(
            {'INFO'},
            f"Input {src_faces:,} faces -> main {main_faces:,} + bo_ {bo_faces:,} "
            f"(physics is {100.0 * bo_faces / main_faces:.1f}% of main) "
            f"| LODs: {lod_txt}",
        )

    def _apply_modifiers_and_transforms(self, objects):
        """Apply all modifiers and transforms to each object"""
        for obj in objects:
            bpy.context.view_layer.objects.active = obj
            bpy.ops.object.select_all(action='DESELECT')
            obj.select_set(True)

            # Apply modifiers
            for mod in list(obj.modifiers):
                try:
                    bpy.ops.object.modifier_apply(modifier=mod.name)
                except RuntimeError:
                    pass  # Skip modifiers that can't be applied

            # Apply transforms
            bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)

    def _join_meshes(self, objects, context):
        """Join all mesh objects into one"""
        bpy.ops.object.select_all(action='DESELECT')
        for obj in objects:
            obj.select_set(True)
        context.view_layer.objects.active = objects[0]
        bpy.ops.object.join()
        return context.active_object

    def _voxel_remesh(self, obj, context):
        """Voxel remesh, merging overlapping geometry into one watertight shell.

        Uses bpy.ops.object.voxel_remesh() rather than the Remesh modifier,
        because only the operator honours Mesh.use_remesh_preserve_attributes.
        That reprojects every mesh attribute onto the regenerated surface, so
        material indices AND UV layers survive. The modifier has no such flag,
        which is why the previous version needed a manual KDTree transfer.
        """
        if context.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')

        bpy.ops.object.select_all(action='DESELECT')
        obj.select_set(True)
        context.view_layer.objects.active = obj

        # Keep material indices and UVs across the remesh
        obj.data.use_remesh_preserve_attributes = True
        obj.data.use_remesh_preserve_volume = False
        obj.data.remesh_voxel_size = self.voxel_size

        # Adaptive voxels drop occupancy in locally-flat regions, cutting face
        # count without flattening curved detail. This disables Fix Poles.
        if self.voxel_adaptivity > 0.0:
            obj.data.remesh_voxel_adaptivity = self.voxel_adaptivity

        bpy.ops.object.voxel_remesh()

        # Clean up any remaining issues
        bpy.ops.object.mode_set(mode='EDIT')
        bpy.ops.mesh.select_all(action='SELECT')
        bpy.ops.mesh.remove_doubles(threshold=0.0001)
        bpy.ops.mesh.normals_make_consistent(inside=False)
        bpy.ops.object.mode_set(mode='OBJECT')

        return obj

    def _cleanup_mesh(self, obj):
        """Clean up mesh: remove doubles, delete loose geometry, recalc normals"""
        bpy.ops.object.select_all(action='DESELECT')
        obj.select_set(True)
        bpy.context.view_layer.objects.active = obj

        # Enter edit mode
        bpy.ops.object.mode_set(mode='EDIT')

        # Select all
        bpy.ops.mesh.select_all(action='SELECT')

        # Remove doubles
        bpy.ops.mesh.remove_doubles(threshold=0.0001)

        # Delete loose geometry
        bpy.ops.mesh.delete_loose()

        # Recalculate normals
        bpy.ops.mesh.normals_make_consistent(inside=False)

        # Back to object mode
        bpy.ops.object.mode_set(mode='OBJECT')

        # Drop floater islands: Voxel mode only. Voxel remesh always yields one
        # closed shell, so any island left afterwards is debris created by
        # decimation or a genuinely separate object in the kit. Cull mode is
        # deliberately excluded -- see _run_pipeline.
        if self.island_culling and self.merge_method == 'VOXEL':
            self._drop_floaters(obj)

    

    def _drop_floaters(self, obj):
        """Delete islands that are physically detached from the main assembly.

        An island here is a topologically disconnected face component -- joined
        only through shared edges. That is NOT the same as a separate object: a
        kitbash is assembled from pieces that intersect without sharing an edge,
        so one physical object routinely arrives as dozens of islands.

        Measuring the earthworks exports: each is ONE object whose every island
        intersects another, transitively forming a single group covering 100%
        of the mesh. Keep-largest-island, which assumes topologically = one
        object, therefore kept only 8-9% of them and destroyed the rest.

        So islands are grouped by physical intersection instead, and only groups
        that touch nothing else are deleted. On the measured files that keeps
        all of earthworks_a/b/c and keeps the 172-island assembly of earth_wall
        while dropping its 58 detached 8-face specks. Results are identical from
        eps 0.0 to 0.01, so this is hard intersection rather than a tunable
        distance heuristic.
        """
        mesh = obj.data
        bm = bmesh.new()
        bm.from_mesh(mesh)
        bm.faces.ensure_lookup_table()
        bm.faces.index_update()
        bm.verts.ensure_lookup_table()

        visited = [False] * len(bm.faces)
        islands = []
        for seed in bm.faces:
            if visited[seed.index]:
                continue
            comp = []
            stack = [seed]
            visited[seed.index] = True
            while stack:
                f = stack.pop()
                comp.append(f)
                for e in f.edges:
                    for nf in e.link_faces:
                        if not visited[nf.index]:
                            visited[nf.index] = True
                            stack.append(nf)
            islands.append(comp)

        if len(islands) <= 1:
            bm.free()
            return

        # One BVH per island, plus its bounding box to skip far-apart pairs
        # before paying for an overlap test.
        trees = []
        boxes = []
        for comp in islands:
            vidx = sorted({v.index for f in comp for v in f.verts})
            verts = [bm.verts[k].co.copy() for k in vidx]
            remap = {k: j for j, k in enumerate(vidx)}
            polys = [[remap[v.index] for v in f.verts] for f in comp]
            trees.append(BVHTree.FromPolygons(
                verts, polys, all_triangles=False, epsilon=ISLAND_MERGE_EPS))
            boxes.append((
                [min(c[k] for c in verts) for k in range(3)],
                [max(c[k] for c in verts) for k in range(3)],
            ))

        parent = list(range(len(islands)))

        def find(a):
            while parent[a] != a:
                parent[a] = parent[parent[a]]
                a = parent[a]
            return a

        def union(a, b):
            ra, rb = find(a), find(b)
            if ra != rb:
                parent[rb] = ra

        for i in range(len(islands)):
            for j in range(i + 1, len(islands)):
                gap = 0.0
                for k in range(3):
                    if boxes[i][1][k] < boxes[j][0][k]:
                        gap += (boxes[j][0][k] - boxes[i][1][k]) ** 2
                    elif boxes[j][1][k] < boxes[i][0][k]:
                        gap += (boxes[i][0][k] - boxes[j][1][k]) ** 2
                if math.sqrt(gap) > ISLAND_MERGE_EPS:
                    continue
                if trees[i].overlap(trees[j]):
                    union(i, j)

        groups = {}
        for i in range(len(islands)):
            groups.setdefault(find(i), []).append(i)

        def group_faces(g):
            return sum(len(islands[i]) for i in g)

        keep = max(groups.values(), key=group_faces)

        doomed = []
        n_dropped = 0
        for root, members in groups.items():
            if members is keep:
                continue
            for i in members:
                doomed.extend(islands[i])
                n_dropped += 1

        if not doomed:
            bm.free()
            return

        bmesh.ops.delete(bm, geom=doomed, context='FACES')
        loose = [v for v in bm.verts if not v.link_faces]
        if loose:
            bmesh.ops.delete(bm, geom=loose, context='VERTS')
        bm.to_mesh(mesh)
        bm.free()
        mesh.update()
        print(
            f"Kept {len(keep)} islands ({group_faces(keep)} faces) of "
            f"{len(islands)}; dropped {n_dropped} detached islands "
            f"({len(doomed)} faces)"
        )

    def _drop_small_islands(self, obj, fraction):
        """Delete islands below a fraction of the largest island's face count.

        This is a SIZE rule, answering "is this too small to matter?" rather
        than the intersection rule's "is this a separate object?". The two are
        complementary and neither alone is right for a bo_ collision proxy.

        Intersection alone does not strip sticks: the sticks INTERSECT the body,
        so they belong to the main group and are kept. Measured on the
        simplified render mesh, the intersection pass leaves 81-117 islands, and
        the size distribution is sharply bimodal:

            earthworks_a  495 413 391 383 369 357 331 257 250 221 | 66 53 51 50 ...
                                            10 substantial pieces             sticks

        A cliff after ~10 pieces makes a 10% threshold a clean split rather
        than a tuned guess: it keeps all ten real pieces and removes the
        50-66-face sticks below.
        """
        mesh = obj.data
        bm = bmesh.new()
        bm.from_mesh(mesh)
        bm.faces.ensure_lookup_table()
        bm.faces.index_update()

        visited = [False] * len(bm.faces)
        islands = []
        for seed in bm.faces:
            if visited[seed.index]:
                continue
            comp = []
            stack = [seed]
            visited[seed.index] = True
            while stack:
                f = stack.pop()
                comp.append(f)
                for e in f.edges:
                    for nf in e.link_faces:
                        if not visited[nf.index]:
                            visited[nf.index] = True
                            stack.append(nf)
            islands.append(comp)

        if len(islands) <= 1:
            bm.free()
            return

        sizes = [len(c) for c in islands]
        floor = max(1, int(round(max(sizes) * fraction)))
        doomed = []
        n_dropped = 0
        for comp, size in zip(islands, sizes):
            if size < floor:
                doomed.extend(comp)
                n_dropped += 1

        if not doomed:
            bm.free()
            return

        bmesh.ops.delete(bm, geom=doomed, context='FACES')
        loose = [v for v in bm.verts if not v.link_faces]
        if loose:
            bmesh.ops.delete(bm, geom=loose, context='VERTS')
        bm.to_mesh(mesh)
        bm.free()
        mesh.update()
        print(
            f"bo_ dropped {n_dropped} small islands (< {floor} faces, "
            f"largest {max(sizes)}); kept {len(islands) - n_dropped}"
        )

    def _parity_inside(self, bvh, co, direction, eps):
        """True only if rays in BOTH directions cross the shell an odd number
        of times. Any even count proves the point is outside the closed shell,
        so a single even result classifies the point as exterior."""
        for sign in (1.0, -1.0):
            d = direction * sign
            org = co + d * eps
            hits = 0
            while hits <= 64:
                loc, nrm, idx, dist = bvh.ray_cast(org, d, 1.0e30)
                if loc is None:
                    break
                hits += 1
                org = loc + d * eps
            if hits % 2 == 0:
                return False
        return True

    def _cull_interior(self, obj, context):
        """Delete provably buried interior faces, guided by a voxel shell.

        A cheap closed voxel shell (bounding-box diagonal / 1000, adaptivity
        off so the shell is tight) acts as an inside/outside oracle for the
        ORIGINAL geometry. The original surface is never resampled: surviving
        faces are the source faces, so UVs, materials and thin detail are
        preserved exactly and the result is not blocky.

        A face is deleted only when EVERY vertex is provably buried:
          1. Vertices within one voxel of the shell surface are exterior.
          2. Exterior-ness propagates one pass through face adjacency, so a
             face that intersects inwards keeps its far vertices alive
             through its near-surface neighbours.
          3. Remaining uncertain vertices are ray-cast against the shell:
             even parity in either direction proves outside, odd in both
             directions proves inside.
          4. Exterior-ness propagates once more, then faces whose vertices
             are ALL still interior are deleted.

        Propagation is bounded to ONE face-hop per stage: each stage decides
        from a snapshot of the flags taken before that stage starts, so a
        vertex rescued in this stage cannot rescue anything within the same
        stage. Mutating live state mid-sweep instead (Gauss-Seidel) looks like
        one pass but cascades through the whole face list and rescues entire
        connected islands -- measured, that collapsed culling from 30.4% to
        8.7% of faces on the earthworks exports.
        """
        if context.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')

        # Selector resolution from the bounding box: measured good across
        # assets (diag/1000). Adaptivity stays off so the shell is accurate.
        bb = obj.bound_box
        xs = [c[0] for c in bb]
        ys = [c[1] for c in bb]
        zs = [c[2] for c in bb]
        diag = math.sqrt(
            (max(xs) - min(xs)) ** 2 +
            (max(ys) - min(ys)) ** 2 +
            (max(zs) - min(zs)) ** 2)
        voxel = max(diag / 1000.0, 1e-5)
        tolerance = voxel          # within one voxel of the shell == exterior
        eps = max(diag * 1e-6, 1e-7)

        # Build the shell on a throwaway copy so the original is untouched.
        bpy.ops.object.select_all(action='DESELECT')
        sel = obj.copy()
        sel.data = obj.data.copy()
        bpy.context.collection.objects.link(sel)
        sel.select_set(True)
        context.view_layer.objects.active = sel
        sel.data.use_remesh_preserve_attributes = True
        sel.data.use_remesh_preserve_volume = False
        sel.data.remesh_voxel_size = voxel
        sel.data.remesh_voxel_adaptivity = 0.0
        bpy.ops.object.voxel_remesh()

        bm_sel = bmesh.new()
        bm_sel.from_mesh(sel.data)
        shell_faces = len(bm_sel.faces)
        bvh = BVHTree.FromBMesh(bm_sel)
        bm_sel.free()

        sel_mesh = sel.data
        bpy.data.objects.remove(sel, do_unlink=True)
        if sel_mesh.users == 0:
            bpy.data.meshes.remove(sel_mesh)

        if shell_faces == 0:
            self.report({'WARNING'}, "Cull skipped: voxel shell came out empty")
            return obj

        bm = bmesh.new()
        bm.from_mesh(obj.data)
        bm.normal_update()
        n_source_faces = len(bm.faces)

        # 1. distance classification
        exterior = []
        n_near = 0
        for v in bm.verts:
            hit = bvh.find_nearest(v.co)
            near = hit[0] is not None and hit[3] <= tolerance
            exterior.append(near)
            if near:
                n_near += 1

        # 2. propagate exterior one pass through faces (before any ray casts,
        #    so propagated vertices never need one)
        #
        # Decides from a SNAPSHOT of the exterior flags, then applies. Reading
        # live state inside the same sweep (Gauss-Seidel) lets a vertex rescued
        # by face 3 rescue face 7 later in that very loop, which floods whole
        # connected islands instead of doing one hop. Measured on the earthworks
        # exports, the cascade rescued 5,075 verts against a true single pass's
        # 1,743 and culled 8.7% of faces instead of 30.4% -- the rule the user
        # asked for is exactly one face-hop from a known-good vertex.
        def propagate():
            snap = list(exterior)
            added = 0
            for f in bm.faces:
                verts = f.verts
                if any(snap[v.index] for v in verts):
                    for v in verts:
                        if not exterior[v.index]:
                            exterior[v.index] = True
                            added += 1
            return added

        n_prop1 = propagate()

        # 3. ray-cast the remainder
        n_cast = 0
        n_outside = 0
        for v in bm.verts:
            if exterior[v.index]:
                continue
            n_cast += 1
            n = v.normal if v.normal.length > 1e-9 else Vector((0.0, 0.0, 1.0))
            if not self._parity_inside(bvh, v.co, n.normalized(), eps):
                exterior[v.index] = True
                n_outside += 1

        # 4. propagate once more, then delete all-interior faces
        n_prop2 = propagate()
        doomed = [f for f in bm.faces if not any(exterior[v.index] for v in f.verts)]
        n_culled = len(doomed)
        bmesh.ops.delete(bm, geom=doomed, context='FACES')

        dead_edges = [e for e in bm.edges if not e.link_faces]
        if dead_edges:
            bmesh.ops.delete(bm, geom=dead_edges, context='EDGES')
        loose = [v for v in bm.verts if not v.link_faces]
        if loose:
            bmesh.ops.delete(bm, geom=loose, context='VERTS')

        bm.to_mesh(obj.data)
        bm.free()
        obj.data.update()
        del bvh

        print(
            f"[cull] shell: {shell_faces:,} faces at voxel {voxel:.5f} | "
            f"verts {n_near:,} near + {n_prop1:,} propagated, "
            f"{n_cast:,} ray-cast ({n_outside:,} outside), +{n_prop2:,} propagated | "
            f"faces removed {n_culled:,} of {n_source_faces:,} "
            f"({100.0 * n_culled / max(1, n_source_faces):.1f}%)"
        )

        # Weld the z-fighting layer the cull deliberately keeps (junk within
        # one voxel of the surface), so the decimator can collapse it.
        bpy.ops.object.select_all(action='DESELECT')
        obj.select_set(True)
        context.view_layer.objects.active = obj
        bpy.ops.object.mode_set(mode='EDIT')
        bpy.ops.mesh.select_all(action='SELECT')
        bpy.ops.mesh.remove_doubles(threshold=0.0001)
        bpy.ops.mesh.normals_make_consistent(inside=False)
        bpy.ops.object.mode_set(mode='OBJECT')

        return obj

    def _resolve_ratio(self, obj):
        """Resolve the overall decimation ratio for the current mesh state.

        Target mode must be evaluated against the face count that exists at
        the moment decimation starts, i.e. AFTER any planar pre-pass, or the
        dissolve's own face removal is counted twice and the target is missed.
        """
        if self.decimate_mode == 'TARGET' and self.target_faces > 0:
            current = len(obj.data.polygons)
            if current > 0:
                return min(1.0, self.target_faces / current)
        return self.decimate_ratio

    def _simplify_mesh(self, obj, target_faces=None):
        """Simplify mesh while preserving detail using the selected method.

        target_faces overrides the user's Decimate Mode with an absolute face
        count. LOD generation passes one in per LOD; the method, Detail Weight
        and pass count still follow the main decimation settings.
        """
        bpy.ops.object.select_all(action='DESELECT')
        obj.select_set(True)
        bpy.context.view_layer.objects.active = obj

        def resolve_ratio():
            # Like _resolve_ratio but against an explicit count. The ratio is
            # taken from the face count present at this moment -- in Planar
            # mode that is only known after the dissolve, which is why this
            # closure is called inside each branch rather than up front.
            if target_faces is not None:
                current = len(obj.data.polygons)
                return min(1.0, target_faces / current) if current > 0 else 1.0
            return self._resolve_ratio(obj)

        if self.simplify_method == 'PLANAR':
            # Planar pre-pass: merge near-coplanar faces first, then decimate.
            # delimit matters a lot here. The default is {'NORMAL'}, which
            # happily dissolves ACROSS material boundaries and sharp edges,
            # merging a rock face into adjacent soil and n-gon-ing away a
            # hard edge. Bannerlord splits multi-material meshes into submeshes,
            # so a sloppy cross-material n-gon becomes a visible seam in-game.
            bpy.ops.object.mode_set(mode='EDIT')
            bpy.ops.mesh.select_all(action='SELECT')
            bpy.ops.mesh.dissolve_limited(
                angle_limit=0.0872666,
                use_dissolve_boundaries=False,
                delimit={'NORMAL', 'MATERIAL', 'SEAM', 'SHARP'},
            )
            bpy.ops.object.mode_set(mode='OBJECT')

            # Resolve the ratio only now, after the dissolve, so Target Faces
            # refers to the mesh the decimator actually sees.
            ratio = resolve_ratio()

            # Multi-pass decimate for better silhouette preservation
            ratio_per_pass = ratio ** (1.0 / self.decimate_passes)
            for i in range(self.decimate_passes):
                decimate_mod = obj.modifiers.new(name=f"DecimatePass{i}", type='DECIMATE')
                decimate_mod.decimate_type = 'COLLAPSE'
                decimate_mod.ratio = ratio_per_pass
                bpy.ops.object.modifier_apply(modifier=decimate_mod.name)

        elif self.simplify_method == 'CURVATURE':
            # Protect high-curvature vertices during decimation
            ratio = resolve_ratio()
            self._apply_curvature_group(
                obj, "Curvature", invert=False, strength=self.detail_weight
            )

            # Multi-pass decimate with vertex group protection
            ratio_per_pass = ratio ** (1.0 / self.decimate_passes)
            for i in range(self.decimate_passes):
                decimate_mod = obj.modifiers.new(name=f"DecimatePass{i}", type='DECIMATE')
                decimate_mod.decimate_type = 'COLLAPSE'
                decimate_mod.ratio = ratio_per_pass
                decimate_mod.vertex_group = "Curvature"
                decimate_mod.vertex_group_factor = 1.0
                decimate_mod.invert_vertex_group = False
                bpy.ops.object.modifier_apply(modifier=decimate_mod.name)

            self._remove_group(obj, "Curvature")

        else:  # STANDARD
            # Standard ratio-based decimation
            decimate_mod = obj.modifiers.new(name="Decimate", type='DECIMATE')
            decimate_mod.decimate_type = 'COLLAPSE'
            decimate_mod.ratio = resolve_ratio()
            bpy.ops.object.modifier_apply(modifier=decimate_mod.name)

        # Converge on the requested count. Ratio mode is left alone: the user
        # asked for a ratio, and over-shooting it is expected behaviour of
        # Blender's decimator rather than a bug to hide.
        if target_faces is not None:
            self._trim_to_target(obj, target_faces)
        elif self.decimate_mode == 'TARGET' and self.target_faces > 0:
            self._trim_to_target(obj, self.target_faces)

    def _trim_to_target(self, obj, target, tolerance=1.15, max_passes=10):
        """Iteratively decimate until the face count is near the target.

        Blender's COLLAPSE decimator treats `ratio` as a soft goal: it stops
        collapsing once no more valid edge collapses remain, so a single pass
        commonly lands 2-3x above the requested ratio. Repeating with a
        recomputed ratio converges on the real target.
        """
        last = len(obj.data.polygons)
        if target <= 0 or last <= target * tolerance:
            return

        for _ in range(max_passes):
            mod = obj.modifiers.new(name="TargetTrim", type='DECIMATE')
            mod.decimate_type = 'COLLAPSE'
            mod.ratio = min(1.0, target / last)
            bpy.ops.object.modifier_apply(modifier=mod.name)

            now = len(obj.data.polygons)
            if now <= target * tolerance:
                return
            if now >= last * 0.98:
                # Less than 2% progress; further passes will not help.
                return
            last = now

    def _apply_curvature_group(self, obj, group_name, invert=False, strength=1.0):
        """Create a vertex group weighted by discrete curvature (angle defect).

        Blender's Decimate protects HIGH weights, so:
          invert=False -> high curvature is protected (visual meshes)
          invert=True  -> low curvature is protected, i.e. detail and creases are
                          collapsed first (physics hulls)
        strength=0 flattens every weight, giving uniform collapse.
        """
        bm = bmesh.new()
        bm.from_mesh(obj.data)
        bm.verts.ensure_lookup_table()

        # Angle defect: 2*pi minus the sum of incident face angles. The angle at
        # a vertex corner lives on its EDGE, not its face -- BMFace has no
        # calc_angle(); BMEdge.calc_face_angle() is correct.
        #
        # calc_face_angle() RAISES on an edge that does not have exactly two
        # faces, and culling legitimately creates those: deleting an island (or
        # a buried face) leaves boundary edges with a single face. BMVert.
        # is_manifold is NOT a sufficient guard -- it reports True for a vertex
        # whose fan merely stays contiguous, so a boundary vertex still passes
        # it and then throws (measured: every vert is_manifold on the earthworks
        # exports while 118 of them sit on 1-face edges). Filter per edge
        # instead, via the documented fallback argument, which returns the
        # supplied value on any edge that is not shared by two faces.
        curvature = {}
        for v in bm.verts:
            if v.is_manifold:
                angle_sum = sum(e.calc_face_angle(0.0) for e in v.link_edges)
                curvature[v.index] = abs(2.0 * math.pi - angle_sum)
            else:
                curvature[v.index] = 0.0

        max_curv = max(curvature.values()) if curvature else 0.0
        if max_curv > 0:
            curvature = {k: v / max_curv for k, v in curvature.items()}
        bm.free()

        self._remove_group(obj, group_name)
        vgroup = obj.vertex_groups.new(name=group_name)
        for index, weight in curvature.items():
            if invert:
                weight = 1.0 - weight
            vgroup.add([index], weight * strength, 'REPLACE')
        return vgroup

    def _remove_group(self, obj, group_name):
        """Remove a vertex group by name, tolerating Blender's .001 suffix."""
        for g in list(obj.vertex_groups):
            if g.name == group_name or g.name.startswith(group_name + "."):
                obj.vertex_groups.remove(g)

    def _duplicate_for_physics(self, source_obj, context):
        """Duplicate the render mesh into a bo_ candidate, stripped of groups."""
        bpy.ops.object.select_all(action='DESELECT')
        source_obj.select_set(True)
        context.view_layer.objects.active = source_obj
        bpy.ops.object.duplicate()

        bo_obj = context.active_object
        bo_obj.name = "bo_" + source_obj.name

        # duplicate() copies vertex groups, so a Curvature group used by the
        # main mesh's decimation could ride along. A physics hull must never be
        # curvature-protected -- strip any groups before decimating.
        for group in list(bo_obj.vertex_groups):
            bo_obj.vertex_groups.remove(group)
        return bo_obj

    def _generate_physics_mesh(self, source_obj, context):
        """Generate bo_ physics mesh from source"""
        bo_obj = self._duplicate_for_physics(source_obj, context)
        self._decimate_physics(bo_obj)
        return bo_obj

    def _generate_physics_mesh_cull(self, merged_obj, context):
        """Cull-mode bo_ physics mesh: a decimated copy of the render result.

        Unlike Voxel mode there is no voxel pass here. The cull result IS the
        finished asset, so bo_ tracks its actual silhouette instead of a
        separate shell rebuilt from the pre-cull join -- one merge pass instead
        of two, and physics can never describe a shape the render mesh does not
        have.

        Consequence, chosen deliberately: the source is the SIMPLIFIED render
        mesh, so bo_ cannot carry silhouette detail the main decimation already
        removed. That is fine for a collision proxy, but it also makes bo_ an
        open surface. If physics ever needs shape the render mesh dropped, take
        it from the pre-simplification culled mesh instead of this one.
        """
        bo_obj = self._duplicate_for_physics(merged_obj, context)

        # bo_ prunes islands that the render mesh keeps. Decimation cannot do
        # this: reverse-curvature weighting protects the SMOOTH parts of each
        # piece, so a stick is protected on its own terms and survives even at
        # Filter Strength 1.0.
        #
        # Two complementary passes, both BEFORE decimation so the bo_ face
        # budget is spent on geometry that survives:
        #   1. intersection -- drop genuinely detached objects
        #   2. size         -- drop sticks inside the main assembly, which the
        #                       intersection pass cannot touch because they
        #                       intersect the body
        # The render mesh gets neither: it is a rendering asset, so a small
        # stick resting against the body is legitimate geometry.
        self._drop_floaters(bo_obj)
        self._drop_small_islands(bo_obj, BO_ISLAND_MIN_FRACTION)
        self._decimate_physics(bo_obj)

        # Run the size pass AGAIN, after decimation. The pre-pass only cleans
        # the input; the decimator manufactures new specks, and those are the
        # jutting triangles actually seen on bo_. Measured on earthworks_a:
        # source islands end at 66 faces, but the decimated result ends
        # 72,55,52,51,51,45,44,39,31,29,8,7 -- an 8/7-face tail that does not
        # exist before decimation, so no pre-pass can remove it.
        self._drop_small_islands(bo_obj, BO_ISLAND_MIN_FRACTION)
        return bo_obj

    def _decimate_physics(self, bo_obj):
        """Decimate and strip a physics candidate down to the bo_ target."""
        # Decimate to the bo_ target. A convex hull was tried here and is not
        # used: on kitbash geometry it wraps the concave voids between pieces
        # (+30% enclosed volume, so agents collide with air), came out with
        # non-manifold edges, and produced a LARGER file at the same face count.
        ratio = self.bo_decimate_ratio
        if self.bo_decimate_mode == 'TARGET':
            current_faces = len(bo_obj.data.polygons)
            if current_faces > 0:
                ratio = min(1.0, self.bo_target_faces / current_faces)

        decimate_mod = bo_obj.modifiers.new(name="Decimate", type='DECIMATE')
        decimate_mod.decimate_type = 'COLLAPSE'
        decimate_mod.ratio = ratio

        # Optional reverse-curvature filter: protect LOW curvature so detail
        # and creases are the first things collapsed, leaving a smooth bulky
        # hull that is a better collision proxy at the same face budget.
        if self.bo_filter_detail:
            self._apply_curvature_group(
                bo_obj, "BoFilter", invert=True, strength=self.bo_filter_strength
            )
            decimate_mod.vertex_group = "BoFilter"
            decimate_mod.vertex_group_factor = 1.0
            decimate_mod.invert_vertex_group = False

        bpy.ops.object.modifier_apply(modifier=decimate_mod.name)

        if self.bo_filter_detail:
            self._remove_group(bo_obj, "BoFilter")

        # Converge on the requested physics face count, same as the main mesh
        if self.bo_decimate_mode == 'TARGET' and self.bo_target_faces > 0:
            self._trim_to_target(bo_obj, self.bo_target_faces)

        # Strip UVs and materials - a physics shape is a collision hull, never
        # rendered, and Bannerlord would otherwise split it into pointless
        # per-material submeshes.
        while bo_obj.data.uv_layers:
            bo_obj.data.uv_layers.remove(bo_obj.data.uv_layers[0])
        bo_obj.data.materials.clear()
        for poly in bo_obj.data.polygons:
            poly.material_index = 0

        return bo_obj

    def _generate_lods(self, main_obj, context):
        """Generate <base>.lod1 ... <base>.lod6 from the finished main mesh.

        LOD 0 is the main mesh itself and is never modified. Each LOD N is a
        fresh duplicate of LOD 0 decimated to lod{N}_ratio of LOD 0's face
        count. Ratios are measured against LOD 0, not against the previous
        LOD, so editing one does not shift the others.

        Method, Detail Weight and pass count follow the main decimation via
        _simplify_mesh. UVs and materials are KEPT: a LOD is a render mesh,
        and Bannerlord expects every LOD to share LOD 0's material set. Each
        LOD can be toggled off individually; skipped LODs leave a numbering
        gap (0, 2, 3, 4) rather than renumbering the rest.
        """
        if not self.lod_enabled:
            return []

        base = main_obj.name
        lod0_faces = len(main_obj.data.polygons)
        lods = []
        for i in range(1, 7):
            if not getattr(self, f"lod{i}_enabled"):
                continue
            ratio = getattr(self, f"lod{i}_ratio")
            target = max(1, int(round(lod0_faces * ratio)))
            if target >= lod0_faces:
                continue

            bpy.ops.object.select_all(action='DESELECT')
            main_obj.select_set(True)
            context.view_layer.objects.active = main_obj
            bpy.ops.object.duplicate()

            lod = context.active_object
            # The suffix is set on BOTH names. Bannerlord binds LODs to a mesh
            # by this suffix, so the object and its mesh data must agree.
            lod.name = f"{base}.lod{i}"
            lod.data.name = f"{base}.lod{i}"

            self._simplify_mesh(lod, target_faces=target)
            self._cleanup_mesh(lod)
            lods.append(lod)
            print(
                f"[lod] {lod.name}: {lod0_faces:,} -> "
                f"{len(lod.data.polygons):,} faces (target {target:,})"
            )
        return lods

    def _consolidate_materials(self, obj):
        """Consolidate duplicate materials"""
        if not obj.data.materials:
            return

        # Build a map of unique materials
        material_map = {}  # old_index -> new_index
        unique_materials = []
        new_slots = []

        for i, mat in enumerate(obj.data.materials):
            if mat is None:
                new_slots.append(None)
                continue

            # Check if we already have this material
            found = False
            for j, unique_mat in enumerate(unique_materials):
                if self._materials_equal(mat, unique_mat):
                    material_map[i] = j
                    found = True
                    break

            if not found:
                material_map[i] = len(unique_materials)
                unique_materials.append(mat)
                new_slots.append(mat)

        # Remap material indices
        if len(unique_materials) < len(obj.data.materials):
            # Update polygon material indices
            for poly in obj.data.polygons:
                old_idx = poly.material_index
                if old_idx in material_map:
                    poly.material_index = material_map[old_idx]

            # Update material slots
            obj.data.materials.clear()
            for mat in new_slots:
                obj.data.materials.append(mat)

    def _materials_equal(self, mat1, mat2):
        """Check if two materials are functionally equal"""
        if mat1.name != mat2.name:
            return False
        if mat1.diffuse_color != mat2.diffuse_color:
            return False
        # Add more comparisons as needed (metallic, roughness, etc.)
        return True

    def _export_obj(self, merged_obj, bo_obj, context, lod_objs=None):
        """Export processed meshes as FBX (Bannerlord format)"""
        export_dir = bpy.path.abspath(self.export_path)
        if not os.path.exists(export_dir):
            os.makedirs(export_dir, exist_ok=True)

        base_name = merged_obj.name

        # Export the render meshes as ONE FBX. The LODs travel in the same
        # file as LOD 0: Bannerlord matches LODs to a mesh by the .lodN suffix
        # on the mesh name, so splitting them across files would orphan them.
        merged_path = os.path.join(export_dir, f"{base_name}.fbx")
        bpy.ops.object.select_all(action='DESELECT')
        merged_obj.select_set(True)
        for lod in (lod_objs or []):
            lod.select_set(True)
        context.view_layer.objects.active = merged_obj
        bpy.ops.export_scene.fbx(
            filepath=merged_path,
            use_selection=True,
            apply_unit_scale=True,
            global_scale=1.0,
            apply_scale_options='FBX_SCALE_NONE',
            use_mesh_modifiers=True,
            mesh_smooth_type='FACE',
            path_mode='COPY',
            embed_textures=False,
        )

        # Export physics mesh as FBX
        bo_path = os.path.join(export_dir, f"bo_{base_name}.fbx")
        bpy.ops.object.select_all(action='DESELECT')
        bo_obj.select_set(True)
        context.view_layer.objects.active = bo_obj
        bpy.ops.export_scene.fbx(
            filepath=bo_path,
            use_selection=True,
            apply_unit_scale=True,
            global_scale=1.0,
            apply_scale_options='FBX_SCALE_NONE',
            use_mesh_modifiers=True,
            mesh_smooth_type='FACE',
            path_mode='COPY',
            embed_textures=False,
        )

        # Surface failures instead of letting a silent no-op look like success
        for path in (merged_path, bo_path):
            if not os.path.exists(path):
                self.report({'ERROR'}, f"Export failed, file not written: {path}")
            else:
                self.report({'INFO'}, f"Wrote {path}")


class BANNERLORD_OT_quick_export_obj(Operator):
    """Quick export selected objects as FBX"""
    bl_idname = "bannerlord.quick_export_obj"
    bl_label = "Quick Export FBX"
    bl_options = {'REGISTER', 'UNDO'}

    export_path: bpy.props.StringProperty(
        name="Export Path",
        description="Output directory for FBX export",
        default="",
        subtype='DIR_PATH',
    )

    def execute(self, context):
        if not self.export_path:
            self.report({'ERROR'}, "No export path specified")
            return {'CANCELLED'}

        if not os.path.exists(self.export_path):
            os.makedirs(self.export_path)

        bpy.ops.export_scene.fbx(
            filepath=os.path.join(self.export_path, "export.fbx"),
            use_selection=True,
            apply_unit_scale=True,
            global_scale=1.0,
            apply_scale_options='FBX_SCALE_NONE',
            use_mesh_modifiers=True,
            mesh_smooth_type='FACE',
            path_mode='COPY',
            embed_textures=False,
        )

        self.report({'INFO'}, f"Exported to {self.export_path}")
        return {'FINISHED'}


def register():
    bpy.utils.register_class(BANNERLORD_OT_process_prefab)
    bpy.utils.register_class(BANNERLORD_OT_quick_export_obj)


def unregister():
    bpy.utils.unregister_class(BANNERLORD_OT_quick_export_obj)
    bpy.utils.unregister_class(BANNERLORD_OT_process_prefab)
