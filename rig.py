
import os
import bpy
import json
import math

from . import model, util

from collections import deque
from mathutils import Vector
from bpy.types import Operator, Panel, UIList, PropertyGroup
from bpy.props import StringProperty, BoolProperty, FloatProperty, EnumProperty
from bpy_extras.io_utils import ImportHelper, ExportHelper

def get_objects(self, context):
    objects = []

    for object in context.scene.objects:
        if object.type == 'MESH':
            objects.append((object.name, object.name, ""))
            
    if len(objects) == 0:
        objects.append(('None', "No objects", "", 'ERROR', 0))

    return objects

class RS_OT_ImportRig(Operator, ImportHelper):
    """Imports a Rune Synergy rig"""
    bl_idname = "rs.import_rig"
    bl_label = "Rune Synergy (.rig)"
    filename_ext = ".rig"
    
    filter_glob: StringProperty(
        default="*.rig",
        options={'HIDDEN'},
        maxlen=255,
    )

    attach_object: EnumProperty(name="Attach to", items=get_objects)
    
    clear_vertex_groups: BoolProperty(
        name="Clear Vertex Groups",
        description="Clears all vertex groups of the specified target object before import",
        default=True,
    )
    
    def execute(self, context):
        return Import(context, self.filepath,
            obj_name = self.attach_object,
            clear_vertex_groups = self.clear_vertex_groups,
        )

def Import(context, filepath, obj_name=None, clear_vertex_groups=False):
    with open(filepath, "r") as file:
        data = json.load(file)

    if not data:
        print("no data")
        return {'CANCELLED'}

    if "bones" not in data:
        print("no bone data")
        return {'CANCELLED'}

    data_bones = data["bones"]
    
    if obj_name:
        for other in context.scene.objects:
            if other.name == obj_name:
                obj = other
                break
    else:
        obj = context.active_object
    
    if not obj:
        print("no object found")
        return {'CANCELLED'}

    label_vertices = model.get_label_vertices(obj.data)
 
    obj.select_set(state=True)
    bpy.ops.object.mode_set(mode='OBJECT')
    bpy.ops.object.armature_add()

    armature_obj = context.active_object
    armature_obj.name = obj_name
    armature_obj.show_in_front = True
    armature_obj.parent = obj

    armature = armature_obj.data
    armature["imported"] = True

    bpy.ops.object.mode_set(mode='EDIT')
    model.create_or_update_armature_modifier(obj, armature_obj)
    
    edit_bones = armature.edit_bones

    if clear_vertex_groups:
        for group in obj.vertex_groups:
            obj.vertex_groups.remove(group)

    # create bones, vertex groups, and set bone head.
    for data_bone in data_bones:
        has_origin_labels = False

        for label in data_bone["origins"]:
            if label in label_vertices:
                has_origin_labels = True
                break

        bone_name = data_bone["name"]
        
        if not has_origin_labels:
            data_bone["skipped"] = True
            print("Bone", bone_name, "skipped due to missing origin labels")
            continue

        # create bone and link to data temporarily for future ref
        edit_bone = edit_bones.new(bone_name)
        data_bone["edit_bone"] = edit_bone

        # store origin and transform labels in new bone
        edit_bone["origin_labels"] = data_bone["origins"]
        edit_bone["transform_labels"] = data_bone["rotates"]

        vertex_group = obj.vertex_groups.get(bone_name)

        if vertex_group is None:
            vertex_group = obj.vertex_groups.new(name=bone_name)

        for label in data_bone["rotates"]:
            if label not in label_vertices:
                continue
            for vertex in label_vertices[label]:
                vertex_group.add([vertex.index], 1.0, 'REPLACE')

        edit_bone.head = model.get_label_median(label_vertices, data_bone["origins"])
        edit_bone.tail = edit_bone.head + Vector((0,10,0))

    # assign parents
    for data_bone in data_bones:
        if "skipped" in data_bone:
            continue
        if data_bone["name"] == "ROOT":
            continue
        edit_bone = data_bone["edit_bone"]
        parent_name = data_bone["parent"] or ""
        if parent_name in edit_bones:
            edit_bone.parent = edit_bones[parent_name]

    # reposition bone if needed based on relationships
    for data_bone in data_bones:
        if "skipped" in data_bone:
            continue
        
        bone_name = data_bone["name"]

        if bone_name == "ROOT":
            continue

        edit_bone = data_bone["edit_bone"]
        children = [child for child in armature.edit_bones if child.parent == edit_bone]

        # one child, so we probably are just a part of a chain. connect to them
        if len(children) == 1:
            child = children[0]
            if child.head != edit_bone.head:
                edit_bone.tail = child.head
                child.use_connect = True
        else: # zero children or more than 1
            # skip any bones marked as root...
            if "root" in data_bone and data_bone["root"] == True:
                continue

            label_center = model.get_label_median(label_vertices, data_bone["rotates"])

            # no children, so just place the bone head 25% further than its influenced
            # labels center
            if len(children) == 0:
                edit_bone.tail = edit_bone.head + 1.25 * (label_center - edit_bone.head)
            else: # more than 1 child
                children_center = sum((bone.head for bone in children), Vector((0,0,0))) / len(children)

                # The direction this bone would need to go to get to the center of its labels                    
                center_dir = (label_center - edit_bone.head).normalized()
                
                # the distance from the label center to the center of this bones children
                label_to_children_dist = (label_center - children_center).length

                # set the tail to the midpoint of our label center and children center
                edit_bone.tail = label_center + (center_dir * label_to_children_dist) * 0.5

        # Oops, the bone became super tiny trying to connect to a label that overlapped it.
        if (edit_bone.head - edit_bone.tail).length < 2:
            if edit_bone.parent:
                fwd = (edit_bone.head - edit_bone.parent.head).normalized()
                edit_bone.tail = edit_bone.head + (fwd * 10)
            else:
                edit_bone.tail = edit_bone.head + Vector((0, 0, +20))
                print(edit_bone, "ended up in an awkward position")

    bpy.ops.object.mode_set(mode='OBJECT')
    return {'FINISHED'}    

class RS_OT_ExportRig(Operator, ExportHelper):
    """Exports the active armatures rig"""

    bl_idname = "rs.export_rig"
    bl_label = "Rune Synergy (.rig)"
    filename_ext = ".rig"

    filter_glob: StringProperty(
        default="*.rig",
        options={'HIDDEN'},
        maxlen=255,
    )

    def execute(self, context):
        return Export(context, self.filepath)

def Export(context, filepath):
    obj = context.active_object

    if obj is None:
        return {'CANCELLED'}

    if obj.type != 'ARMATURE':
        obj = obj.find_armature()

    if obj.type != 'ARMATURE':
        print("no armature found")
        return {'CANCELLED'}

    armature = obj.data
    
    data = {
        "vertex_groups":[],
        "face_groups":[],
    }

    bones = bones_sorted_by_depth(obj)

    assigned_ids = {}
    
    for bone in bones:
        if "id" not in bone:
            for id in range(0, 255):
                if id not in assigned_ids:
                    bone["id"] = id
                    break

        id = bone["id"]
        assigned_ids[id] = True
        
        if "origin_labels" not in bone:
            bone["origin_labels"] = [255-id]
        if "transform_labels" not in bone:
            bone["transform_labels"] = [id]

        group = {
            "name": "{}".format(bone.name),
            "origin_labels": util.export_array(bone["origin_labels"]),
            "labels": util.export_array(bone["transform_labels"]),
            "children": [child.name for child in bones if child.parent == bone],
        }

        if bone.inherit_scale == 'FULL':
            group["inherit_scale"] = True

        data["vertex_groups"].append(group)
    
    print(data)
    with open(filepath, "w") as file:
        json.dump(data, file)

    return {'FINISHED'} 

def bones_sorted_by_depth(armature_obj):
    if not armature_obj or armature_obj.type != 'ARMATURE':
        return []

    # Get the root bones
    root_bones = [bone for bone in armature_obj.data.bones if not bone.parent]

    # Perform BFS to sort bones by depth
    sorted_bones = []
    queue = deque(root_bones)
    while queue:
        bone = queue.popleft()
        sorted_bones.append(bone)
        queue.extend(bone.children)

    return sorted_bones


__classes__ = (
    RS_OT_ExportRig,
    RS_OT_ImportRig,
)

__extensions__ = {
    bpy.types.TOPBAR_MT_file_export: [lambda self, context: self.layout.operator(RS_OT_ExportRig.bl_idname)],
    bpy.types.TOPBAR_MT_file_import: [lambda self, context: self.layout.operator(RS_OT_ImportRig.bl_idname)],
}
