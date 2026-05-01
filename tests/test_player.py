from manim import *
import scenes.advanced_scene as sa

scene = sa.AdvancedScene()
captured = []
def capturing_play(*animations, **kwargs):
    if hasattr(scene, 'compile_animations'):
        compiled_anims = scene.compile_animations(*animations, **kwargs)
    else:
        compiled_anims = animations
    captured.append(compiled_anims)
    for anim in compiled_anims:
        mob = getattr(anim, 'mobject', None)
        if mob is not None and mob not in scene.mobjects:
            scene.add(mob)
        elif hasattr(anim, 'add_to_back') and anim not in scene.mobjects:
            scene.add(anim)

scene.play = capturing_play
scene.wait = lambda *a, **k: None

scene.construct()

print("Mobjects in scene at end:", len(scene.mobjects))
for i, anims in enumerate(captured):
    print(f"Play call {i}: {len(anims)} animations")
