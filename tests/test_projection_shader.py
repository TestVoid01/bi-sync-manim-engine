import numpy as np
from manim import *
import manim.mobject.opengl.opengl_vectorized_mobject as m

config.renderer = "opengl"
config.use_projection_stroke_shaders = True

curve = ParametricFunction(
    lambda t: np.array([t, np.sin(t), 0]),
    t_range=[-PI, PI],
    color=BLUE
)
curve.init_points()

# When use_projection_stroke_shaders is True, the rendering flow changes.
print("use_projection_stroke_shaders:", config.use_projection_stroke_shaders)

if hasattr(curve, 'get_stroke_shader_wrapper'):
    wrapper = curve.get_stroke_shader_wrapper()
    print("Shader Folder:", getattr(wrapper, 'shader_folder', None))
    if hasattr(wrapper, 'vert_data'):
        print("vert_data dtype names:", wrapper.vert_data.dtype.names)
        if 'unit_normal' in wrapper.vert_data.dtype.names:
            print("unit_normal still exists!")
        else:
            print("unit_normal is gone! The issue is completely bypassed.")
else:
    print("No get_stroke_shader_wrapper method.")

