from manim import *
import numpy as np

CYAN = '#00FFFF'

class AdvancedScene(ThreeDScene):
    """
    Bi-Sync Test Scene — Beautiful Mathematical Composition
    Tests axes.plot(), labels, and basic shapes properly arranged.
    """

    def construct(self):
        self.camera.background_color = BLACK
        
        # 1. Main Axes (Centered)
        axes = Axes(
            x_range=[-4, 4, 1], 
            y_range=[-3, 3, 1], 
            x_length=10, 
            y_length=6, 
            tips=False, 
            axis_config={'color': WHITE, 'stroke_width': 2.0}
        )
        axes.move_to(ORIGIN)
        self.play(Create(axes), run_time=1.5)

        # 2. Plotting Functions (Correctly aligned to axes)
        sine1 = axes.plot(lambda x: np.sin(x), x_range=[-4, 4], color=BLUE)
        sine2 = axes.plot(lambda x: np.sin(2 * x), x_range=[-4, 4], color=RED) # Fixed opacity bug
        sine3 = axes.plot(lambda x: 0.5 * np.sin(4 * x), x_range=[-4, 4], color=GREEN)
        sine4 = axes.plot(lambda x: np.cos(x), x_range=[-4, 4], color=YELLOW)
        sine5 = axes.plot(lambda x: np.exp(-0.3 * abs(x)) * np.sin(3 * x), x_range=[-4, 4], color=CYAN)

        self.play(
            Create(sine1), 
            Create(sine2), 
            run_time=1.5
        )
        self.play(
            Create(sine3), 
            Create(sine4), 
            Create(sine5), 
            run_time=2.0
        )

        # 3. Neatly arranged Labels
        label1 = MathTex('\\sin(x)', font_size=28, color=BLUE)
        label1.next_to(axes.c2p(2, np.sin(2)), UP)

        label2 = MathTex('\\sin(2x)', font_size=28, color=RED)
        label2.next_to(axes.c2p(1, np.sin(2)), DOWN)

        label3 = MathTex('0.5\\sin(4x)', font_size=28, color=GREEN)
        label3.next_to(axes.c2p(3, 0.5 * np.sin(12)), DOWN)

        label4 = MathTex('\\cos(x)', font_size=28, color=YELLOW)
        label4.next_to(axes.c2p(0, 1), UP, buff=0.5)

        label5 = MathTex('e^{-|x|}\\sin(3x)', font_size=28, color=CYAN)
        label5.next_to(axes.c2p(-2, np.exp(-0.6) * np.sin(-6)), UP)

        self.play(
            FadeIn(label1, shift=UP), 
            FadeIn(label2, shift=DOWN), 
            FadeIn(label3, shift=DOWN), 
            FadeIn(label4, shift=UP), 
            FadeIn(label5, shift=UP), 
            run_time=1.5
        )
        
        self.wait(1)

        # 4. Geometric Shapes on the sides
        triangle = Triangle(color=PURPLE, fill_opacity=0.5, stroke_width=4.0)
        triangle.scale(0.8)
        triangle.to_corner(UL)
        
        square = Square(side_length=1.5, color=ORANGE, fill_opacity=0.3, stroke_width=4.0)
        square.to_corner(UR)
        
        self.play(
            SpinInFromNothing(triangle), 
            SpinInFromNothing(square), # Fixed spelling bug
            run_time=1.0
        )
        
        # 5. Final continuous rotation to look cool
        self.play(
            triangle.animate.rotate(PI),
            square.animate.rotate(-PI),
            run_time=2.0
        )
        
        self.wait(2)
