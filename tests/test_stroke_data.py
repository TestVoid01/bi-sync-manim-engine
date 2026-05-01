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

print("Mobject Class:", type(curve).__mro__)
if hasattr(curve, 'unit_normal'):
    print("Unit Normal descriptor direct:", curve.unit_normal)
else:
    print("unit_normal not present on this object")

if hasattr(curve, 'get_stroke_shader_wrapper'):
    wrapper = curve.get_stroke_shader_wrapper()
    print("Shader Wrapper block names:", wrapper.shader_data.dtype.names if hasattr(wrapper, 'shader_data') else "No shader data")
    if hasattr(wrapper, 'shader_data') and 'unit_normal' in wrapper.shader_data.dtype.names:
        print("First 5 normals in shader data:")
        print(wrapper.shader_data['unit_normal'][:5])
else:
    print("No get_stroke_shader_wrapper method.")
