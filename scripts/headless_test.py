import sys
from PyQt6.QtWidgets import QApplication
from engine.canvas import ManimCanvas
from engine.state import EngineState
from scenes.advanced_scene import AdvancedScene

app = QApplication(sys.argv)
state = EngineState()
canvas = ManimCanvas(AdvancedScene, state)
canvas._do_first_init()
