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
# Manually corrupt the normal to Y-axis
curve.unit_normal[:] = [0.0, -1.0, 0.0]

# Now generate the wrapper (this is what Manim does internally)
wrapper = curve.get_stroke_shader_wrapper()

print("Wrapper normal before fix:", wrapper.vert_data['unit_normal'][0])

# Now the previous planner tried to fix it like this:
curve.unit_normal[:] = [0.0, 0.0, 1.0]

print("Mobject normal after fix:", curve.unit_normal[0])
print("Wrapper normal after fix:", wrapper.vert_data['unit_normal'][0])

if wrapper.vert_data['unit_normal'][0][2] < 0.1:
    print("BUG VERIFIED: The wrapper retains the cached old normal data!")
