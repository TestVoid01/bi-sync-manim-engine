import sys
import os

from engine.state import EngineState
from engine.hot_swap import HotSwapInjector

engine_state = EngineState()
hot_swap = HotSwapInjector(engine_state)
hot_swap._scene_file = "scenes/advanced_scene.py"
hot_swap.reload_from_file("scenes/advanced_scene.py")
