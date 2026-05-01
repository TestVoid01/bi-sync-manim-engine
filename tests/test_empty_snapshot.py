import sys
from manim import *
import main
from engine.state import EngineState
from engine.animation_player import AnimationPlayer
from scenes.advanced_scene import AdvancedScene

config.renderer = "opengl"
scene = AdvancedScene()

engine_state = EngineState()
player = AnimationPlayer(engine_state)
player.set_scene(scene)

# Run construct (which uses capturing_play)
scene.construct()

# Now inspect player._original_queue
# Entry 0 is Create(axes)
anims0, rt0, kw0, snap0 = player._original_queue[0]
axes_in_0 = list(snap0.keys())[0]
print(f"Snapshot 0 axes points: {len(snap0[axes_in_0].points)}")

anims1, rt1, kw1, snap1 = player._original_queue[1]
axes_in_1 = list(snap1.keys())[0]
print(f"Snapshot 1 axes points: {len(snap1[axes_in_1].points)}")

# Entry 2 is Create(sine2)
anims2, rt2, kw2, snap2 = player._original_queue[2]
axes_in_2 = list(snap2.keys())[0]
sine1_in_2 = list(snap2.keys())[1]
print(f"Snapshot 2 axes points: {len(snap2[axes_in_2].points)}")
print(f"Snapshot 2 sine1 points: {len(snap2[sine1_in_2].points)}")

