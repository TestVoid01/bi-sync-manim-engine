import sys
import numpy as np
from PIL import Image
from manim import *
import main 
from scenes.advanced_scene import AdvancedScene
from engine.animation_player import AnimationPlayer
from engine.state import EngineState

# Use capturing_play correctly
from engine.canvas import ManimCanvas
from PyQt6.QtWidgets import QApplication
app = QApplication(sys.argv)
engine_state = EngineState()
canvas = ManimCanvas(AdvancedScene, engine_state)
canvas.initializeGL()
canvas.paintGL() # triggers construct and capturing_play

player = canvas._animation_player

# Play fully once
print("First play...")
player.play()
for i in range(300):
    player._tick()

# Now Reset and Play again (like Repeat button)
print("Resetting and playing again...")
player.reset()
# player.reset() clears the queue! 
# Wait, Reset button clears the queue and does what?
# Let's check main.py _on_reset_clicked

