import sys
from manim import *
import main
from engine.state import EngineState
from engine.canvas import ManimCanvas
from PyQt6.QtWidgets import QApplication

app = QApplication(sys.argv)
state = EngineState()

# First run
from scenes.advanced_scene import AdvancedScene
canvas = ManimCanvas(AdvancedScene, state)
canvas.initializeGL()
canvas.paintGL() # this runs _do_first_init

# check points
print("Points after init:", len(canvas._scene.mobjects[0].points))

# Simulate refresh
print("Reloading...")
canvas.reload_scene_from_module("scenes.advanced_scene", "scenes/advanced_scene.py")

print("Points after reload:", len(canvas._scene.mobjects[0].points))

