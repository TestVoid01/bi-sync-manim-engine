import sys
import os
import numpy as np
import traceback
import main
from manim import *
from PyQt6.QtWidgets import QApplication
from engine.canvas import ManimCanvas
from engine.state import EngineState
from scenes.advanced_scene import AdvancedScene

app = QApplication(sys.argv)
state = EngineState()
canvas = ManimCanvas(AdvancedScene, state)
canvas.initializeGL()
canvas.paintGL()

player = canvas._animation_player
player.play()

for i in range(100):
    player.update(1.0 / 60.0)

for mob in canvas._scene.mobjects:
    if "ParametricFunction" in str(type(mob)):
        print(f"{type(mob).__name__} points: {len(mob.points)}")
        print(f"  stroke_width: {mob.stroke_width[0] if len(mob.stroke_width)>0 else None}")
        swl = mob.get_stroke_shader_wrapper()
        if swl:
            print(f"  normal: {swl.vert_data['unit_normal'][0]}")

print("Queue index:", player._queue_index)
print("State:", player._state)
