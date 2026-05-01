import os
import sys
from manim import *
import main
from engine.state import EngineState
from engine.canvas import ManimCanvas
from PyQt6.QtWidgets import QApplication

app = QApplication(sys.argv)
state = EngineState()

from scenes.advanced_scene import AdvancedScene
canvas = ManimCanvas(AdvancedScene, state)
canvas.initializeGL()
canvas.paintGL()

player = canvas._animation_player
print(f"Total animations in player queue: {len(player._original_queue)}")
