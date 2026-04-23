"""
Bi-Sync Hot-Swap Injector — Zero-Restart Scene Reload
======================================================

Phase 3: Bi-Directional Sync Bridge

Reloads Manim scenes WITHOUT restarting the Python process.
Instead of importlib.reload(), we exec() the new code in an
isolated namespace and extract the updated parameters.

The Flow:
    1. Read new .py file from disk
    2. exec() in isolated dict → get new Scene class
    3. Create temporary scene, call construct()
    4. Extract mobject parameters from new scene
    5. Apply to existing scene's mobjects via setters
    6. Trigger re-render via Socket 3

Safety:
    - exec() runs in isolated namespace (no global pollution)
    - Original scene is preserved if reload fails
    - All errors are caught and logged (no crashes)
"""

from __future__ import annotations

import ast
import logging
import traceback
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional

logger = logging.getLogger("bisync.hot_swap")

if TYPE_CHECKING:
    from manim.scene.scene import Scene
    from engine.state import EngineState


class HotSwapInjector:
    """Reloads Manim scenes by exec-ing new code in isolation.

    Instead of destroying and recreating the entire scene (which
    would require reinitializing the OpenGL context), we:
    1. Execute the new code to get fresh mobject parameters
    2. Apply those parameters to existing mobjects
    3. Trigger a re-render

    This preserves the GL context, FBO, and widget state.
    """

    def __init__(self, engine_state: EngineState) -> None:
        self._engine_state = engine_state
        self._scene_file: Optional[Path] = None
        self._current_scene: Optional[Scene] = None
        self._ast_mutator = None
        logger.info("HotSwapInjector initialized")

    def set_ast_mutator(self, mutator: Any) -> None:
        self._ast_mutator = mutator

    def set_scene(self, scene: Scene, scene_file: str | Path) -> None:
        """Register the active scene and its source file.

        Args:
            scene: The currently running Manim Scene
            scene_file: Path to the .py file containing the scene
        """
        self._current_scene = scene
        self._scene_file = Path(scene_file)
        logger.info(f"Hot-swap target: {self._scene_file.name}")

    def reload_from_file(self, file_path: str | Path | None = None) -> bool:
        """Reload the scene from a modified .py file.

        This is the main hot-swap entry point. Called when:
        - QFileSystemWatcher detects a file change
        - AST Mutator saves a modified file

        Flow:
            1. Read new source code
            2. exec() in isolated namespace
            3. Find the Scene class in the namespace
            4. Create temp scene, call construct()
            5. Extract new mobject params
            6. Apply to existing scene
            7. Trigger re-render

        Returns:
            True if reload succeeded
        """
        path = Path(file_path) if file_path else self._scene_file
        if path is None or self._current_scene is None:
            logger.error("No scene file or scene registered")
            return False

        try:
            # Step 1: Read new source
            source = path.read_text(encoding="utf-8")

            # Step 2: Compile and exec in isolated namespace
            code = compile(source, str(path), "exec")
            isolated_ns: dict[str, Any] = {}

            # Import manim into the namespace so Scene classes work
            exec("from manim import *", isolated_ns)
            exec(code, isolated_ns)

            # Step 3: Find the Scene class
            scene_class = None
            from manim import Scene as BaseScene
            for name, obj in isolated_ns.items():
                if (
                    isinstance(obj, type)
                    and issubclass(obj, BaseScene)
                    and obj is not BaseScene
                ):
                    scene_class = obj
                    break

            if scene_class is None:
                logger.error("No Scene subclass found in reloaded file")
                return False

            # Step 4: Create temp scene and construct
            # We create a temporary scene to extract new mobject parameters
            temp_scene = scene_class.__new__(scene_class)
            # Initialize minimal scene state for construct()
            temp_scene.mobjects = []
            temp_scene.animations = []

            # Manually call construct to populate mobjects
            try:
                # Patch self.add to capture mobjects
                added_mobjects = []
                original_add = None
                if hasattr(temp_scene, 'add'):
                    original_add = temp_scene.add

                def capture_add(*mobjects, **kwargs):
                    added_mobjects.extend(mobjects)

                temp_scene.add = capture_add
                temp_scene.construct()
            except Exception as e:
                logger.warning(f"Temp scene construct error: {e}")
                # Even if construct partially fails, we may have some mobjects

            # Step 5: Extract parameters and apply to existing scene
            if added_mobjects:
                self._apply_updates(added_mobjects)
                self._engine_state.scene_is_healthy = True
            else:
                logger.warning("No mobjects found in reloaded scene")
                self._engine_state.scene_is_healthy = False

            # Step 6: Trigger re-render
            self._engine_state.request_render()

            logger.info(
                f"Hot-swap complete: {path.name} "
                f"({len(added_mobjects)} mobjects updated)"
            )
            return True

        except Exception as e:
            logger.error(
                f"Hot-swap failed: {e}\n{traceback.format_exc()}"
            )
            return False

    def _apply_updates(self, new_mobjects: list) -> None:
        """Apply parameters from new mobjects to existing scene mobjects.

        Matches by _bisync_line_number to be robust against array shifts,
        falling back to class type and order for unmatched objects.
        """
        if self._current_scene is None:
            return

        existing = list(self._current_scene.mobjects)

        # Try matching by line number first (robust against reordering)
        unmatched_new = []
        matched_old_ids = set()

        for new_mob in new_mobjects:
            new_line = getattr(new_mob, '_bisync_line_number', None)
            matched = False

            if new_line is not None:
                for old_mob in existing:
                    if id(old_mob) in matched_old_ids:
                        continue
                    if getattr(old_mob, '_bisync_line_number', None) == new_line and type(old_mob) == type(new_mob):
                        self._copy_properties(old_mob, new_mob)
                        matched_old_ids.add(id(old_mob))
                        matched = True
                        break

            if not matched:
                unmatched_new.append(new_mob)

        # Fallback to type and index matching
        if unmatched_new:
            unmatched_old = [mob for mob in existing if id(mob) not in matched_old_ids]

            new_by_type: dict[str, list] = {}
            for mob in unmatched_new:
                new_by_type.setdefault(type(mob).__name__, []).append(mob)

            old_by_type: dict[str, list] = {}
            for mob in unmatched_old:
                old_by_type.setdefault(type(mob).__name__, []).append(mob)

            for cls_name, new_list in new_by_type.items():
                old_list = old_by_type.get(cls_name, [])
                for i, new_mob in enumerate(new_list):
                    if i < len(old_list):
                        self._copy_properties(old_list[i], new_mob)

    def _copy_properties(self, old_mob: Any, new_mob: Any) -> None:
        """Copy visual properties from new mobject to old mobject.

        Uses Manim's setter methods to update properties safely.
        Only copies properties that have actually changed.
        """
        try:
            # Copy position
            if hasattr(new_mob, 'get_center') and hasattr(old_mob, 'move_to'):
                new_center = new_mob.get_center()
                old_center = old_mob.get_center()
                if not all(abs(a - b) < 1e-6 for a, b in zip(new_center, old_center)):
                    old_mob.move_to(new_center)

            # Copy color
            if hasattr(new_mob, 'color') and hasattr(old_mob, 'set_color'):
                try:
                    if str(new_mob.color) != str(old_mob.color):
                        old_mob.set_color(new_mob.color)
                except Exception:
                    pass

            # Copy fill opacity
            if hasattr(new_mob, 'get_fill_opacity') and hasattr(old_mob, 'set_fill'):
                new_opacity = new_mob.get_fill_opacity()
                old_opacity = old_mob.get_fill_opacity()
                if abs(new_opacity - old_opacity) > 1e-6:
                    old_mob.set_fill(opacity=new_opacity)

            # Copy stroke opacity
            if hasattr(new_mob, 'get_stroke_opacity') and hasattr(old_mob, 'set_stroke'):
                new_opacity = new_mob.get_stroke_opacity()
                old_opacity = old_mob.get_stroke_opacity()
                if abs(new_opacity - old_opacity) > 1e-6:
                    old_mob.set_stroke(opacity=new_opacity)

            # Copy scale (via width comparison for shapes with width)
            if hasattr(new_mob, 'width') and hasattr(old_mob, 'width'):
                if old_mob.width > 0 and abs(new_mob.width - old_mob.width) > 1e-6:
                    scale_factor = new_mob.width / old_mob.width
                    old_mob.scale(scale_factor)

            # --- GENERIC REFLECTION FALLBACK ---
            for attr_name in dir(new_mob):
                if attr_name.startswith('_') or callable(getattr(new_mob, attr_name)):
                    continue
                if hasattr(old_mob, attr_name):
                    try:
                        new_val = getattr(new_mob, attr_name)
                        old_val = getattr(old_mob, attr_name)
                        if type(new_val) == type(old_val):
                            if type(new_val).__name__ == 'ndarray':
                                import numpy as np
                                if not np.array_equal(new_val, old_val):
                                    setattr(old_mob, attr_name, new_val)
                            elif new_val != old_val:
                                setattr(old_mob, attr_name, new_val)
                                logger.debug(f"Reflection copied {attr_name}={new_val}")
                    except Exception:
                        pass

        except Exception as e:
            logger.debug(f"Property copy error: {e}")

    def apply_transform(self, target_var: str, method_name: str, value: float) -> bool:
        """Apply a transform method (like scale) directly to the mobject.
        
        Since scale is relative in Manim, fast-path dragging is complex without 
        storing base state. For now, we rely on the slow path (AST reload) on release.
        """
        pass

    def apply_single_property(
        self,
        target_var: str,
        prop_name: str,
        new_value: Any,
    ) -> bool:
        """Apply a single property change to a scene mobject.

        Called directly by the property panel for immediate feedback
        WITHOUT going through file save → reload.

        This is the fast path for slider dragging:
        slider → apply_single_property → re-render (in-memory only)

        Args:
            target_var: Variable name (e.g., "circle")
            prop_name: Property name (e.g., "radius")
            new_value: New value to apply

        Returns:
            True if the property was applied
        """
        if self._current_scene is None:
            return False

        # Find the mobject by variable name convention
        # We look for mobjects that match the expected type/position
        for mob in self._current_scene.mobjects:
            if self._ast_mutator is not None:
                live_bind = self._ast_mutator.get_live_bind(id(mob))
                if live_bind and live_bind.variable_name == target_var:
                    return self._apply_property_to_mob(mob, prop_name, new_value)
                    
            mob_type = type(mob).__name__

            # Match by naming convention
            if target_var == "circle" and mob_type == "Circle":
                return self._apply_property_to_mob(mob, prop_name, new_value)
            elif target_var == "square" and mob_type == "Square":
                return self._apply_property_to_mob(mob, prop_name, new_value)
            elif target_var == "triangle" and mob_type == "Triangle":
                return self._apply_property_to_mob(mob, prop_name, new_value)
            elif target_var == "dot" and mob_type == "Dot":
                return self._apply_property_to_mob(mob, prop_name, new_value)
            elif target_var == "title" and mob_type == "Text":
                return self._apply_property_to_mob(mob, prop_name, new_value)

        logger.warning(f"Mobject not found for: {target_var}")
        return False

    def _apply_property_to_mob(
        self, mob: Any, prop_name: str, value: Any
    ) -> bool:
        """Apply a specific property to a mobject."""
        try:
            if prop_name == "radius" and hasattr(mob, 'width'):
                # Circle radius → scale to new radius
                current_radius = mob.width / 2.0
                if current_radius > 0 and abs(value - current_radius) > 1e-6:
                    mob.scale(value / current_radius)
                    logger.debug(f"Applied radius={value}")
                    return True

            elif prop_name == "side_length" and hasattr(mob, 'width'):
                current_side = mob.width
                if current_side > 0 and abs(value - current_side) > 1e-6:
                    mob.scale(value / current_side)
                    logger.debug(f"Applied side_length={value}")
                    return True

            elif prop_name == "fill_opacity":
                if hasattr(mob, 'set_fill'):
                    mob.set_fill(opacity=value)
                    logger.debug(f"Applied fill_opacity={value}")
                    return True

            elif prop_name == "stroke_width":
                if hasattr(mob, 'set_stroke'):
                    mob.set_stroke(width=value)
                    return True

            elif prop_name == "stroke_opacity":
                if hasattr(mob, 'set_stroke'):
                    mob.set_stroke(opacity=value)
                    return True

            elif prop_name == "color":
                return self._apply_color(mob, value)

            elif prop_name == "font_size":
                if hasattr(mob, 'font_size'):
                    mob.font_size = value
                    # In Manim, changing font_size on a rendered Text object is hard, 
                    # often requires re-creation. We'll try scaling as a fallback if it exists.
                    if hasattr(mob, 'scale'):
                        # This is a very rough hot-swap approach for font size
                        # Proper fix is full reload, but we try this for continuous drag
                        pass
                    return True
                    
            elif prop_name == "text":
                # Changing text requires full reload usually, but we can try to update it
                # if the mobject supports it, otherwise it'll just trigger a reload on release
                if hasattr(mob, 'text'):
                    mob.text = value
                    return True

            # --- GENERIC PROPERTY UPDATER VIA REFLECTION ---
            else:
                # If it's a color property (e.g., stroke_color, sheen_color), resolve it first
                if "color" in prop_name and isinstance(value, str):
                    resolved = self._resolve_color(value)
                    if resolved is not None:
                        value = resolved

                # First attempt: Manim setter method (e.g., set_stroke_color)
                setter_name = f"set_{prop_name}"
                if hasattr(mob, setter_name):
                    setter = getattr(mob, setter_name)
                    if callable(setter):
                        setter(value)
                        logger.debug(f"Applied generic {prop_name}={value} via {setter_name}()")
                        return True
                
                # Second attempt: Direct attribute setting (setattr)
                if hasattr(mob, prop_name):
                    setattr(mob, prop_name, value)
                    logger.debug(f"Applied generic {prop_name}={value} via setattr")
                    return True

        except Exception as e:
            logger.error(f"Apply property error: {e}")

        return False

    # ────────────────────────────────────────────────────────────
    # Color Resolution
    # ────────────────────────────────────────────────────────────

    # Known Manim color constants (name → import)
    _COLOR_MAP: dict[str, Any] = {}

    @classmethod
    def _resolve_color(cls, color_name: str) -> Any:
        """Convert a color name string (e.g., 'RED') to a Manim color.

        Lazily builds a lookup table from manim.constants.
        """
        if not cls._COLOR_MAP:
            import manim
            for name in dir(manim):
                obj = getattr(manim, name)
                # Manim colors are ManimColor instances or hex strings
                if isinstance(obj, str) and obj.startswith("#"):
                    cls._COLOR_MAP[name] = obj
                elif type(obj).__name__ == 'ManimColor' or hasattr(obj, 'to_hex'):  # ManimColor
                    cls._COLOR_MAP[name] = obj
            logger.debug(f"Color map built: {len(cls._COLOR_MAP)} entries")

        return cls._COLOR_MAP.get(color_name)

    def _apply_color(self, mob: Any, color_value: Any) -> bool:
        """Apply a color to a mobject.

        Handles both string names (from AST) and direct color objects.
        """
        try:
            if isinstance(color_value, str):
                # Resolve "RED" → manim.RED
                resolved = self._resolve_color(color_value)
                if resolved is None:
                    logger.warning(f"Unknown color: {color_value}")
                    return False
                color_value = resolved

            if hasattr(mob, 'set_color'):
                mob.set_color(color_value)
                logger.debug(f"Applied color={color_value}")
                return True
        except Exception as e:
            logger.error(f"Color apply error: {e}")
        return False

