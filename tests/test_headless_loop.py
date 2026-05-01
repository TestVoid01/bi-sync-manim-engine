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

scene.construct()
print(f"Captured {len(player._original_queue)} animations.")

# Let's mock request_render and update_frame so it runs headless perfectly
engine_state.request_render = lambda: None
if not hasattr(scene, 'renderer'):
    scene.renderer = type('DummyRenderer', (), {'update_frame': lambda s: None})()

player.play()

frame_count = 0
while player._state == AnimationPlayer.PLAYING:
    player.update(1.0 / 60.0)
    frame_count += 1
    
    if frame_count % 60 == 0:
        print(f"Played {frame_count} frames, currently at animation {player._queue_index}")

print(f"Finished playing {frame_count} frames successfully!")
