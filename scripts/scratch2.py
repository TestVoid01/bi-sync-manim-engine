import sys, os
from pathlib import Path
os.environ["MANIM_RENDERER"] = "opengl"
from manim import config
config.renderer = "opengl"

from engine.state import EngineState
from engine.ast_mutator import ASTMutator
from engine.hit_tester import HitTester
from engine.coordinate_transformer import CoordinateTransformer
from engine.drag_controller import DragController
from engine.runtime_provenance import configure_tracking, patch_manim_creation_tracking

configure_tracking(os.path.abspath("scenes/advanced_scene.py"), project_root=os.path.abspath("."))
patch_manim_creation_tracking()

engine_state = EngineState()
ast_mutator = ASTMutator()
ast_mutator.parse_file("scenes/advanced_scene.py")

hit_tester = HitTester(engine_state, ast_mutator)
coord = CoordinateTransformer()

class MockScene:
    def __init__(self):
        from scenes.advanced_scene import AdvancedScene
        self._scene = AdvancedScene()
        self._scene.renderer = type('MockR', (), {'init_scene': lambda s: None, 'update_frame': lambda s: None, 'camera': type('MockC', (), {'init_background': lambda: None})()})()
        
        # advance animations to end
        def mock_play(*anims, **kw):
            for anim in anims:
                if hasattr(anim, 'mobject'):
                    self._scene.add(anim.mobject)
        self._scene.play = mock_play
        self._scene.wait = lambda *a, **k: None
        self._scene.construct()
        self.mobjects = self._scene.mobjects

scene = MockScene()
drag = DragController(engine_state, hit_tester, coord, ast_mutator)
drag.set_scene(scene._scene)

for m in scene.mobjects:
    try:
        min_x = float(m.get_left()[0])
        max_x = float(m.get_right()[0])
        min_y = float(m.get_bottom()[1])
        max_y = float(m.get_top()[1])
        engine_state.push_hitbox(id(m), (min_x, min_y, max_x, max_y))
    except Exception as e:
        pass

# math_x = 0, math_y = 0 should be center of screen (px=640, py=360)
# we assume 1280x720 widget size
coord.set_widget_size(1280, 720)
print(f"Test selection at center (640, 360)")
res = drag.on_mouse_press(640, 360)
print(f"Result: {res}")
print(f"Selected mobject: {engine_state.selected_mobject_name}")

