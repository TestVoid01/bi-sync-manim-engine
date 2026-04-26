"""
Advanced Demo Scene — Complex Mathematical Visualization
=========================================================

A visually rich scene with animations to test the Bi-Sync Engine:
- Mathematical function plots (sine wave)
- Geometric constructions
- LaTeX equations
- self.play() animations captured by AnimationPlayer
"""
from manim import Scene, Circle, Square, Triangle, Dot, Line, Arrow, MathTex, Text, VGroup, Axes, ParametricFunction, BLUE, RED, GREEN, YELLOW, WHITE, ORANGE, PURPLE, ORIGIN, LEFT, RIGHT, UP, DOWN, PI, FadeIn, Create, Write, GrowFromCenter, GrowArrow, SpinInFromNothing, FadeOut, Indicate, config
import numpy as np

class AdvancedScene(Scene):
    """Complex scene with math plots, LaTeX, and animations.

    Animations are captured by AnimationPlayer and replayed
    frame-by-frame when user presses Play.
    """

    def construct(self) -> None:
        title = Text('Bi-Sync Engine', font_size=20, color=WHITE)
        title.to_edge(UP, buff=0.3)
        self.play(FadeIn(title, shift=DOWN * 0.3), run_time=0.8)
        axes = Axes(x_range=[-3, 3, 1], y_range=[-2, 2, 1], x_length=5, y_length=3, tips=False, axis_config={'color': WHITE, 'stroke_width': 1.5})
        axes.rotate(0.0)
        axes.move_to([-3.46, -0.49, 0.0])
        self.play(Create(axes), run_time=1.0)
        sine_curve = axes.plot(lambda x: np.sin(x * PI), x_range=[-3, 3], color=BLUE, fill_opacity=0.0, stroke_width=4.3, stroke_opacity=1.0)
        sine_curve.rotate(0.0)
        sine_curve.scale(1.5)
        sine_curve.move_to([-3.58, -0.87, 0.0])
        self.play(Create(sine_curve), run_time=1.5)
        equation = MathTex('f(x) = \\sin(\\pi x)', font_size=28, color=WHITE)
        equation.next_to(axes, UP, buff=0.3)
        self.play(Write(equation), run_time=1.0)
        circle = Circle(radius=0.8, color=RED, fill_opacity=0.5)
        circle.move_to([3.53, 1.37, 0.0])
        self.play(GrowFromCenter(circle), run_time=0.8)
        square = Square(side_length=1.2, color=ORANGE, fill_opacity=0.4)
        square.move_to([3.5, -0.5, 0.0])
        self.play(SpinInFromNothing(square), run_time=1.0)
        triangle = Triangle(color=PURPLE, fill_opacity=0.3)
        triangle.scale(0.6)
        triangle.shift(RIGHT * 3.5 + DOWN * 2.2)
        self.play(GrowFromCenter(triangle), run_time=0.6)
        arrow1 = Arrow(start=ORIGIN, end=RIGHT * 1.5 + UP * 0.8, color=RED, stroke_width=2.5)
        arrow1.shift(RIGHT * 0.5 + DOWN * 2)
        arrow2 = Arrow(start=ORIGIN, end=RIGHT * 0.5 + UP * 1.5, color=GREEN, stroke_width=2.5)
        arrow2.move_to([0.93, -1.79, 0.0])
        self.play(GrowArrow(arrow1), GrowArrow(arrow2), run_time=0.8)
        vec_a = MathTex('\\vec{a}', font_size=24, color=RED)
        vec_a.next_to(arrow1.get_end(), RIGHT, buff=0.1)
        vec_b = MathTex('\\vec{b}', font_size=24, color=GREEN)
        vec_b.next_to(arrow2.get_end(), LEFT, buff=0.1)
        self.play(Write(vec_a), Write(vec_b), run_time=0.6)
        dot = Dot(axes.c2p(0.5, np.sin(0.5 * PI)), radius=0.1, color=YELLOW)
        self.play(FadeIn(dot, scale=3), run_time=0.5)
        self.play(Indicate(equation, color=YELLOW), run_time=0.8)
