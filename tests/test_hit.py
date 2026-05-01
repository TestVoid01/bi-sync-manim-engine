import sys
import os

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

engine_state = EngineState()
ast_mutator = ASTMutator()
ast_mutator.parse_file("scenes/advanced_scene.py")

hit_tester = HitTester(engine_state, ast_mutator)

import importlib
module = importlib.import_module("scenes.advanced_scene")
scene = module.AdvancedScene()
scene.construct()

print("Bindings:")
for k, v in ast_mutator.bindings.items():
    print(f"  {k}: line {v.line_number}")

# Pick a mobject from the scene
for mob in scene.mobjects:
    print(f"Testing {type(mob).__name__}")
    var_name = hit_tester.get_variable_name(mob)
    print(f"  Parent resolved to: {var_name}")
    if hasattr(mob, 'submobjects') and mob.submobjects:
        sub = mob.submobjects[0]
        sub_var = hit_tester.get_variable_name(sub)
        print(f"  Submobject resolved to: {sub_var}")

