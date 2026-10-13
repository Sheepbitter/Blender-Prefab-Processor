import bpy
from bpy.types import Panel

# This module must not import from the package __init__: __init__ imports
# this module while it is still executing, so a back-import would be a
# partially-initialised circular import.
ADDON_ID = __package__

# Scene property names, without the "bl_" prefix.
PREF_FIELDS = (
    "merge_method",
    "island_culling",
    "voxel_size",
    "voxel_adaptivity",
    "simplify_method",
    "detail_weight",
    "decimate_mode",
    "decimate_ratio",
    "target_faces",
    "decimate_passes",
    "bo_decimate_mode",
    "bo_decimate_ratio",
    "bo_target_faces",
    "bo_filter_detail",
    "bo_filter_strength",
    "consolidate_materials",
    "export_after",
    "export_path",
    "quick_export_path",
)


class BANNERLORD_PT_prefab_processor(Panel):
    """Bannerlord Prefab Processor Panel"""
    bl_label = "Bannerlord Prefab Processor"
    bl_idname = "BANNERLORD_PT_prefab_processor"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Bannerlord"

    def draw(self, context):
        layout = self.layout
        scene = context.scene

        # Info box
        box = layout.box()
        box.label(text="1. Import Bannerlord OBJ export")
        box.label(text="2. Select all mesh objects")
        box.label(text="3. Click Process Prefab")

        # Live face count of the current selection
        meshes = [o for o in context.selected_objects if o.type == 'MESH']
        if meshes:
            faces = sum(len(o.data.polygons) for o in meshes)
            objs = len(meshes)
            row = box.row()
            row.label(text="Selection:")
            row.label(text=f"{faces:,} faces  ({objs} object{'s' if objs != 1 else ''})")
        else:
            box.label(text="No mesh objects selected", icon='INFO')

        layout.separator()

        # Settings
        col = layout.column(align=True)
        col.label(text="Settings:")

        col.prop(scene, "bl_merge_method")
        if scene.bl_merge_method == 'VOXEL':
            col.prop(scene, "bl_voxel_size")
            col.prop(scene, "bl_voxel_adaptivity")
            col.prop(scene, "bl_island_culling")
        else:
            col.label(text="Cull: shell auto-sized to bbox/1000", icon='INFO')
            col.label(text="Cull keeps every island (no floater pass)", icon='INFO')

        layout.separator()
        col.label(text="Simplification:")
        col.prop(scene, "bl_simplify_method")
        if scene.bl_simplify_method == 'CURVATURE':
            col.prop(scene, "bl_detail_weight")
        col.prop(scene, "bl_decimate_mode")
        if scene.bl_decimate_mode == 'RATIO':
            col.prop(scene, "bl_decimate_ratio")
        else:
            col.prop(scene, "bl_target_faces")
        col.prop(scene, "bl_decimate_passes")
        col.prop(scene, "bl_consolidate_materials")

        layout.separator()
        col.label(text="Physics Mesh (bo_):")
        col.prop(scene, "bl_bo_decimate_mode")
        if scene.bl_bo_decimate_mode == 'RATIO':
            col.prop(scene, "bl_bo_decimate_ratio")
        else:
            col.prop(scene, "bl_bo_target_faces")
        col.prop(scene, "bl_bo_filter_detail")
        if scene.bl_bo_filter_detail:
            col.prop(scene, "bl_bo_filter_strength")
        box2 = layout.box()
        box2.label(text="bo_ has no materials or UVs", icon='INFO')

        layout.separator()

        # Export settings
        col = layout.column(align=True)
        col.label(text="Export:")
        col.prop(scene, "bl_export_after")
        if scene.bl_export_after:
            col.prop(scene, "bl_export_path")

        layout.separator()

        # Process button
        row = layout.row(align=True)
        row.scale_y = 2.0
        row.operator("bannerlord.process_prefab", text="Process Prefab", icon='MODIFIER')

        layout.separator()

        # Quick export
        col = layout.column(align=True)
        col.label(text="Quick Export:")
        col.prop(scene, "bl_quick_export_path")
        col.operator("bannerlord.quick_export_obj", text="Export Selected as FBX", icon='EXPORT')


def register():
    bpy.types.Scene.bl_merge_method = bpy.props.EnumProperty(
        name="Merge Method",
        items=[
            ('CULL', "Cull Interior", ""),
            ('VOXEL', "Voxel Remesh", ""),
        ],
        default='CULL',
    )
    bpy.types.Scene.bl_island_culling = bpy.props.BoolProperty(
        name="Cull Floaters",
        description="Voxel Remesh mode only: delete islands that are physically detached from the main assembly. Cull Interior always keeps every island",
        default=True,
    )
    bpy.types.Scene.bl_decimate_ratio = bpy.props.FloatProperty(
        name="Decimate Ratio",
        default=0.1,
        min=0.01,
        max=1.0,
    )
    bpy.types.Scene.bl_voxel_size = bpy.props.FloatProperty(
        name="Voxel Size",
        default=0.01,
        min=0.001,
        max=1.0,
    )
    bpy.types.Scene.bl_simplify_method = bpy.props.EnumProperty(
        name="Simplify Method",
        items=[
            ('PLANAR', "Planar Pre-Pass", ""),
            ('CURVATURE', "Curvature-Weighted", ""),
            ('STANDARD', "Standard Decimate", ""),
        ],
        default='CURVATURE',
    )
    bpy.types.Scene.bl_decimate_passes = bpy.props.IntProperty(
        name="Decimate Passes",
        default=10,
        min=1,
        max=100,
    )
    bpy.types.Scene.bl_voxel_adaptivity = bpy.props.FloatProperty(
        name="Voxel Adaptivity",
        description="Removes voxels in flat regions to cut face count. Disables Fix Poles",
        default=0.0,
        min=0.0,
        max=1.0,
        step=0.01,
    )
    bpy.types.Scene.bl_decimate_mode = bpy.props.EnumProperty(
        name="Decimate Mode",
        items=[
            ('RATIO', "Ratio", ""),
            ('TARGET', "Target Faces", ""),
        ],
        default='RATIO',
    )
    bpy.types.Scene.bl_target_faces = bpy.props.IntProperty(
        name="Target Face Count",
        description="Target face count",
        default=0,
        min=1,
        max=1000000,
    )
    bpy.types.Scene.bl_detail_weight = bpy.props.FloatProperty(
        name="Detail Weight",
        description="How strongly to protect fine details during decimation",
        default=0.7,
        min=0.0,
        max=1.0,
        step=0.05,
    )
    bpy.types.Scene.bl_bo_decimate_mode = bpy.props.EnumProperty(
        name="bo_ Decimate Mode",
        items=[
            ('RATIO', "Ratio", ""),
            ('TARGET', "Target Faces", ""),
        ],
        default='RATIO',
    )
    bpy.types.Scene.bl_bo_decimate_ratio = bpy.props.FloatProperty(
        name="bo_ Decimate Ratio",
        description="Ratio of main mesh faces to keep for the physics mesh",
        default=0.05,
        min=0.001,
        max=1.0,
        step=0.005,
    )
    bpy.types.Scene.bl_bo_target_faces = bpy.props.IntProperty(
        name="bo_ Target Face Count",
        description="Target face count for the physics mesh",
        default=500,
        min=1,
        max=1000000,
    )
    bpy.types.Scene.bl_bo_filter_detail = bpy.props.BoolProperty(
        name="Filter Detail",
        description="Reverse-curvature decimation: collapse detail first",
        default=True,
    )
    bpy.types.Scene.bl_bo_filter_strength = bpy.props.FloatProperty(
        name="bo_ Filter Strength",
        default=0.7,
        min=0.0,
        max=1.0,
        step=0.05,
    )
    bpy.types.Scene.bl_consolidate_materials = bpy.props.BoolProperty(
        name="Consolidate Materials",
        default=True,
    )
    bpy.types.Scene.bl_export_after = bpy.props.BoolProperty(
        name="Export After Processing",
        default=True,
    )
    bpy.types.Scene.bl_export_path = bpy.props.StringProperty(
        name="Export Path",
        default="",
        subtype='DIR_PATH',
    )
    bpy.types.Scene.bl_quick_export_path = bpy.props.StringProperty(
        name="Quick Export Path",
        default="",
        subtype='DIR_PATH',
    )

    bpy.utils.register_class(BANNERLORD_PT_prefab_processor)

    # Restore the last-used settings. bpy.context.scene is not available
    # during register(), so defer to the next main-loop tick.
    bpy.app.timers.register(load_preferences, first_interval=0.1)


def load_preferences():
    """Copy saved preferences onto the scene properties."""
    if not bpy.context.scene:
        return None
    addon = bpy.context.preferences.addons.get(ADDON_ID)
    if not addon:
        return None

    prefs = addon.preferences
    scene = bpy.context.scene
    for name in PREF_FIELDS:
        prop = "bl_" + name
        if hasattr(scene, prop) and hasattr(prefs, name):
            try:
                setattr(scene, prop, getattr(prefs, name))
            except (TypeError, ValueError):
                pass  # clamped value differs between scene and prefs ranges
    return None  # run once


def save_preferences(context=None):
    """Copy scene properties back into the saved preferences."""
    ctx = context or bpy.context
    addon = ctx.preferences.addons.get(ADDON_ID)
    if not addon:
        return

    prefs = addon.preferences
    scene = bpy.context.scene
    for name in PREF_FIELDS:
        prop = "bl_" + name
        if hasattr(scene, prop) and hasattr(prefs, name):
            try:
                setattr(prefs, name, getattr(scene, prop))
            except (TypeError, ValueError):
                pass
    # Blender writes AddonPreferences to userpref.blend automatically, so no
    # explicit flush is needed (and Addon.preferences is read-only anyway).


def unregister():
    bpy.utils.unregister_class(BANNERLORD_PT_prefab_processor)

    del bpy.types.Scene.bl_merge_method
    del bpy.types.Scene.bl_island_culling
    del bpy.types.Scene.bl_decimate_ratio
    del bpy.types.Scene.bl_voxel_size
    del bpy.types.Scene.bl_voxel_adaptivity
    del bpy.types.Scene.bl_simplify_method
    del bpy.types.Scene.bl_decimate_passes
    del bpy.types.Scene.bl_target_faces
    del bpy.types.Scene.bl_decimate_mode
    del bpy.types.Scene.bl_detail_weight
    del bpy.types.Scene.bl_bo_decimate_mode
    del bpy.types.Scene.bl_bo_decimate_ratio
    del bpy.types.Scene.bl_bo_target_faces
    del bpy.types.Scene.bl_bo_filter_detail
    del bpy.types.Scene.bl_bo_filter_strength
    del bpy.types.Scene.bl_consolidate_materials
    del bpy.types.Scene.bl_export_after
    del bpy.types.Scene.bl_export_path
    del bpy.types.Scene.bl_quick_export_path
