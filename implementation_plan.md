# Bi-Sync Manim Engine - Implementation Plan

## Problem 1: The "Black Screen" Trap
**Issue:** 
When you make a typo or error in the code editor, the Manim `construct()` method fails, resulting in an empty scene (black screen). When you fix the error, the system's `ASTMutator` compares the new code's variables with the old code's variables. Since the variable names haven't changed (you just fixed a value or typo), it assumes no structural change occurred and attempts a "Fast Property Update" instead of rebuilding the scene. However, because the scene is empty from the previous crash, there are no objects to update. The system gets stuck, leaving the screen black until a forced manual refresh.

**Solution: State-Aware Reloading**
1. **Track Scene Health:** We will introduce a `scene_is_healthy` flag in the engine state.
2. **Mark as Unhealthy on Error:** If a hot-swap or `construct()` execution throws an error (or results in 0 mobjects unexpectedly), we will set `scene_is_healthy = False`.
3. **Force Full Reload on Recovery:** In `MainWindow`, we will modify the smart detection logic. If the scene was marked as unhealthy during the last run, the next code save will *always* trigger a **Full Scene Reload** to restore all objects, completely bypassing the "Fast Property Update".

---

## Problem 2: Limited Manim Property Support in Real-Time
**Issue:** 
Currently, `HotSwapInjector.apply_single_property` uses a hardcoded list to handle specific properties like `radius`, `side_length`, `color`, and `fill_opacity`. If you change a property that isn't on this list (or a completely new Manim feature), the fast update ignores it, and you don't see the change in real-time.

**Solution: Generic Property Updater via Reflection**
1. **Keep Math-Heavy Specifics:** We will keep the specific handlers for properties that require complex math (like scaling a circle when `radius` changes, since Manim uses `width/height` under the hood).
2. **Implement a Smart Fallback:** For any property not explicitly listed, we will dynamically attempt to apply it:
   - First, we will check if Manim has a built-in setter method for it (e.g., if you change `stroke_color`, we look for `set_stroke_color()`).
   - If no setter exists, we will use Python's `setattr()` to directly inject the new value into the object.
3. **Smart Color Detection:** If the property name contains the word "color" (e.g., `sheen_color`), we will automatically route it through our newly fixed `_resolve_color` system so Manim understands it.

This approach means you won't have to manually code every single Manim feature into the system. The engine will figure it out dynamically.
