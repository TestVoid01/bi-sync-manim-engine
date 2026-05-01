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
from engine.renderer import HijackedRenderer

app = QApplication(sys.argv)
state = EngineState()
canvas = ManimCanvas(AdvancedScene, state)
canvas.initializeGL()
canvas.paintGL() # This calls _do_first_init()

# Play manually
player = canvas._animation_player
player.play()

# Fast-forward until crash
print("Playing headless...")
for i in range(100):
    try:
        player.update(1.0 / 60.0)
    except Exception as e:
        print(f"CRASH AT FRAME {i}")
        traceback.print_exc()
        sys.exit(1)
    
print("Finished 100 frames.")
