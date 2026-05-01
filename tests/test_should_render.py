from manim import *
import numpy as np

config.renderer = "opengl"
axes = Axes(x_range=[-4, 4, 1], y_range=[-3, 3, 1])
sine1 = axes.plot(lambda x: np.sin(x), x_range=[-4, 4], color=BLUE)

print("Original should_render:", sine1.should_render)
sine1.__dict__['should_render'] = True
print("After dict hack should_render:", sine1.should_render)

# Now what if it's during animation?
anim = Create(sine1)
anim.begin()
print("After Create begin should_render:", sine1.should_render)
anim.interpolate(0.5)
print("After Create interpolate 0.5 should_render:", sine1.should_render)
