import sys
from manim import *
from engine.state import EngineState
from engine.canvas import ManimCanvas
from engine.animation_player import AnimationPlayer
from PyQt6.QtWidgets import QApplication

app = QApplication(sys.argv)

class TestScene(ThreeDScene):
    def construct(self):
        pt_a = np.array([-4, -2, 0])
        pt_b = np.array([4, 2, 0])
        points = [pt_a, [-2, 1, 0], [0, -3, 0], [2, 3, 0], [3, 0, 0], pt_b]
        self.chaos_path = VMobject(color=ORANGE).set_points_smoothly(points)
        self.play(Create(self.chaos_path))

state = EngineState()
canvas = ManimCanvas(TestScene, state)
canvas._do_first_init()
player = canvas._animation_player

# Check the snapshot
snapshot = player._original_queue[0][2]
chaos_copy = list(snapshot.values())[0]

print("Snapshot points shape:", np.shape(chaos_copy.points))
print("Snapshot rgbas shape:", np.shape(chaos_copy.rgbas))
print("Snapshot stroke_width shape:", np.shape(chaos_copy.stroke_width))
