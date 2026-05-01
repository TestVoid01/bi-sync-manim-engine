from manim import *
import copy
from scenes.advanced_scene import AdvancedScene

config.renderer = "opengl"
config.preview = False
config.write_to_movie = False

class MockPlayer:
    def __init__(self):
        self.count = 0
    def capture_play_call(self, scene, anims, kwargs, state):
        self.count += 1
        print(f"Captured {self.count}!")

class MockRenderer:
    def init_scene(self, scene):
        pass
    def update_frame(self, scene):
        pass

scene = AdvancedScene(renderer=MockRenderer())
scene.setup()
player = MockPlayer()

def capturing_play(*animations, **kwargs):
    try:
        compiled_anims = scene.compile_animations(*animations, **kwargs)
        for anim in compiled_anims:
            mob = getattr(anim, 'mobject', None)
            if mob is not None and mob not in scene.mobjects:
                scene.add(mob)
        state_snapshot = {m: m.copy() for m in scene.mobjects}
        for anim in compiled_anims:
            anim.begin()
        player.capture_play_call(scene, compiled_anims, kwargs, state_snapshot)
        for anim in compiled_anims:
            anim.interpolate(1.0)
            anim.finish()
            anim.clean_up_from_scene(scene)
        scene.update_mobjects(kwargs.get("run_time", 1.0))
    except Exception as e:
        print(f"Play Error: {e}")
        import traceback
        traceback.print_exc()

def capturing_wait(duration=1, **kwargs):
    try:
        w = Wait(duration=duration, **kwargs)
        state_snapshot = {m: m.copy() for m in scene.mobjects}
        w.begin()
        player.capture_play_call(scene, [w], kwargs, state_snapshot)
        w.interpolate(1.0)
        w.finish()
        w.clean_up_from_scene(scene)
    except Exception as e:
        print(f"Wait Error: {e}")
        import traceback
        traceback.print_exc()

scene.play = capturing_play
scene.wait = capturing_wait

try:
    scene.construct()
except Exception as e:
    print(f"Construct Error: {e}")
    import traceback
    traceback.print_exc()
    
print(f"Total animations captured: {player.count}")
