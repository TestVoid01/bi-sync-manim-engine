import sys
import numpy as np
from manim import *

config.renderer = "opengl"
axes = Axes(x_range=[-4, 4, 1], y_range=[-3, 3, 1], x_length=8, y_length=5)
sine1 = axes.plot(lambda x: np.sin(x), x_range=[-4, 4], color=BLUE)
sine1.init_points()

print("Original sine1 points shape:", sine1.points.shape)

# Create animation
anim = Create(sine1)

# Step 1: Snapshot BEFORE begin()
snapshot1 = sine1.copy()
print("Snapshot 1 points shape:", snapshot1.points.shape)

# Step 2: anim.begin()
anim.begin()
print("sine1 points shape after begin:", sine1.points.shape)

# Step 3: player.capture_play_call() uses snapshot1
# Wait! In capturing_play, the snapshot was taken BEFORE begin!
print("If we restore snapshot1 during playback:")
try:
    sine1.become(snapshot1)
    anim.interpolate(0.5)
    print("Interpolate 0.5 points shape:", sine1.points.shape)
except Exception as e:
    import traceback
    traceback.print_exc()
    print("CRASHED!", e)
