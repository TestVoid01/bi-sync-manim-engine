import sys
import numpy as np
from manim import *

config.renderer = "opengl"
axes = Axes(x_range=[-4, 4, 1], y_range=[-3, 3, 1], x_length=8, y_length=5)
sine1 = axes.plot(lambda x: np.sin(x), x_range=[-4, 4], color=BLUE)

print("Stroke width:", sine1.stroke_width)
print("Stroke color:", sine1.stroke_color)
print("Stroke rgba:", sine1.stroke_rgba if hasattr(sine1, 'stroke_rgba') else "None")

wrapper = sine1.get_stroke_shader_wrapper()
print("Wrapper stroke_width:", wrapper.vert_data['stroke_width'][0])
