import os
import time
import shutil
from pathlib import Path
from PyQt6.QtWidgets import QApplication

os.environ["MANIM_RENDERER"] = "opengl"
from manim import config
config.renderer = "opengl"

from engine.state import EngineState
from engine.ast_mutator import ASTMutator
from engine.hot_swap import HotSwapInjector
from engine.animation_player import AnimationPlayer
from engine.drag_controller import DragController
from engine.hit_tester import HitTester
from engine.coordinate_transformer import CoordinateTransformer
from engine.canvas import ManimCanvas

app = QApplication([])

print("=== STARTING INTEGRATION TEST ===")

# 1. Setup Backup
scene_path = Path("scenes/advanced_scene.py")
backup_path = Path("scenes/advanced_scene_backup.py")
shutil.copy(scene_path, backup_path)

try:
    # 2. Initialize Engine
    state = EngineState()
    from scenes.advanced_scene import AdvancedScene
    canvas = ManimCanvas(AdvancedScene, state)
    canvas.initializeGL()
    canvas.paintGL() # triggers construct and capturing_play
    
    ast_mutator = ASTMutator()
    ast_mutator.parse_file(scene_path)
    
    print("\n--- TEST 1: AST Parsing ---")
    print(f"Bindings found: {len(ast_mutator.bindings)}")
    print(f"Animations found: {len(ast_mutator.animations)}")
    
    print("\n--- TEST 2: Property Edit (GUI -> Code) ---")
    circle_ref = ast_mutator.get_binding_by_name("circle")
    if circle_ref:
        success = ast_mutator.update_property("circle", "radius", 5.5)
        print(f"Update radius success: {success}")
        
        # Check if comments survived (Bug #2 check)
        with open(scene_path, "r") as f:
            content = f.read()
            if "#" in content:
                print("Comments preserved: Yes")
            else:
                print("Comments preserved: No (Formatting destroyed by ast.unparse)")
    else:
        print("Circle not found in AST.")

    print("\n--- TEST 3: Hot Swap (Code -> GUI) ---")
    hot_swap = HotSwapInjector(state, ast_mutator)
    hot_swap.set_scene(canvas.get_scene(), scene_path)
    # Simulate external file change
    success = hot_swap.reload_from_file(scene_path)
    print(f"Hot swap success: {success}")

    print("\n--- TEST 4: Dragging Pipeline ---")
    hit_tester = HitTester(state, ast_mutator)
    coord = CoordinateTransformer()
    coord.set_widget_size(1280, 720)
    drag = DragController(state, hit_tester, coord, ast_mutator)
    drag.set_scene(canvas.get_scene())
    
    # Click at center
    print("Testing hit detection at (0,0)...")
    hits = hit_tester.test(0.0, 0.0)
    print(f"Hits: {hits}")

    print("\n--- TEST 5: Animation Pipeline ---")
    player = canvas._animation_player
    print(f"Total animations captured: {player.animation_count}")
    
    # Try seeking
    print("Seeking to 50%...")
    player.seek(0.5)
    print(f"Scene objects after seek: {len(canvas.get_scene().mobjects)}")
    
finally:
    # Restore backup
    shutil.copy(backup_path, scene_path)
    backup_path.unlink()
    print("\n=== INTEGRATION TEST COMPLETE ===")
