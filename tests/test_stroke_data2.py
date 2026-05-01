import numpy as np
from manim import *
import manim.mobject.opengl.opengl_vectorized_mobject as m

config.renderer = "opengl"

curve = ParametricFunction(
    lambda t: np.array([t, np.sin(t), 0]),
    t_range=[-PI, PI],
    color=BLUE
)
curve.init_points()

wrapper = curve.get_stroke_shader_wrapper()
print("Wrapper attributes:", dir(wrapper))
print("Shader Folder:", getattr(wrapper, 'shader_folder', None))

if hasattr(wrapper, 'read_data_info'):
    print("Read data info method exists.")

if hasattr(wrapper, 'vert_data'):
    print("vert_data exists, shape:", getattr(wrapper.vert_data, 'shape', None))
    print("vert_data dtype names:", wrapper.vert_data.dtype.names)
    if 'unit_normal' in wrapper.vert_data.dtype.names:
        print("First 5 normals in vert_data:")
        print(wrapper.vert_data['unit_normal'][:5])
