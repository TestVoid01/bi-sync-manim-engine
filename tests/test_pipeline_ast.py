import os
import shutil
from pathlib import Path

os.environ["MANIM_RENDERER"] = "opengl"
from manim import config
config.renderer = "opengl"

from engine.ast_mutator import ASTMutator

def test_ast_mutator():
    print("=== TESTING AST MUTATOR ===")
    scene_path = Path("scenes/advanced_scene.py")
    backup_path = Path("scenes/advanced_scene_backup_ast.py")
    shutil.copy(scene_path, backup_path)
    
    try:
        mutator = ASTMutator()
        mutator.parse_file(scene_path)
        print(f"Bindings found: {len(mutator.bindings)}")
        print(f"Animations found: {len(mutator.animations)}")
        
        # Test 1: Update Property
        print("\n[Test 1] Updating property 'fill_opacity' of 'triangle' to 0.5...")
        success = mutator.update_property("triangle", "fill_opacity", 0.5)
        mutator.save_atomic()
        print(f"Update success: {success}")
        
        # Verify formatting preservation
        with open(scene_path, "r") as f:
            content = f.read()
            if "#" in content:
                print("Comments preserved: Yes")
            else:
                print("Comments preserved: No (Formatting destroyed by ast.unparse)")
            
            if "fill_opacity=0.5" in content or "fill_opacity=0.5" in content.replace(" ", ""):
                print("Value updated in source: Yes")
            else:
                print("Value updated in source: No")

        # Test 2: Update Animation Method and Kwargs
        print("\n[Test 2] Updating animation method and kwargs for 'triangle'...")
        # Get animation ref
        anim_ref = None
        for a in mutator.animations:
            if a.target_var == "triangle":
                anim_ref = a
                break
        
        if anim_ref:
            # Change SpinInFromNothing to FadeIn
            success1 = mutator.update_animation_method("triangle", anim_ref.method_name, "FadeIn")
            # Change run_time to 2.5
            success2 = mutator.update_animation_kwarg("triangle", "run_time", 2.5)
            mutator.save_atomic()
            print(f"Update animation method success: {success1}")
            print(f"Update animation kwarg success: {success2}")
            
            with open(scene_path, "r") as f:
                content = f.read()
                if "FadeIn(triangle)" in content:
                    print("Method updated in source: Yes")
                else:
                    print("Method updated in source: No")
                if "run_time=2.5" in content:
                    print("Kwarg updated in source: Yes")
                else:
                    print("Kwarg updated in source: No")
        else:
            print("Triangle animation not found.")
            
    finally:
        shutil.copy(backup_path, scene_path)
        backup_path.unlink()
        print("=== AST MUTATOR TEST COMPLETE ===\n")

if __name__ == "__main__":
    test_ast_mutator()
