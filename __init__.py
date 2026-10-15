bl_info = {
    "name": "Bannerlord Prefab Processor",
    "description": "Process Bannerlord prefab exports: merge intersecting meshes, generate bo_ physics meshes, consolidate materials",
    "author": "OpenCode",
    "version": (1, 1, 0),
    "blender": (4, 5, 0),
    "location": "View3D > Sidebar > Bannerlord",
    "category": "Object",
}

import bpy
from bpy.props import (
    FloatProperty,
    IntProperty,
    BoolProperty,
    EnumProperty,
    StringProperty,
)

from . import operators
from . import ui

ADDON_ID = __name__


class BANNERLORD_AddonPreferences(bpy.types.AddonPreferences):
    """Persists the last-used settings across Blender sessions.

    Blender writes AddonPreferences back to userpref.blend automatically, so
    values assigned here survive a restart with no extra save code.
    """

    bl_idname = ADDON_ID

    voxel_size: FloatProperty(
        name="Voxel Size",
        default=0.01,
        min=0.001,
        max=1.0,
    )
    voxel_adaptivity: FloatProperty(
        name="Voxel Adaptivity",
        default=0.0,
        min=0.0,
        max=1.0,
    )
    merge_method: EnumProperty(
        name="Merge Method",
        items=[
            ('CULL', "Cull Interior", ""),
            ('VOXEL', "Voxel Remesh", ""),
        ],
        default='CULL',
    )
    island_culling: BoolProperty(
        name="Cull Floaters",
        default=True,
    )
    simplify_method: EnumProperty(
        name="Simplify Method",
        items=[
            ('PLANAR', "Planar Pre-Pass", ""),
            ('CURVATURE', "Curvature-Weighted", ""),
            ('STANDARD', "Standard Decimate", ""),
        ],
        default='CURVATURE',
    )
    detail_weight: FloatProperty(
        name="Detail Weight",
        default=0.7,
        min=0.0,
        max=1.0,
    )
    decimate_mode: EnumProperty(
        name="Decimate Mode",
        items=[
            ('RATIO', "Ratio", ""),
            ('TARGET', "Target Faces", ""),
        ],
        default='RATIO',
    )
    decimate_ratio: FloatProperty(
        name="Decimate Ratio",
        default=0.5,
        min=0.01,
        max=1.0,
    )
    target_faces: IntProperty(
        name="Target Face Count",
        default=10000,
        min=1,
    )
    decimate_passes: IntProperty(
        name="Decimate Passes",
        default=10,
        min=1,
        max=10,
    )
    lod_enabled: BoolProperty(
        name="Auto Generate LODs",
        default=True,
    )
    lod1_ratio: FloatProperty(
        name="LOD1 Ratio",
        default=0.9,
        min=0.0,
        max=1.0,
    )
    lod2_ratio: FloatProperty(
        name="LOD2 Ratio",
        default=0.8,
        min=0.0,
        max=1.0,
    )
    lod3_ratio: FloatProperty(
        name="LOD3 Ratio",
        default=0.6,
        min=0.0,
        max=1.0,
    )
    lod4_ratio: FloatProperty(
        name="LOD4 Ratio",
        default=0.4,
        min=0.0,
        max=1.0,
    )
    lod5_ratio: FloatProperty(
        name="LOD5 Ratio",
        default=0.2,
        min=0.0,
        max=1.0,
    )
    lod6_ratio: FloatProperty(
        name="LOD6 Ratio",
        default=0.05,
        min=0.0,
        max=1.0,
    )
    bo_decimate_mode: EnumProperty(
        name="bo_ Decimate Mode",
        items=[
            ('RATIO', "Ratio", ""),
            ('TARGET', "Target Faces", ""),
        ],
        default='RATIO',
    )
    bo_decimate_ratio: FloatProperty(
        name="bo_ Decimate Ratio",
        default=0.05,
        min=0.001,
        max=1.0,
    )
    bo_target_faces: IntProperty(
        name="bo_ Target Face Count",
        default=500,
        min=1,
    )
    bo_filter_detail: BoolProperty(
        name="Filter Detail",
        default=True,
    )
    bo_filter_strength: FloatProperty(
        name="bo_ Filter Strength",
        default=0.7,
        min=0.0,
        max=1.0,
    )
    consolidate_materials: BoolProperty(
        name="Consolidate Materials",
        default=True,
    )
    export_after: BoolProperty(
        name="Export After Processing",
        default=True,
    )
    export_path: StringProperty(
        name="Export Path",
        subtype='DIR_PATH',
        default="",
    )
    quick_export_path: StringProperty(
        name="Quick Export Path",
        subtype='DIR_PATH',
        default="",
    )

    def draw(self, context):
        layout = self.layout
        layout.label(text="Settings save automatically when you run the processor.")
        layout.prop(self, "export_path")


def _get_prefs(context):
    addon = context.preferences.addons.get(ADDON_ID)
    return addon.preferences if addon else None


def register():
    operators.register()
    ui.register()
    bpy.utils.register_class(BANNERLORD_AddonPreferences)


def unregister():
    bpy.utils.unregister_class(BANNERLORD_AddonPreferences)
    ui.unregister()
    operators.unregister()