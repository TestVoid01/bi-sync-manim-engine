from manim import *
import logging
import traceback
from scenes.advanced_scene import AdvancedScene

scene = AdvancedScene()

def capturing_play(*animations, **kwargs):
    compiled_anims = scene.compile_animations(*animations, **kwargs) if hasattr(scene, 'compile_animations') else animations
    for anim in compiled_anims:
        if hasattr(anim, "is_introducer") and anim.is_introducer():
            mob = getattr(anim, 'mobject', None)
            if mob is not None and mob not in scene.mobjects:
                scene.add(mob)
        elif hasattr(anim, "add_to_back") and anim not in scene.mobjects:
            scene.add(anim)
        else:
            mob = getattr(anim, 'mobject', None)
            if mob is not None and mob not in scene.mobjects:
                scene.add(mob)

scene.play = capturing_play
scene.wait = lambda *a, **k: None

try:
    scene.construct()
    print("Construct succeeded!")
except Exception as e:
    print(f"Construct failed: {e}")
    traceback.print_exc()
