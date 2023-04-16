import os
import bpy
import bmesh
import json
import math

from mathutils import Vector
from bpy.types import Operator, Panel, UIList
from bpy.props import *
from bpy_extras.io_utils import ImportHelper, ExportHelper

from . import util

def Import(context, filepath):
    data = None

    with open(filepath, "r") as file:
        data = json.load(file)

    if data is None:
        print("No model data to import")
        return {'CANCELLED'}

    name = util.filename_without_extension(filepath)

    mesh = bpy.data.meshes.new(name)
    obj = bpy.data.objects.new(name, mesh)

    context.collection.objects.link(obj)
    context.view_layer.objects.active = obj

    bm = bmesh.new()

    label_layer = bm.verts.layers.int.new("label")
    
    for vertex in data["vertices"]:
        x = vertex[0]
        y = vertex[2]
        z = -vertex[1]
        bm.verts.new((x,y,z))
    bm.verts.ensure_lookup_table()

    for vertex_index, label in enumerate(data["vertex_label"]):
        bm.verts[vertex_index][label_layer] = label

    for face in data["faces"]:
        bm.faces.new([bm.verts[i] for i in face])
    bm.faces.ensure_lookup_table()
    bm.faces.index_update()

    uv_layer = bm.loops.layers.uv.new("color")

    for face in bm.faces:
        face_type = data["face_type"][face.index]
        # TODO: custom face type importers? face_impoter[face_type]
        if face_type == 0:
            face.smooth = True
        elif face_type == 1:
            face.smooth = False
        color = data["face_color"][face.index]
        u = ((color % 128.0) + 0.5) / 128.0
        v = (512.0 - ((color / 128.0) + 0.5)) / 512.0
        for loop in face.loops:
            loop[uv_layer].uv = (u, v)

    transparents = {}

    for face_index, transparency in enumerate(data["face_alpha"]):
        if transparency not in transparents:
            transparents[transparency] = []
        transparents[transparency].append(face_index)

    for transparency, face_indices in transparents.items():
        palette = get_palette(transparency)
        obj.data.materials.append(palette)
        material_index = obj.material_slots.find(palette.name)

        for face_index in face_indices:
            bm.faces[face_index].material_index = material_index
            

    bm.to_mesh(mesh)
    bm.free()
    mesh.update()

    return {'FINISHED'}

def Export(filepath, obj, armature_obj):
    bpy.ops.object.mode_set(mode='OBJECT')

    rigged = False
    armature = None
    
    if armature_obj:
        armature = armature_obj.data

        if not armature:
            print("Unable to export model: provided armature object has no armature")
            return {'CANCELLED'}
        
        rigged = True

        for bone_index, bone in enumerate(armature.bones):
            if not "origin" in bone:
                bone["origin"] = 255 - bone_index
            if not "label" in bone:
                bone["label"] = bone_index

    mesh = obj.data

    if not mesh:
        print("Unable to export model: no mesh")
        return {'CANCELLED'}

    model = {
        "vertices": [],
        "vertex_label": [],
        "faces": [],
        "face_type": [],
        "face_color": [],
        "face_alpha": [],
        "face_label": [],
        "face_layer": [],
        "texture_faces": [],
    }

    for vertex in mesh.vertices:
        label = 0

        if rigged:
            bone = None
            for vertex_group in vertex.groups:
                if vertex_group.weight > 0.5:
                    group = obj.vertex_groups[vertex_group.group]
                    bone = armature.bones.get(group.name)
                    break
            if bone:
                label = bone["label"]

        model["vertices"].append(util.export_vector(vertex.co))
        model["vertex_label"].append(label)

    if rigged:
        for bone in armature.bones:
            model["vertices"].append(util.export_vector(bone.head_local))
            model["vertex_label"].append(255 - bone["label"])
            
    uv_layer = mesh.uv_layers.active.data
    
    backfaces = []
    
    for face in mesh.polygons:
        type = 1

        if face.use_smooth:
            type = 0
        
        uv = uv_layer[face.loop_start].uv
        u = int(uv[0] * 128)
        v = 511 - int(uv[1] * 512)
        color = int(u + (v * 128))

        transparency = 0
        material_index = face.material_index
        double_sided = False
        
        if material_index < len(obj.material_slots):
            material = obj.material_slots[material_index].material
            if material:
                transparency = 255 - int(material.base_alpha * 255)
            if material.double_sided:
                double_sided = True

        layer = 0 # TODO: pray for blender to allow multipass viewport compositing
        
        model["faces"].append(face.vertices[:])
        model["face_type"].append(type)
        model["face_color"].append(color)
        model["face_label"].append(material_index)
        model["face_alpha"].append(transparency)
        model["face_layer"].append(layer)

        if double_sided:
            a = face.vertices[0]
            b = face.vertices[1]
            c = face.vertices[2]
            
            backfaces.append({
                "vertices": [c, b, a], # reverse winding
                "type": type,
                "color": color,
                "label": material_index,
                "transparency": transparency,
                "layer": layer,
            })

    for face in backfaces:
        model["faces"].append(face["vertices"])
        model["face_type"].append(face["type"])
        model["face_color"].append(face["color"])
        model["face_label"].append(face["label"])
        model["face_alpha"].append(face["transparency"])
        model["face_layer"].append(face["layer"])
        
    
    with open(filepath, "w") as file:
        json.dump(model, file)
    
    return {'FINISHED'}

def load_image(image_path):
    current_script_path = os.path.dirname(os.path.realpath(__file__))
    image_path = os.path.join(current_script_path, image_path)
    image_name = os.path.basename(image_path)
    image = bpy.data.images.get(image_name)

    if not image:
        image = bpy.data.images.load(image_path)

    return image

def get_palette(transparency):
    opaque_material = bpy.data.materials.get("OPAQUE")

    if not opaque_material:
        opaque_material = bpy.data.materials.new("OPAQUE")
        opaque_material.use_nodes = True
        opaque_material.use_backface_culling = True
        shader_node_tree = opaque_material.node_tree
        nodes = shader_node_tree.nodes
        nodes.clear()
        diffuse_node = nodes.new(type='ShaderNodeBsdfDiffuse')
        diffuse_node.location = (0, 0)
        diffuse_node.inputs["Roughness"].default_value = 1
        output_node = nodes.new(type='ShaderNodeOutputMaterial')
        output_node.location = (300, 0)
        texture_node = nodes.new(type='ShaderNodeTexImage')
        texture_node.location = (-300, 0)
        texture_node.interpolation = 'Closest'
        texture_node.image = load_image("palette.png")
        links = shader_node_tree.links
        links.new(texture_node.outputs['Color'], diffuse_node.inputs['Color'])
        links.new(diffuse_node.outputs['BSDF'], output_node.inputs['Surface'])
    
    if transparency == 0:
        return opaque_material

    alpha = 255 - transparency

    name = "ALPHA_{}".format(alpha)
    transparent_material = bpy.data.materials.get(name)
    
    if transparent_material:
        return transparent_material
    
    transparent_material = bpy.data.materials.new(name)
    transparent_material.use_nodes = True
    transparent_material.use_backface_culling = True
    transparent_material.blend_method = 'BLEND'
    shader_node_tree = transparent_material.node_tree
    nodes = shader_node_tree.nodes
    nodes.clear()
    
    principled_node = nodes.new(type='ShaderNodeBsdfPrincipled')
    principled_node.location = (0, 0)
    principled_node.inputs["Specular"].default_value = 0
    principled_node.inputs["Roughness"].default_value = 1
    principled_node.inputs["Alpha"].default_value = alpha / 255.0
    
    output_node = nodes.new(type='ShaderNodeOutputMaterial')
    output_node.location = (300, 0)
    texture_node = nodes.new(type='ShaderNodeTexImage')
    texture_node.location = (-300, 0)
    texture_node.interpolation = 'Closest'
    texture_node.image = load_image("palette.png")
    links = shader_node_tree.links
    links.new(texture_node.outputs['Color'], principled_node.inputs['Base Color'])
    links.new(principled_node.outputs['BSDF'], output_node.inputs['Surface'])

    return transparent_material


def apply_palette(obj):
    if not obj:
        return {'CANCELLED'}
    obj.data.materials.append(get_palette(0))
    return {'FINISHED'}

def create_or_update_armature_modifier(target_obj, armature_obj):
    # Ensure that both the target object and armature object exist
    if target_obj is None or armature_obj is None:
        print("Error: Could not find target object and/or armature object")
        return

    # Check for an existing Armature modifier on the target object
    armature_modifier = None
    for modifier in target_obj.modifiers:
        if modifier.type == 'ARMATURE':
            armature_modifier = modifier
            break

    # If no Armature modifier is found, create a new one
    if armature_modifier is None:
        armature_modifier = target_obj.modifiers.new(name="Armature", type="ARMATURE")

    # Assign the armature object to the modifier's "Object" field
    armature_modifier.object = armature_obj

class RS_OT_ImportModel(Operator, ImportHelper):
    """Nothing"""
    bl_idname = "rs.import_model"
    bl_label = "Rune Synergy (.mdl)"
    filename_ext = ".mdl"
    filter_glob: StringProperty(
        default="*.mdl",
        options={'HIDDEN'},
        maxlen=255,
    )

    def execute(self, context):
        return Import(context, self.filepath)

class RS_OT_ExportModel(Operator, ExportHelper):
    """Nothing"""
    bl_idname = "rs.export_model"
    bl_label = "Rune Synergy (.mdl)"
    filename_ext = ".mdl"
    filter_glob: StringProperty(
        default="*.mdl",
        options={'HIDDEN'},
        maxlen=255,
    )

    def execute(self, context):
        obj = context.active_object
        armature_obj = obj.find_armature()
        return Export(self.filepath, obj, armature_obj)

class RS_UL_FaceGroups(UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        if item.material:
            row = layout.row(align=True)
            row.prop(item.material, "name", text="", icon="FACE_MAPS", emboss=False)
        else:
            layout.label(text="Invalid Slot")

class RS_OT_FaceGroup_Create(Operator):
    """Create"""

    bl_idname = "facegroup.create"
    bl_label = "Create"

    def execute(self, context):
        print("eep")
        return {'FINISHED'}

class RS_OT_FaceGroup_Delete(Operator):
    """Delete"""
    
    bl_idname = "facegroup.delete"
    bl_label = "Delete"
    
    def execute(self, context):
        print("eep")
        return {'FINISHED'}

class RS_OT_FaceGroup_Assign(Operator):
    """Assigns the selected faces to the active face group"""

    bl_idname = "facegroup.assign"
    bl_label = "Assign"

    def execute(self, context):
        print("eep")
        return {'FINISHED'}

class RS_OT_FaceGroup_Select(Operator):
    """Selects all the faces in the active face group"""
    bl_idname = "facegroup.select"
    bl_label = "Select"
    
    def execute(self, context):
        return {'FINISHED'}
    
class RS_OT_FaceGroup_Deselect(Operator):
    """Deselects all the faces in the active face group"""
    bl_idname = "facegroup.deselect"
    bl_label = "Deselect"
    
    def execute(self, context):
        return {'FINISHED'}

class RS_PT_FaceGroups(Panel):
    bl_label = "Face Groups"
    bl_idname = "RS_PT_FaceGroups"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Rune Synergy"
    bl_label = "Face Groups"

    @classmethod
    def poll(cls, context):
        return context.object and context.object.type == 'MESH'

    def draw(self, context):
        layout = self.layout
        obj = context.object

        row = layout.row()
        col = row.column()

        col.template_list("RS_UL_FaceGroups", "", obj, "material_slots", obj, "active_material_index")
        
        col = row.column(align=True)
        col.operator("facegroup.create", icon='ADD', text="")
        col.operator("facegroup.delete", icon='REMOVE', text="")

        if context.object.mode == 'EDIT':
            row = layout.row(align=True)
            row.operator("facegroup.assign", text="Assign")
            row.operator("facegroup.select", text="Select")
            row.operator("facegroup.deselect", text="Deselect")

        active_index = obj.active_material_index

        if active_index < len(obj.material_slots):
            slot = obj.material_slots[active_index]
            material = slot.material
            if material:
                layout.prop(material, "base_alpha", text="Base Alpha", emboss=True, slider=True)

                alpha_node = get_material_alpha_node(material)

                if alpha_node:
                    layout.label(text="Use the following slider for animating")
                    layout.prop(alpha_node, "default_value", text="Current Alpha", emboss=True, slider=True)
                
                layout.prop(material, "double_sided")

def get_material_alpha_node(material):
    tree = material.node_tree
    if tree:
        node = tree.nodes.get("Principled BSDF")
        if node:
            return node.inputs.get("Alpha")
    return None

def material_base_alpha_update(self, context):
    if self.base_alpha == 1:
        self.blend_method = 'OPAQUE'
    else:
        self.blend_method = 'BLEND'
    self.node_tree.nodes["Principled BSDF"].inputs.get("Alpha").default_value = self.base_alpha
    
def material_double_sided_update(self, context):
    self.use_backface_culling = not self.double_sided
    self.show_transparent_back = self.double_sided
        
__classes__ = (
    RS_OT_ImportModel,
    RS_OT_ExportModel,
    RS_OT_FaceGroup_Create,
    RS_OT_FaceGroup_Delete,
    RS_OT_FaceGroup_Assign,
    RS_OT_FaceGroup_Select,
    RS_OT_FaceGroup_Deselect,
    RS_UL_FaceGroups,
    RS_PT_FaceGroups,
)

__properties__ = {
    bpy.types.Material: {
        "base_alpha": FloatProperty(name="Base Alpha", description="The alpha values the triangles assigned to this group will begin with", default=1, min=0, max=1,precision=3, update=material_base_alpha_update),
        "double_sided": BoolProperty(name="Double Sided", description="Shows backfaces and allows translucent faces of the same group to be seen through each other", default=False, update=material_double_sided_update),
    }
}

__extensions__ = {
    bpy.types.TOPBAR_MT_file_import: [lambda self, context: self.layout.operator(RS_OT_ImportModel.bl_idname)],
    bpy.types.TOPBAR_MT_file_export: [lambda self, context: self.layout.operator(RS_OT_ExportModel.bl_idname)],
}
