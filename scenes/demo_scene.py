"""
Demo Scene — Test Scene for Bi-Sync Manim Engine
==================================================

Scene with filled shapes for testing the full bi-directional
sync pipeline: Canvas ↔ Code Editor ↔ Property Panel.
"""
from manim import Circle, Dot, Line, Scene, Square, Triangle, BLUE, GREEN, RED, WHITE, YELLOW, ORIGIN, RIGHT, LEFT, UP, DOWN

class DemoScene(Scene):
    """Test scene with 6 mobjects for bi-directional sync testing.

    Each shape can be:
    - Dragged on canvas → code updates
    - Modified via slider → code + canvas update
    - Edited in code editor → canvas + sliders update
    """

    def construct(self) -> None:
        circle = Circle(radius=1.8, color=BLUE, fill_opacity=0.0)
        circle.move_to([-2.9, -0.38, 0.0])
        square = Square(side_length=1.9, color=RED, fill_opacity=0.3)
        square.move_to([1.92, 0.4, 0.0])
        dot = Dot(point=ORIGIN, radius=0.15, color=GREEN)
        triangle = Triangle(color=YELLOW, fill_opacity=0.0)
        triangle.scale(0.8)
        triangle.move_to([1.86, 2.01, 0.0])
        h_line = Line(LEFT * 0.5, RIGHT * 0.5, color=WHITE)
        v_line = Line(DOWN * 0.5, UP * 0.5, color=WHITE)
        self.add(circle, square, dot, triangle, h_line, v_line)
