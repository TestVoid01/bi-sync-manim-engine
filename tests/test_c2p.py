import numpy as np
from manim import *

axes = Axes(x_range=[-4, 4, 1], y_range=[-3, 3, 1], x_length=8, y_length=5)
print("Before Create begin, axes center:", axes.get_center())
print("c2p(4, 0):", axes.c2p(4, 0))

anim = Create(axes)
anim.begin()

print("After Create begin, axes points:", len(axes.points))
print("After Create begin, axes.x_axis points:", len(axes.x_axis.points))
print("c2p(4, 0) after begin:", axes.c2p(4, 0))

# Try creating label next to it
label = MathTex("Test")
try:
    label.next_to(axes.c2p(4, 0), RIGHT)
    print("Label next_to succeeded. Center:", label.get_center())
except Exception as e:
    print("Label next_to failed:", e)

