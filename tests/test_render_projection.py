import sys
import numpy as np
from manim import *

# Enable projection shaders!
config.use_projection_stroke_shaders = True
config.use_projection_fill_shaders = True

# We need a proper OpenGL context for this test, so let's import the engine stuff
from engine.renderer import HijackedRenderer

class MockScene(Scene):
    def construct(self):
        axes = Axes(x_range=[-4, 4, 1], y_range=[-3, 3, 1], x_length=8, y_length=5)
        sine1 = axes.plot(lambda x: np.sin(x), x_range=[-4, 4], color=BLUE)
        self.add(axes, sine1)

try:
    renderer = HijackedRenderer(None)
    scene = MockScene(renderer=renderer)
    
    # Try to render a frame
    renderer.update_frame(scene)
    print("Frame updated successfully with projection shaders.")
    
    wrapper_list = scene.mobjects[0].get_shader_wrapper_list()
    print("Shader Wrapper list folders:")
    for w in wrapper_list:
        print("  -", getattr(w, 'shader_folder', None))
    
except Exception as e:
    import traceback
    traceback.print_exc()
    print("CRASHED!", e)
