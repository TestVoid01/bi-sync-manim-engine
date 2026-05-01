from manim import *
import copy

config.renderer = "opengl"
config.preview = False
config.write_to_movie = False

class TestScene(Scene):
    def construct(self):
        path = VMobject(color=ORANGE).set_points_smoothly([[-2,0,0], [0,2,0], [2,0,0]])
        
        # Simulate capturing_play
        self.add(path)
        
        anim = Create(path)
        anim._setup_scene(self)
        anim.begin()
        
        # Snapshot exactly at alpha=0
        copied_state = path.copy()
        
        # Fast forward
        anim.interpolate(1.0)
        anim.finish()
        anim.clean_up_from_scene(self)
        
        # Now simulate AnimationPlayer replay
        self.mobjects.clear()
        
        # Restore state
        path.become(copied_state)
        self.add(path)
        
        # Simulate rendering a frame at alpha=0.5
        anim.interpolate(0.5)
        
        # Check path state
        print(f"Path points shape: {path.points.shape}")
        print(f"Path stroke width: {path.stroke_width}")
        print(f"Path color: {path.color}")

if __name__ == "__main__":
    scene = TestScene()
    scene.render()
