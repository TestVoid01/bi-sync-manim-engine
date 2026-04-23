import sys
import os

# Monkey-patch Mobject to track creation line numbers
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
                print(f"[TEST] Mobject {type(self).__name__} created at {filename}:{frame.f_lineno}")
                break
            frame = frame.f_back
    except Exception as e:
        print("Exception in patch", e)

Mobject.__init__ = _patched_mobject_init

import importlib
module = importlib.import_module("scenes.advanced_scene")
scene = module.AdvancedScene()
scene.construct()

print("Mobjects in scene:")
for mob in scene.mobjects:
    print(f"{type(mob).__name__}: {getattr(mob, '_bisync_line_number', None)}")
