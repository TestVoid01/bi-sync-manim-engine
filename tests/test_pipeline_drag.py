import os
import shutil
from pathlib import Path

os.environ["MANIM_RENDERER"] = "opengl"
from manim import config
config.renderer = "opengl"

from engine.state import EngineState
from engine.ast_mutator import ASTMutator
from engine.hit_tester import HitTester
from engine.coordinate_transformer import CoordinateTransformer
from engine.drag_controller import DragController

def test_drag_pipeline():
    print("=== TESTING DRAG PIPELINE ===")
    scene_path = Path("scenes/advanced_scene.py")
    backup_path = Path("scenes/advanced_scene_backup_drag.py")
    shutil.copy(scene_path, backup_path)
    
    try:
        state = EngineState()
        mutator = ASTMutator()
        mutator.parse_file(scene_path)
        
        hit_tester = HitTester(state, mutator)
        coord = CoordinateTransformer()
        coord.set_widget_size(1280, 720)
        drag = DragController(state, hit_tester, coord, mutator)
        
        # Mock scene and hitboxes
        class MockScene:
            def __init__(self):
                self.mobjects = []
        
        # We need a real Mobject to test hit detection properly, or we can bypass hit detection and just test the AST update manually
        # Let's bypass hit detection and just call _update_ast_position directly
        print("\n[Test 1] Updating position via DragController AST logic...")
        # Get line number of triangle
        triangle_ref = mutator.get_binding_by_name("triangle")
        if triangle_ref:
            # We bypass the internal queue and SPSC loop, directly calling the AST update method that runs on mouse release
            drag._update_ast_position("triangle", 12.5, -5.5, triangle_ref.line_number, [])
            mutator.save_atomic()
            
            with open(scene_path, "r") as f:
                content = f.read()
                if "[12.5, -5.5, 0.0]" in content:
                    print("Drag position updated in source: Yes")
                else:
                    print("Drag position updated in source: No")
        else:
            print("Triangle not found in AST.")
            
    finally:
        shutil.copy(backup_path, scene_path)
        backup_path.unlink()
        print("=== DRAG PIPELINE TEST COMPLETE ===\n")

if __name__ == "__main__":
    test_drag_pipeline()
