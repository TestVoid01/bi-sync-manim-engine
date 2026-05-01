import sys
import numpy as np
from manim import *
import main 
from scenes.advanced_scene import AdvancedScene

config.renderer = "opengl"

scene = AdvancedScene()
scene.construct()

for i, mob in enumerate(scene.mobjects):
    if "ParametricFunction" in str(type(mob)):
        print(f"Checking Mob[{i}] ({type(mob).__name__})")
        # Trigger the wrapper generation (which should trigger our patch)
        sw = mob.get_stroke_shader_wrapper()
        if sw:
            normals = sw.vert_data['unit_normal']
            print(f"  Wrapper Normal[0]: {normals[0]}")
            if normals[0][2] > 0.9:
                print("  RESULT: FIX APPLIED SUCCESSFULLY!")
            else:
                print("  RESULT: Still wrong.")
