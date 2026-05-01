from manim import *
config.renderer = 'opengl'
scene = Scene()
sq = Square()
anims = scene.compile_animations(FadeIn(sq))
for anim in anims:
    print("Is introducer?", anim.is_introducer())
    if anim.is_introducer():
        scene.add(anim.mobject)
    if hasattr(anim, '_setup_scene'):
        anim._setup_scene(scene)
    anim.begin()
    anim.interpolate(1.0)
    anim.finish()
    anim.clean_up_from_scene(scene)

print("Mobjects in scene:", len(scene.mobjects))
