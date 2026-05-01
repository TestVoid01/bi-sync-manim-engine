import sys
import os
import numpy as np
import traceback
import main
from manim import *
from engine.canvas import ManimCanvas
from engine.state import EngineState
from scenes.advanced_scene import AdvancedScene

# We must use ManimCanvas to get capturing_play
# Since we don't have a Qt loop, we mock it.
from PyQt6.QtWidgets import QApplication
app = QApplication(sys.argv)

state = EngineState()
canvas = ManimCanvas(AdvancedScene, state)
canvas.initializeGL()
canvas.paintGL() # _do_first_init intercepts and populates player

player = canvas._animation_player
player.play()

for _ in range(60):
    player._tick()

print(f"Axes points after 60 ticks (end of Create): {len(canvas._scene.mobjects[0].points)}")

for _ in range(30):
    player._tick()

sine1 = canvas._scene.mobjects[1]
print(f"Sine1 points at t=1.5s (mid Create): {len(sine1.points)}")

swl = sine1.get_stroke_shader_wrapper()
print(f"Sine1 swl normal: {swl.vert_data['unit_normal'][0] if swl else 'No wrapper'}")
print(f"Sine1 has points: {len(sine1.points)}")
print(f"Sine1 should_render: {sine1.should_render}")
print(f"Sine1 stroke_width: {sine1.stroke_width[0]}")
print(f"Sine1 color: {sine1.rgbas[0]}")
