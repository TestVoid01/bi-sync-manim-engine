from manim import *
import numpy as np

CYAN = "#00FFFF"

class AdvancedScene(ThreeDScene):
    """
    Bi-Sync Engine Export / Motion Script Animation
    Contains 4 scenes demonstrating concepts of relative rest,
    distance vs displacement, velocity vectors, and 3D vector fields.
    """
    def construct(self):
        # ---------------------------------------------------------
        # [SCENE 1: The Illusion of Absolute Rest]
        # ---------------------------------------------------------
        self.camera.background_color = BLACK
        dot = Dot(ORIGIN, color=WHITE, radius=0.08)
        
        axes = Axes(
            x_range=[-5, 5, 1], y_range=[-5, 5, 1],
            axis_config={'color': DARK_GREY, 'stroke_width': 1.0}
        )
        self.add(dot)
        self.wait(1)
        
        # Grid fades in behind the dot
        self.play(FadeIn(axes), run_time=2)
        
        # Group to scale and move together to reveal the star
        local_frame = VGroup(axes, dot)
        star = Circle(radius=1.5, color=YELLOW, fill_opacity=0.9).move_to(RIGHT * 4)
        
        # Zoom out drastically
        self.play(
            local_frame.animate.scale(0.12).shift(LEFT * 2),
            FadeIn(star, shift=LEFT),
            run_time=3
        )
        self.wait(1)
        
        # Orbit mechanics
        orbit_angle = ValueTracker(np.pi)
        local_frame.add_updater(lambda m: m.move_to(
            star.get_center() + 4 * np.array([np.cos(orbit_angle.get_value()), np.sin(orbit_angle.get_value()), 0])
        ))
        
        orbit_vec = always_redraw(lambda: Arrow(
            local_frame.get_center(), 
            local_frame.get_center() + 1.2 * np.array([-np.sin(orbit_angle.get_value()), np.cos(orbit_angle.get_value()), 0]), 
            color=RED, buff=0, stroke_width=4, max_tip_length_to_length_ratio=0.2
        ))
        
        speed_text = always_redraw(lambda: Text("107,000 km/h", font_size=18, color=RED).next_to(orbit_vec, UP, buff=0.1))
        
        self.play(Create(orbit_vec), FadeIn(speed_text))
        self.play(orbit_angle.animate.increment_value(np.pi / 4), run_time=4, rate_func=linear)
        self.wait(2)
        
        # ---------------------------------------------------------
        # [SCENE 2: The Chaos Trail (Distance vs. Displacement)]
        # ---------------------------------------------------------
        # Clear screen safely (filtering for VMobjects only)
        self.play(FadeOut(VGroup(*[m for m in self.mobjects if isinstance(m, VMobject)])))
        self.camera.background_color = "#000022"  # Dark blue background
        
        pt_a = np.array([-4, -2, 0])
        pt_b = np.array([4, 2, 0])
        dot_a = Dot(pt_a, color=YELLOW)
        dot_b = Dot(pt_b, color=RED)
        self.play(FadeIn(dot_a), FadeIn(dot_b))
        
        # Chaotic zigzag path
        points = [pt_a, [-2, 1, 0], [0, -3, 0], [2, 3, 0], [3, 0, 0], pt_b]
        chaos_path = VMobject(color=ORANGE).set_points_smoothly(points)
        
        dist_tracker = ValueTracker(0)
        dist_label = Text("दूरी (Distance) = ", font_size=24).to_corner(UL)
        dist_num = always_redraw(lambda: DecimalNumber(dist_tracker.get_value(), num_decimal_places=1, font_size=24).next_to(dist_label, RIGHT))
        dist_unit = always_redraw(lambda: Text("m", font_size=24).next_to(dist_num, RIGHT, buff=0.1))
        
        self.play(FadeIn(VGroup(dist_label, dist_num, dist_unit)))
        
        dot_moving = Dot(pt_a, color=YELLOW)
        self.add(dot_moving)
        
        self.play(
            MoveAlongPath(dot_moving, chaos_path),
            Create(chaos_path),
            dist_tracker.animate.set_value(42.6),
            run_time=6, rate_func=linear
        )
        self.wait(2)
        
        # The sharp straight-line vector (Displacement)
        cyan_arrow = Arrow(pt_a, pt_b, buff=0, color=CYAN, stroke_width=6)
        disp_label = Text("विस्थापन (Displacement) = ", font_size=24, color=CYAN).next_to(dist_label, DOWN, aligned_edge=LEFT)
        disp_val = Text("8.9m", font_size=24, color=CYAN).next_to(disp_label, RIGHT)
        
        self.play(Create(cyan_arrow), FadeIn(VGroup(disp_label, disp_val), shift=UP), run_time=2)
        self.play(Wiggle(cyan_arrow, scale_value=1.2))
        self.wait(4)
        
        # ---------------------------------------------------------
        # [SCENE 3: The Quantum Trap of the Loop]
        # ---------------------------------------------------------
        self.play(FadeOut(VGroup(*[m for m in self.mobjects if isinstance(m, VMobject)])))
        self.camera.background_color = BLACK
        
        circle_track = Circle(radius=2.5, color=WHITE, stroke_width=2)
        green_dot = Dot(RIGHT * 2.5, color=GREEN, radius=0.1)
        speedometer = MathTex(r"\text{Speed: } 100 \text{ m/s}").to_corner(UL)
        
        self.play(Create(circle_track), FadeIn(green_dot), FadeIn(speedometer))
        
        theta = ValueTracker(0)
        green_dot.add_updater(lambda d: d.move_to([2.5 * np.cos(theta.get_value()), 2.5 * np.sin(theta.get_value()), 0]))
        
        # Rotating velocity vector
        vel_arrow = always_redraw(lambda: Arrow(
            green_dot.get_center(),
            green_dot.get_center() + 1.5 * np.array([-np.sin(theta.get_value()), np.cos(theta.get_value()), 0]),
            buff=0, color=YELLOW
        ))
        self.add(vel_arrow)
        self.play(theta.animate.increment_value(np.pi), run_time=5, rate_func=linear)
        self.wait(1)
        
        # Zoom in on X and Y components
        vx_arrow = always_redraw(lambda: Arrow(
            green_dot.get_center(),
            green_dot.get_center() + np.array([-1.5 * np.sin(theta.get_value()), 0, 0]),
            buff=0, color=RED, max_tip_length_to_length_ratio=0.15
        ))
        vy_arrow = always_redraw(lambda: Arrow(
            green_dot.get_center(),
            green_dot.get_center() + np.array([0, 1.5 * np.cos(theta.get_value()), 0]),
            buff=0, color=BLUE, max_tip_length_to_length_ratio=0.15
        ))
        
        self.play(FadeIn(vx_arrow), FadeIn(vy_arrow))
        self.play(theta.animate.increment_value(np.pi), run_time=6, rate_func=linear)
        self.wait(1)
        
        # Complete the circle back to start
        self.play(theta.animate.set_value(2 * np.pi), run_time=2, rate_func=smooth)
        
        # Flashes red indicating the trap
        self.camera.background_color = "#4a0000"
        
        # Shrinking displacement vector
        def disp_updater(mob):
            start_pos = np.array([2.5, 0, 0])
            current_pos = green_dot.get_center()
            dist = np.linalg.norm(current_pos - start_pos)
            if dist < 0.1:
                mob.set_stroke(opacity=0)
                mob.set_fill(opacity=0)
            else:
                mob.set_stroke(opacity=1)
                mob.set_fill(opacity=1)
                mob.put_start_and_end_on(start_pos, current_pos)
                
        disp_vector = Arrow(np.array([2.5, 0, 0]), np.array([2.5, 0.01, 0]), color=CYAN, buff=0)
        disp_vector.add_updater(disp_updater)
        self.add(disp_vector)
        
        # Little nudge to trigger updater explicitly to show zero displacement
        self.play(theta.animate.set_value(2 * np.pi + 0.5), run_time=1)
        self.play(theta.animate.set_value(2 * np.pi), run_time=1)
        self.camera.background_color = BLACK
        
        # Equation breakdown
        def get_eq(disp_text="Displacement", val_text=None):
            eq = VGroup(
                Text("Average Velocity = ", font_size=36),
                Text(disp_text, font_size=36, color=CYAN),
                Text(" / Time", font_size=36)
            ).arrange(RIGHT)
            if val_text is not None:
                eq[1].become(Text(val_text, font_size=36, color=CYAN).move_to(eq[1]))
            return eq
            
        eq1 = get_eq().to_edge(UP, buff=1)
        self.play(FadeIn(eq1, shift=DOWN))
        self.wait(1)
        
        eq2 = get_eq(val_text="0").to_edge(UP, buff=1)
        self.play(Transform(eq1, eq2))
        
        eq3 = Text("Average Velocity = 0", font_size=36, color=CYAN).to_edge(UP, buff=1)
        self.play(Transform(eq1, eq3))
        self.wait(3)
        
        # ---------------------------------------------------------
        # [SCENE 4: The Vector Anatomy (The Aha! Moment)]
        # ---------------------------------------------------------
        self.play(FadeOut(VGroup(*[m for m in self.mobjects if isinstance(m, VMobject)])))
        self.camera.background_color = BLACK
        
        formula = MathTex(r"\vec{v} = \lim_{\Delta t \to 0} \frac{\Delta \vec{r}}{\Delta t} = \frac{d\vec{r}}{dt}", font_size=48)
        self.play(Write(formula), run_time=2)
        self.play(Wiggle(formula, color=YELLOW))
        self.wait(1)
        self.play(FadeOut(formula))
        
        # 3D Vector field and axes setup
        axes_3d = ThreeDAxes()
        self.move_camera(phi=75 * DEGREES, theta=30 * DEGREES, run_time=2)
        self.play(Create(axes_3d))
        
        def vector_field_func(pos):
            return np.array([-pos[1], pos[0], 0.5]) * 0.5
            
        vec_field = ArrowVectorField(
            vector_field_func, 
            x_range=[-4, 4, 1], y_range=[-4, 4, 1], z_range=[-2, 2, 1], 
            opacity=0.3
        )
        self.play(FadeIn(vec_field))
        
        curve_3d = ParametricFunction(
            lambda t: np.array([3 * np.cos(t), 3 * np.sin(t), t - 2]),
            t_range=[0, 4],
            color=YELLOW,
            stroke_width=4
        )
        self.play(Create(curve_3d), run_time=4)
        
        # [OUTRO]
        self.move_camera(phi=0, theta=0, run_time=2)
        self.play(
            FadeOut(axes_3d),
            FadeOut(vec_field),
            Transform(curve_3d, Dot(ORIGIN, color=WHITE, radius=0.08)),
            run_time=3
        )
        self.wait(2)
        self.play(FadeOut(curve_3d), run_time=2)
        self.wait(2)
