import sys, os
os.environ["MANIM_RENDERER"] = "opengl"
from manim import config
config.renderer = "opengl"

from manim.mobject.mobject import Mobject
_orig_mobject_init = Mobject.__init__
def _patched_mobject_init(self, *args, **kwargs):
    _orig_mobject_init(self, *args, **kwargs)
    try:
        frame = sys._getframe(1)
        while frame:
            filename = frame.f_code.co_filename
            if "scenes" in filename and filename.endswith(".py"):
                self._bisync_line_number = frame.f_lineno
                break
            frame = frame.f_back
    except Exception:
        pass
Mobject.__init__ = _patched_mobject_init

from engine.state import EngineState
from engine.ast_mutator import ASTMutator
from engine.hit_tester import HitTester
from engine.renderer import HijackedRenderer

engine_state = EngineState()
ast_mutator = ASTMutator()
ast_mutator.parse_file("scenes/advanced_scene.py")

hit_tester = HitTester(engine_state, ast_mutator)
renderer = HijackedRenderer(engine_state)

import importlib
module = importlib.import_module("scenes.advanced_scene")
scene = module.AdvancedScene(renderer=renderer)
scene.construct()

print(f"Num Mobjects in scene: {len(scene.mobjects)}")

# Force populate hitboxes
engine_state.clear_hitboxes()
for m in scene.mobjects:
    renderer.render_mobject(m)

hitboxes = engine_state.get_hitboxes()
print(f"Num Hitboxes: {len(hitboxes)}")
for k, v in hitboxes.items():
    print(f"  Hitbox {k}: {v}")

# Simulate click at origin (0, 0)
mob_ids = hit_tester.test(0.0, 0.0)
print(f"Hit at (0,0): {mob_ids}")
if mob_ids:
    mob_id = mob_ids[0]
    result = hit_tester.find_mobject_and_path(mob_id, scene)
    print(f"Found Mobject: {result}")
    ast_ref = hit_tester.get_ast_ref(result[0] if result else None)
    print(f"AST Ref: {ast_ref}")
