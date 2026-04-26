"""
Stability Regression Scene
==========================

Pathological cases that previously broke preview, selection, and persistence:
- transformed size properties
- layout modifiers like next_to / to_edge
- large relative animation shifts
- chained animation transforms
"""

from manim import (
    Axes,
    BLUE,
    Circle,
    Dot,
    DOWN,
    FadeOut,
    GREEN,
    MathTex,
    PI,
    RED,
    RIGHT,
    Scene,
    Text,
    UP,
    WHITE,
    YELLOW,
)
import numpy as np


class StabilityRegressionScene(Scene):
    """Regression-only fixture for manual engine verification."""

    def construct(self) -> None:
        title = Text("Regression Fixture", font_size=26, color=WHITE)
        title.to_edge(DOWN, buff=1.3)
        self.add(title)

        axes = Axes(
            x_range=[-3, 3, 1],
            y_range=[-2, 2, 1],
            x_length=4.8,
            y_length=3.0,
            tips=False,
            axis_config={"color": WHITE, "stroke_width": 1.4},
        )
        axes.move_to([0.8, 0.3, 0.0])
        self.add(axes)

        equation = MathTex(r"f(x) = \sin(\pi x)", font_size=28, color=WHITE)
        equation.next_to(axes, UP, buff=0.3)
        self.add(equation)

        circle = Circle(
            radius=1.2,
            color=RED,
            fill_opacity=0.4,
            stroke_opacity=1.0,
            stroke_width=6.0,
        )
        circle.scale(-2.6)
        circle.move_to([5.2, -1.4, 0.0])
        self.add(circle)

        dot = Dot(
            axes.c2p(0.5, np.sin(0.5 * PI)),
            radius=0.6,
            color=YELLOW,
            stroke_opacity=1.0,
            stroke_width=20.0,
            fill_opacity=1.0,
        )
        dot.scale(26.5)
        dot.move_to([5.0, 2.2, 0.0])
        self.add(dot)

        helper = Dot(color=GREEN, radius=0.08)
        helper.move_to([-2.0, -1.6, 0.0])
        self.add(helper)

        self.play(FadeOut(title, shift=DOWN * 19.3), run_time=0.8)
        self.play(dot.animate.shift(RIGHT * 2).rotate(PI / 6), run_time=0.6)
        self.play(circle.animate.move_to([4.0, -2.0, 0.0]), run_time=0.6)
        self.play(helper.animate.shift(UP * 1.2), run_time=0.4)
