from manim import *
import main
config.renderer = "opengl"

label = MathTex('\\sin(x)')
snapshot = label.copy()

anim = FadeIn(label)
anim.begin()

try:
    label.become(snapshot)
    anim.interpolate(0.5)
    print("Interpolate successful.")
except Exception as e:
    import traceback
    traceback.print_exc()

