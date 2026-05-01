import sys
import numpy as np
from manim import *

config.renderer = "opengl"
config.use_projection_stroke_shaders = False
config.use_projection_fill_shaders = False

axes = Axes(x_range=[-4, 4, 1], y_range=[-3, 3, 1], x_length=8, y_length=5)
sine1 = axes.plot(lambda x: np.sin(x), x_range=[-4, 4], color=BLUE)
sine1.init_points()

print(f"Points: {len(sine1.points)}")
swl = sine1.get_shader_wrapper_list()
print(f"Shader Wrappers count: {len(swl)}")
if len(swl) > 0:
    for sw in swl:
        print(f"Shader Folder: {sw.shader_folder}")
