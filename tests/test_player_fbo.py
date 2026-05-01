import sys
import numpy as np
from PIL import Image
from manim import *
import main 
from scenes.advanced_scene import AdvancedScene
from engine.animation_player import AnimationPlayer
from engine.state import EngineState

config.renderer = "opengl"
scene = AdvancedScene()

engine_state = EngineState()
player = AnimationPlayer(engine_state)
player.set_scene(scene)

scene.construct()

# Setup dummy renderer
class DummyFBO:
    def __init__(self):
        self.viewport = (0, 0, 1920, 1080)
    def use(self): pass

class DummyRenderer:
    def __init__(self):
        self.frame_buffer_object = DummyFBO()
    def update_frame(self, s): pass

scene.renderer = DummyRenderer()

player.play()

for _ in range(60): # 1 second into the animation (axes is playing)
    player.update(1.0 / 60.0)

# Check axes points
axes = scene.mobjects[0]
print(f"Axes points: {len(axes.points)}")

# Continue to 1.5 seconds (sine1 should be playing)
for _ in range(30):
    player.update(1.0 / 60.0)

sine1 = scene.mobjects[1]
print(f"Sine1 points: {len(sine1.points)}")

# We can't easily extract FBO image without a real context, but we can verify the state.
print(f"Sine1 stroke width: {sine1.stroke_width}")
print(f"Sine1 unit normal: {sine1.unit_normal[0] if len(sine1.unit_normal)>0 else 'None'}")
print(f"Sine1 rgbas: {sine1.rgbas[0] if len(sine1.rgbas)>0 else 'None'}")
