import sys
import logging
from manim import *
from engine.state import EngineState
from engine.canvas import ManimCanvas
from engine.animation_player import AnimationPlayer
from engine.ast_mutator import ASTMutator

# Setup minimal PyQt app
from PyQt6.QtWidgets import QApplication
app = QApplication(sys.argv)

from scenes.advanced_scene import AdvancedScene

# Initialize engine components
engine_state = EngineState()
canvas = ManimCanvas(AdvancedScene, engine_state)
canvas._animation_player = AnimationPlayer()
canvas._ast_mutator = ASTMutator()

# Trigger paintGL initialization manually (headless mode)
# In standalone=True, moderngl doesn't need PyQt context
canvas._ctx = moderngl.create_context(standalone=True, require=330)

from engine.renderer import HijackedRenderer
canvas._renderer = HijackedRenderer(engine_state=engine_state)
canvas._renderer.set_external_context(canvas._ctx)

canvas._scene = AdvancedScene(renderer=canvas._renderer)
canvas._renderer.init_scene(canvas._scene)

# Patch play/wait
original_play = canvas._scene.play
original_wait = getattr(canvas._scene, 'wait', None)
player = canvas._animation_player
scene_ref = canvas._scene

def capturing_play(*animations, **kwargs):
    try:
        if hasattr(scene_ref, 'compile_animations'):
            compiled_anims = scene_ref.compile_animations(*animations, **kwargs)
        else:
            compiled_anims = animations
        for anim in compiled_anims:
            mob = getattr(anim, 'mobject', None)
            if mob is not None and mob not in scene_ref.mobjects:
                scene_ref.add(mob)
        state_snapshot = {m: m.copy() for m in scene_ref.mobjects}
        for anim in compiled_anims:
            anim.begin()
        player.capture_play_call(scene_ref, compiled_anims, kwargs, state_snapshot)
        for anim in compiled_anims:
            anim.interpolate(1.0)
            anim.finish()
            anim.clean_up_from_scene(scene_ref)
        scene_ref.update_mobjects(kwargs.get("run_time", 1.0))
        print(f"Captured play with {len(compiled_anims)} animations")
    except Exception as e:
        print(f"Animation capture error: {e}")
        import traceback
        traceback.print_exc()
        raise

def capturing_wait(duration=1, **kwargs):
    try:
        from manim import Wait
        w = Wait(duration=duration, **kwargs)
        state_snapshot = {m: m.copy() for m in scene_ref.mobjects}
        w.begin()
        player.capture_play_call(scene_ref, [w], kwargs, state_snapshot)
        w.interpolate(1.0)
        w.finish()
        w.clean_up_from_scene(scene_ref)
        print("Captured wait")
    except Exception as e:
        print(f"Wait capture error: {e}")
        raise

canvas._scene.play = capturing_play
canvas._scene.wait = capturing_wait

# Run construct!
print("Running construct...")
try:
    canvas._scene.construct()
except Exception as e:
    print(f"Construct failed: {e}")
    import traceback
    traceback.print_exc()
