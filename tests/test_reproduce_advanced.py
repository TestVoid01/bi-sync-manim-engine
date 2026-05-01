import sys
import numpy as np
from manim import *
import main 
from scenes.advanced_scene import AdvancedScene

config.renderer = "opengl"

scene = AdvancedScene()
scene.construct()

print(f"Total mobjects: {len(scene.mobjects)}")
for i, mob in enumerate(scene.mobjects):
    if "ParametricFunction" in str(type(mob)):
        print(f"Mob[{i}] ({type(mob).__name__}):")
        print(f"  - Points: {len(mob.points)}")
        print(f"  - Has Stroke: {mob.has_stroke()}")
        print(f"  - Stroke Width: {mob.get_stroke_width()}")
        print(f"  - Color: {mob.get_color()}")
        swl = mob.get_shader_wrapper_list()
        print(f"  - Shader Wrappers: {len(swl)}")
        if len(swl) > 0:
            for sw in swl:
                print(f"    - Folder: {sw.shader_folder}")
