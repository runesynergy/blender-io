import os
import bpy
import bmesh
import json
import math

from mathutils import Vector
from bpy.types import Operator, Panel, UIList, PropertyGroup
from bpy.props import StringProperty, FloatProperty, BoolProperty
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
    mesh.import_path = filepath

    obj = bpy.data.objects.new(name, mesh)
    context.collection.objects.link(obj)
    context.view_layer.objects.active = obj

    bm = bmesh.new()
    
    label_layer = bm.verts.layers.int.new("label")
    
    for index, vertex in enumerate(data["vertices"]):
        x = vertex[0]
        y = vertex[2]
        z = -vertex[1]
        
        v = bm.verts.new((x,y,z))
        v[label_layer] = data["vertex_label"][index]        
    bm.verts.ensure_lookup_table()

    uv_layer = bm.loops.layers.uv.get("color")

    if not uv_layer:
        uv_layer = bm.loops.layers.uv.new("color")

    materials = {}
    
    for index, face in enumerate(data["faces"]):
        type = data["face_type"][index]
        color = data["face_color"][index]
        alpha = data["face_alpha"][index]
        double_sided = data["face_double_sided"][index]
                
        u = ((color % 128.0) + 0.5) / 128.0
        v = ((color / 128.0)) / 512.0
        v = 1.0 - v
        
        f = bm.faces.new([bm.verts[i] for i in face])
        f.smooth = type & 1 == 0
        
        for loop in f.loops:
            loop[uv_layer].uv = (u, v)

        facegroup = "{}".format(alpha)
        if double_sided:
            facegroup += "_DS"
        material = materials.get(facegroup)
        
        if not material:
            material = create_facegroup(obj, facegroup, alpha)
            if double_sided:
                material.double_sided = True
            materials[facegroup] = material

        material_index = obj.material_slots.find(material.name)
        f.material_index = material_index
        
    bm.faces.ensure_lookup_table()
    bm.faces.index_update()
            
    bm.to_mesh(mesh)
    bm.free()

    mesh.update()

    return {'FINISHED'}

def Export(context, filepath):
    bpy.ops.object.mode_set(mode='OBJECT')

    obj = context.active_object

    if not obj:
        return {'CANCELLED'}
    
    mesh = obj.data

    if not mesh:
        print("Unable to export model: no mesh")
        return {'CANCELLED'}

    armature_obj = obj.find_armature()
    armature = None    
    
    if armature_obj:
        armature = armature_obj.data

        for bone_index, bone in enumerate(armature.bones):
            if not "origin" in bone:
                bone["origin"] = 255 - bone_index
            if not "label" in bone:
                bone["label"] = bone_index

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

        if armature:
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

    if armature:
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
        if mode == 'JSON':
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

def create_facegroup(obj, name, transparency):
    material = bpy.data.materials.new(name)
    obj.data.materials.append(material)

    material.use_nodes = True
    material.use_backface_culling = True
    material.blend_method = 'BLEND'
    material.base_alpha = (255 - transparency) / 255
    shader_node_tree = material.node_tree
    nodes = shader_node_tree.nodes
    nodes.clear()
    
    shader_node = nodes.new(type='ShaderNodeBsdfPrincipled')
    shader_node.location = (0, 0)
    shader_node.inputs["Specular"].default_value = 0
    shader_node.inputs["Roughness"].default_value = 1
    shader_node.inputs["Alpha"].default_value = material.base_alpha
    
    output_node = nodes.new(type='ShaderNodeOutputMaterial')
    output_node.location = (300, 0)

    texture_node = nodes.new(type='ShaderNodeTexImage')
    texture_node.location = (-300, 0)
    texture_node.interpolation = 'Closest'
    texture_node.image = load_image("palette.png")
    
    links = shader_node_tree.links
    links.new(texture_node.outputs['Color'], shader_node.inputs['Base Color'])
    links.new(shader_node.outputs['BSDF'], output_node.inputs['Surface'])

    return material

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

def get_label_vertices(mesh):
    label_vertices = {}
    label_layer = mesh.vertex_layers_int["label"]
    if label_layer is None:
        label_layer = mesh.vertex_layers_int.new(name="label")
    for index, vertex_data in label_layer.data.items():
        label = vertex_data.value
        if label not in label_vertices:
            label_vertices[label] = []
        label_vertices[label].append(mesh.vertices[index])
    return label_vertices

def get_label_median(label_vertices, labels):
    vertices = []
    for label in labels:
        if label in label_vertices:
            vertices.extend([v.co for v in label_vertices[label]])
    if len(vertices) == 0:
        return Vector((0,0,0))
    return sum(vertices, Vector((0,0,0))) / len(vertices)

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
        return Export(context, self.filepath)

class RS_OT_FaceGroup_Create(Operator):
    """Create a new face group"""

    bl_idname = "facegroup.create"
    bl_label = "Create Face Group"

    def execute(self, context):
        create_facegroup(context.active_object, "Group", 0)
        return {'FINISHED'}

class RS_OT_FaceGroup_Delete(Operator):
    """Deletes the active face group. (Note: You should reassign the faces in this group first!)"""
    
    bl_idname = "facegroup.delete"
    bl_label = "Delete"
    
    def execute(self, context):
        mode = context.object.mode
        bpy.ops.object.mode_set(mode='OBJECT')
        bpy.ops.object.material_slot_remove()
        bpy.ops.object.mode_set(mode=mode)
        return {'FINISHED'}

class RS_OT_FaceGroup_Assign(Operator):
    """Assigns the selected faces to the active face group"""

    bl_idname = "facegroup.assign"
    bl_label = "Assign"

    def execute(self, context):
        bpy.ops.object.material_slot_assign()
        return {'FINISHED'}

class RS_OT_FaceGroup_Select(Operator):
    """Selects all the faces in the active face group"""
    bl_idname = "facegroup.select"
    bl_label = "Select"
    
    def execute(self, context):
        bpy.ops.object.material_slot_select()
        return {'FINISHED'}
    
class RS_OT_FaceGroup_Deselect(Operator):
    """Deselects all the faces in the active face group"""
    bl_idname = "facegroup.deselect"
    bl_label = "Deselect"
    
    def execute(self, context):
        bpy.ops.object.material_slot_deselect()
        return {'FINISHED'}

class RS_UL_FaceGroups(UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        if item.material:
            layout.prop(item.material, "name", text="", icon="FACE_MAPS", emboss=False)
        else:
            layout.label(text="Invalid Slot")

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
    bpy.types.Mesh: {
        "import_path": StringProperty(name="Import Path", description="The path this mesh was imported from"),
    },
    bpy.types.Material: {
        "base_alpha": FloatProperty(name="Base Alpha", description="The alpha values the triangles assigned to this group will begin with", default=1, min=0, max=1,precision=3, update=material_base_alpha_update),
        "double_sided": BoolProperty(name="Double Sided", description="Shows backfaces and allows translucent faces of the same group to be seen through each other", default=False, update=material_double_sided_update),
    }
}

__extensions__ = {
    bpy.types.TOPBAR_MT_file_import: [lambda self, context: self.layout.operator(RS_OT_ImportModel.bl_idname)],
    bpy.types.TOPBAR_MT_file_export: [lambda self, context: self.layout.operator(RS_OT_ExportModel.bl_idname)],
}
