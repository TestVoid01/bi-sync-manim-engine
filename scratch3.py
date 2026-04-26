import os
os.environ["MANIM_RENDERER"] = "opengl"
from manim import config, Circle, Square, VGroup
config.renderer = "opengl"
from manim.renderer.opengl_renderer import OpenGLRenderer

class MyRenderer(OpenGLRenderer):
    def __init__(self):
        super().__init__()
        self.calls = []
    def render_mobject(self, mobject):
        self.calls.append(type(mobject).__name__)
        super().render_mobject(mobject)

r = MyRenderer()
r.init_scene(type('Mock', (), {'mobjects': [VGroup(Circle(), Square())], 'camera': type('MCam', (), {'init_background': lambda: None})()})())
r.update_frame(r.scene)
print(r.calls)
