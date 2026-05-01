import numpy as np
from manim import *
import manim.mobject.opengl.opengl_vectorized_mobject as m

config.renderer = "opengl"

curve = ParametricFunction(
    lambda t: np.array([t, np.sin(t), 0]),
    t_range=[-PI, PI],
    color=BLUE
)

print("Before animation:")
curve.init_points()
print("Normal before:", curve.unit_normal)

# Let's run a simple Create animation headless
anim = Create(curve)
anim.begin()

print("\nDuring animation:")
for alpha in [0.0, 0.5, 1.0]:
    anim.interpolate(alpha)
    print(f"Alpha {alpha} normal: {curve.unit_normal}")
