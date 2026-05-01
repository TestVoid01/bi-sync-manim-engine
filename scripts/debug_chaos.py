import sys
import numpy as np
from manim import *
from engine.state import EngineState
from engine.canvas import ManimCanvas
from engine.animation_player import AnimationPlayer
from engine.ast_mutator import ASTMutator
from PyQt6.QtWidgets import QApplication

app = QApplication(sys.argv)

class TestScene(ThreeDScene):
    def construct(self):
        pt_a = np.array([-4, -2, 0])
        pt_b = np.array([4, 2, 0])
        points = [pt_a, [-2, 1, 0], [0, -3, 0], [2, 3, 0], [3, 0, 0], pt_b]
        self.chaos_path = VMobject(color=ORANGE).set_points_smoothly(points)
        self.dot_moving = Dot(pt_a, color=YELLOW)
        self.add(self.dot_moving)
        self.play(MoveAlongPath(self.dot_moving, self.chaos_path), Create(self.chaos_path), run_time=1)

state = EngineState()
canvas = ManimCanvas(TestScene, state)
canvas._do_first_init()

player = canvas._animation_player
scene = canvas._scene

print("After construct:")
print("chaos_path points length:", len(scene.chaos_path.points))
print("chaos_path rgbas length:", len(scene.chaos_path.rgbas))

# Simulate replay
player.seek(0.5)

print("At alpha=0.5:")
print("chaos_path points length:", len(scene.chaos_path.points))
print("chaos_path rgbas length:", len(scene.chaos_path.rgbas))
print("chaos_path stroke_width length:", len(scene.chaos_path.stroke_width))
