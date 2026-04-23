# Bi-Sync Manim Engine - Bug & Glitch Report

This document contains a deep architectural and logical analysis of the engine, identifying subtle bugs, race conditions, and logic flaws that may cause glitches during use.

## 1. Ghost Renderer Mobject Mismatch (The "Doppelganger" Bug)
**Location:** `engine/canvas.py` -> `paintGL()`
**Issue:** When rendering the ghost for a target animation, the code searches for the target mobject by looking at `self._scene.mobjects` and picking the *first* object whose type matches the AST's `constructor_name` (`if mob_type == binding.constructor_name:`).
**Impact:** If the scene has multiple objects of the same type (e.g., three `Circle`s), and you animate the third one, the ghost will incorrectly clone the *first* `Circle`. It fails to use variable names or `mobject_id` to reliably identify the correct object for the ghost.

## 2. Hardcoded Variable Names in Property Live-Update
**Location:** `engine/hot_swap.py` -> `apply_single_property()`
**Issue:** The mapping from the property panel's target variable to the scene's mobject is entirely hardcoded to specific strings:
```python
if target_var == "circle" and mob_type == "Circle": ...
elif target_var == "square" and mob_type == "Square": ...
```
**Impact:** If a user names their variable anything else, like `my_circle = Circle()`, the property panel's real-time sliders will completely break, outputting `Mobject not found for: my_circle` in the logs. The fast-path update will silently fail.

## 3. Chained Method AST Blindspot
**Location:** `engine/ast_mutator.py` -> `PropertyFinder.visit_Expr()`
**Issue:** The AST parser looks for standalone transforms like `target_var.scale(1.5)`. It explicitly checks if `isinstance(node.value.func.value, ast.Name)`. 
**Impact:** In Manim, it's very common to chain methods: `circle.scale(1.5).set_color(RED)`. In the AST, `.value` becomes another `Call` node rather than a `Name`. The mutator will silently ignore all chained transformations, causing sync failures.

## 4. Ghost Snap-to-Cursor Jump
**Location:** `engine/drag_controller.py` -> `on_mouse_press()`
**Issue:** When initiating a drag on an animation ghost, the code explicitly resets the grab offset to zero: `self._drag_offset_x = 0.0`. 
**Impact:** When the mouse moves to the next frame, the ghost's center immediately snaps to the tip of the mouse cursor instead of maintaining the relative distance from where the user grabbed it. This creates a very jarring visual jump at the start of the drag.

## 5. Nested Object AST Injection Failure
**Location:** `engine/drag_controller.py` -> `_update_ast_position()` -> `MoveCallInjector`
**Issue:** When dragging an object that doesn't yet have a `.move_to()` or `.shift()` call, the code uses a `NodeTransformer` to inject a new `.move_to()` statement. However, its `visit_FunctionDef` method only scans `n.body` (the top-level statements of the function).
**Impact:** If the object was created inside an `if` block, a `for` loop, or a `VGroup` context, the injection silently fails to find the insertion point because it doesn't traverse into nested statement blocks. The user's drag is completely lost upon release.

## 6. Destructive AST Overwrites on Mere Clicks
**Location:** `engine/drag_controller.py` -> `on_mouse_release()`
**Issue:** If a user simply clicks and releases an object *without moving the mouse*, `on_mouse_release` still retrieves the current `get_center()` and triggers an AST rewrite.
**Impact:** If a user had mathematically clean code like `circle = Circle().shift(UP * 2)`, just clicking the circle will irreversibly destroy their expression and rewrite it to `circle.move_to([0.0, 2.0, 0.0])`. A click without a drag movement should not mutate the file.

## 7. Fragile Hot-Swap Array Matching (Index Shifting)
**Location:** `engine/hot_swap.py` -> `_apply_updates()`
**Issue:** During a fast-path code hot-swap, the system extracts properties from a temporary scene and applies them to the current scene by pairing old and new mobjects strictly by their class name and list index (`new_list[i]` with `old_list[i]`).
**Impact:** If a user modifies the code to insert a new `Square` *before* an existing `Square`, the existing `Square` will incorrectly inherit the new `Square`'s properties. All subsequent squares shift down an index, completely scrambling the visual state until a full, hard reload occurs.
