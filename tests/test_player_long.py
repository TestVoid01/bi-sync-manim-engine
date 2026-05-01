import sys
import os
import main
from manim import *
from engine.state import EngineState
from engine.animation_player import AnimationPlayer
from scenes.advanced_scene import AdvancedScene

config.renderer = "opengl"

engine_state = EngineState()

# Use capturing_play correctly
from engine.canvas import ManimCanvas
from PyQt6.QtWidgets import QApplication
app = QApplication(sys.argv)
canvas = ManimCanvas(AdvancedScene, engine_state)
canvas.initializeGL()
canvas.paintGL() # triggers construct and capturing_play

player = canvas._animation_player
player.play()

# Advance 300 frames (5 seconds)
# Frame 0-48: Create axes (0.8s)
# Frame 48-108: Create sine1 (1.0s)
# Frame 108-168: Create sine2 (1.0s)
# Frame 168-228: Create sine3 (1.0s)
# Frame 228-288: Create sine4 (1.0s)
for i in range(300):
    player._tick()

print(f"Queue index at 300 frames: {player._queue_index}")
print(f"Mobjects in scene: {len(canvas._scene.mobjects)}")

for i, mob in enumerate(canvas._scene.mobjects):
    print(f"Mob {i} ({type(mob).__name__}) points: {len(mob.points)}")
    swl = mob.get_stroke_shader_wrapper()
    if swl:
        print(f"  normal: {swl.vert_data['unit_normal'][0]}")

