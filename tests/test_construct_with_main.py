import sys
import main
from manim import *
config.renderer = "opengl"
from scenes.advanced_scene import AdvancedScene
scene = AdvancedScene()

# Use canvas to capture
from engine.state import EngineState
from engine.canvas import ManimCanvas
from PyQt6.QtWidgets import QApplication

app = QApplication(sys.argv)
state = EngineState()

canvas = ManimCanvas(AdvancedScene, state)
canvas.initializeGL()
canvas.paintGL()

player = canvas._animation_player
print(f"Captured: {len(player._original_queue)} animations.")
