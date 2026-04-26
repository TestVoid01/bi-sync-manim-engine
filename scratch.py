from manim import VGroup, Circle, Square

v = VGroup(Circle(), Square())

class MockRenderer:
    def __init__(self):
        self.calls = 0
    def render_mobject(self, m):
        self.calls += 1

mr = MockRenderer()
# in Manim OpenGL, how is render_mobject called?
# It is called on scene.mobjects
for m in [v]:
    mr.render_mobject(m)
print(f"Calls: {mr.calls}")
