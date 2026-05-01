from manim import *
import logging
logging.basicConfig(level=logging.DEBUG)
config.renderer = "opengl"

from engine.state import EngineState
from engine.renderer import HijackedRenderer

engine_state = EngineState()
renderer = HijackedRenderer(engine_state)

scene = Scene()
scene.renderer = renderer

pt_a = np.array([-4, -2, 0])
pt_b = np.array([4, 2, 0])
points = [pt_a, [-2, 1, 0], [0, -3, 0], [2, 3, 0], [3, 0, 0], pt_b]
chaos_path = VMobject(color=ORANGE, stroke_width=4).set_points_smoothly(points)

scene.add(chaos_path)

try:
    renderer.render_mobject(chaos_path)
except Exception as e:
    import traceback
    traceback.print_exc()

