import sys
import numpy as np
from manim import *

# Let's import main which applies the monkey patches
import main

config.renderer = "opengl"
axes = Axes(x_range=[-4, 4, 1], y_range=[-3, 3, 1], x_length=8, y_length=5)
sine1 = axes.plot(lambda x: np.sin(x), x_range=[-4, 4], color=BLUE)
sine1.init_points()

wrapper = sine1.get_stroke_shader_wrapper()
print("Wrapper normal after main patch:", wrapper.vert_data['unit_normal'][0])
