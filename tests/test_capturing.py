import sys
import main
from manim import *
config.renderer = "opengl"
from scenes.advanced_scene import AdvancedScene
scene = AdvancedScene()

from engine.state import EngineState
from engine.animation_player import AnimationPlayer

state = EngineState()
player = AnimationPlayer(state)
player.set_scene(scene)

def capturing_play(*animations, **kwargs):
    print("capturing_play called with", len(animations), "animations")
    player.capture_play_call(scene, animations, kwargs, {})

scene.play = capturing_play
scene.construct()
print(f"Total in queue: {len(player._original_queue)}")
