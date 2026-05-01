import numpy as np
from manim import *
import manim.mobject.opengl.opengl_vectorized_mobject as m

config.renderer = "opengl"

axes = Axes(x_range=[-4, 4, 1], y_range=[-3, 3, 1], x_length=8, y_length=5)
sine1 = axes.plot(lambda x: np.sin(x), x_range=[-4, 4], color=BLUE)

# Snapshot before animation
snapshot = sine1.copy()

anim = Create(sine1)
anim.begin()

print("Initial points shape:", sine1.points.shape)

try:
    for alpha in [0.1, 0.2, 0.5]:
        # Mimic _restore_base_state_for_active_anims
        sine1.become(snapshot)
        
        # Mimic interpolate
        anim.interpolate(alpha)
        print(f"Alpha {alpha} points shape: {sine1.points.shape}")
        
except Exception as e:
    import traceback
    traceback.print_exc()
    print("CRASHED!", e)

