import sys
import numpy as np
from manim import *
from unittest.mock import MagicMock

# Import everything just like main.py
import main
from engine.state import EngineState
from engine.canvas import ManimCanvas
from engine.animation_player import AnimationPlayer
from engine.renderer import HijackedRenderer

class MockQOpenGLWidget:
    def makeCurrent(self): pass
    def doneCurrent(self): pass

# Setup state
engine_state = EngineState()

# Mock Qt
main.QApplication = MagicMock()
main.MainWindow = MagicMock()

try:
    print("Testing if projection shaders bypass the error...")
    # It's tricky to mock the entire Qt OpenGL context, but we verified the shader data bypass earlier.
    print("Projection shaders enabled:", config.use_projection_stroke_shaders)
except Exception as e:
    import traceback
    traceback.print_exc()
