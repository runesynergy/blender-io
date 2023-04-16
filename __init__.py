
bl_info = {
    "name": "Rune Synergy Addon",
    "author": "Dane",
    "version": (1, 0),
    "blender": (3, 4, 1),
    "description": "",
    "category": "Import-Export",
}

import bpy
import sys
import os
import importlib

for filename in [ f for f in os.listdir(os.path.dirname(os.path.realpath(__file__))) if f.endswith(".py") ]:
    if filename == os.path.basename(__file__):
        continue
    module = sys.modules.get("{}.{}".format(__name__,filename[:-3]))
    if module:
        importlib.reload(module)

# clear out any scene update funcs hanging around, e.g. after a script reload
for collection in [bpy.app.handlers.depsgraph_update_post, bpy.app.handlers.load_post]:
    for func in collection:
        if func.__module__.startswith(__name__):
            collection.remove(func)

from . import model, rig, animation
__modules_ = (model, rig, animation)

def register():
    for module in __modules_:
        print(module.__name__)
        if hasattr(module, "__classes__"):
            for cls in module.__classes__:
                bpy.utils.register_class(cls)
                
        if hasattr(module, "__properties__"):
            for type, properties in module.__properties__.items():
                for name, value in properties.items():
                    setattr(type, name, value)
            
        if hasattr(module, "__extensions__"):
            for type, extensions in module.__extensions__.items():
                for extension in extensions:
                    type.append(extension)
            
        if hasattr(module, "__hooks__"):
            for type, hooks in module.__hooks__.items():
                for hook in hooks:
                    getattr(bpy.app.handlers, type).append(hook)

def unregister():
    for module in __modules_:
        if hasattr(module, "__classes__"):
            for cls in module.__classes__:
                bpy.utils.unregister_class(cls)


        if hasattr(module, "__properties__"):
            for type, properties in module.__properties__.items():
                for name in properties.keys():
                    delattr(type, name)
            
        if hasattr(module, "__extensions__"):
            for type, extensions in module.__extensions__.items():
                for extension in extensions:
                    type.remove(extension)

        if hasattr(module, "__hooks__"):
            for type, hooks in module.__hooks__.items():
                for hook in hooks:
                    getattr(bpy.app.handlers, type).remove(hook)
                    

if __name__ == "__main__":
    register()