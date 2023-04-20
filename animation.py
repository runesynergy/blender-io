
import bpy

from bpy.types import Operator
from bpy.props import *
from bpy_extras.io_utils import ExportHelper

def get_armature_actions(armature):
    actions = set()

    if armature and armature.type == 'ARMATURE' and armature.animation_data:
        if armature.animation_data.action:
            actions.add(armature.animation_data.action)

        if armature.animation_data.nla_tracks:
            for track in armature.animation_data.nla_tracks:
                for strip in track.strips:
                    if strip.action:
                        actions.add(strip.action)

    return actions

def get_actions(self, context):
    actions = []
    armature = context.active_object

    if armature and armature.type == 'ARMATURE':
        armature_actions = get_armature_actions(armature)
        for action in armature_actions:
            actions.append((action.name, action.name, "", 'ACTION', 0))
    else:
        actions.append(('None', "No Armature", ""))

    return actions

class RS_OT_ExportAnim(Operator, ExportHelper):
    bl_idname = "rs.export_anim"
    bl_label = "Rune Synergy (.anim)"
    filename_ext = ".anim"
    filter_glob: StringProperty(
        default="*.anim",
        options={'HIDDEN'},
        maxlen=255,
    )
    
    action_list: EnumProperty(name="Action", items=get_actions)

    def execute(self, context):
        obj = context.active_object
        print("Active:", obj)
        return {'FINISHED'}

__classes__ = (
    RS_OT_ExportAnim,
)

__extensions__ = {
    bpy.types.TOPBAR_MT_file_export: [ lambda self, context: self.layout.operator(RS_OT_ExportAnim.bl_idname) ],
}