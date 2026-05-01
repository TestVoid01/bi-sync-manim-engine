import sys
import numpy as np
from manim import *
import logging

import main 
from scenes.advanced_scene import AdvancedScene
from engine.animation_player import AnimationPlayer
from engine.state import EngineState

config.renderer = "opengl"
scene = AdvancedScene()

engine_state = EngineState()
player = AnimationPlayer(engine_state)
player.set_scene(scene)

try:
    scene.construct()
    print("Construct passed. Playing...")
    
    # Run the player loop manually
    player.play()
    for _ in range(100):
        if player._state != AnimationPlayer.PLAYING:
            break
        player.update(1.0 / 60.0)
        
    print("Done playing.")
except Exception as e:
    import traceback
    traceback.print_exc()
