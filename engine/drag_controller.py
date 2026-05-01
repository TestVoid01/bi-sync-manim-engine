"""
Bi-Sync Drag Controller — Mouse State Machine + Throttled Updates
==================================================================

Phase 4: Interactive Canvas Controller

Manages the complete mouse interaction lifecycle:
    1. Click → Hit-test → Select object
    2. Drag → Throttled position updates (in-memory only)
    3. Release → AST save (atomic write to disk)

SPSC-Style Throttle:
    Instead of a real C++ SPSC ring buffer, we use a simpler
    Python approach: only process the LATEST mouse position per
    frame tick (16ms). This achieves the same effect—hundreds of
    mouse events collapse into one update per frame.

SSD Debounce:
    During drag: in-memory mobject.move_to() only
    On release: AST Mutator saves to disk atomically
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Optional

from PyQt6.QtCore import QTimer

import numpy as np

logger = logging.getLogger("bisync.drag_controller")

if TYPE_CHECKING:
    from engine.ast_mutator import ASTMutator
    from engine.coordinate_transformer import CoordinateTransformer
    from engine.file_watcher import SceneFileWatcher
    from engine.hit_tester import HitTester
    from engine.state import EngineState


class DragController:
    """Manages mouse-driven object manipulation on the canvas.

    State machine:
        IDLE → (mouse press + hit) → DRAGGING → (mouse release) → IDLE

    During DRAGGING:
        - Mouse events update _pending_position (SPSC-style overwrite)
        - 60Hz timer reads _pending_position and applies to mobject
        - No SSD writes (file watcher paused)

    On release:
        - Final position written to AST
        - AST saved atomically to disk
        - File watcher resumed
    """

    DRAG_THRESHOLD_PX = 8

    def __init__(
        self,
        engine_state: EngineState,
        hit_tester: HitTester,
        coord_transformer: CoordinateTransformer,
        ast_mutator: ASTMutator,
        file_watcher: Optional[SceneFileWatcher] = None,
    ) -> None:
        self._engine_state = engine_state
        self._hit_tester = hit_tester
        self._coord = coord_transformer
        self._ast_mutator = ast_mutator
        self._file_watcher = file_watcher

        # State machine
        self._dragging: bool = False
        self._has_moved: bool = False
        self._selected_mob: Optional[Any] = None
        self._selected_mob_id: Optional[int] = None
        self._selected_var_name: Optional[str] = None
        self._selected_mob_line_num: Optional[int] = None
        self._selected_mob_path: list[int] = []
        self._press_candidate: Optional[dict[str, Any]] = None
        self._press_px: int = 0
        self._press_py: int = 0

        # SPSC-style: only store LATEST position
        self._pending_pos: Optional[tuple[float, float]] = None

        # Drag offset (where within the object the user clicked)
        self._drag_offset_x: float = 0.0
        self._drag_offset_y: float = 0.0

        # Scene reference (set by canvas)
        self._scene: Optional[Any] = None

        # 60Hz update timer for throttled drag updates
        self._drag_timer = QTimer()
        self._drag_timer.setInterval(16)  # ~60fps
        self._drag_timer.timeout.connect(self._process_pending_drag)

        self._animation_player = None

    def set_scene(self, scene: Any) -> None:
        """Set the active scene for mobject lookup."""
        self._scene = scene

    def set_animation_player(self, player) -> None:
        """Inject animation player for snapshot synchronization."""
        self._animation_player = player

    def _resolve_hit(self, mob_ids: list[int]) -> Optional[tuple[Any, Any, list[int], int]]:
        """Resolve the best hit from a list of hit mobject IDs, respecting isolation mode.
        Returns: (top_level_mob, hit_mob, path, hit_id) or None
        """
        if not mob_ids:
            return None

        best_result = None
        
        # If in isolation mode, prefer hits that are inside the isolated object's hierarchy
        isolated_key = getattr(self._engine_state, 'isolated_mobject_key', None)
        isolated_path = getattr(self._engine_state, 'isolated_mobject_path', [])
        isolated_depth = len(isolated_path)

        if isolated_key is not None:
            for mob_id in mob_ids:
                result = self._hit_tester.find_mobject_and_path(mob_id, self._scene)
                if result is None:
                    continue
                top_level_mob, hit_mob, path = result
                top_key = getattr(top_level_mob, '_bisync_line_number', id(top_level_mob))
                if top_key == isolated_key:
                    if path[:isolated_depth] == isolated_path:
                        return top_level_mob, hit_mob, path, mob_id

        # Fallback to the first (smallest area) hit
        for mob_id in mob_ids:
            result = self._hit_tester.find_mobject_and_path(mob_id, self._scene)
            if result is not None:
                top_level_mob, hit_mob, path = result
                return top_level_mob, hit_mob, path, mob_id
                
        return None

    def _call_hit_test(self, math_x: float, math_y: float):
        try:
            return self._hit_tester.test(math_x, math_y, self._scene)
        except TypeError:
            return self._hit_tester.test(math_x, math_y)

    def _hit_to_mobjects(self, hit) -> Optional[tuple[Any, Any, list[int], int, Optional[Any]]]:
        from engine.hit_tester import HitResult

        if isinstance(hit, HitResult):
            if hasattr(self._hit_tester, "resolve_hit_mobjects"):
                top, selected = self._hit_tester.resolve_hit_mobjects(hit, self._scene)
                return top, selected, list(hit.path), hit.selected_mobject_id, hit
            result = self._hit_tester.find_mobject_and_path(hit.selected_mobject_id, self._scene)
            if result is None:
                return None
            top, selected, path = result
            return top, selected, path, hit.selected_mobject_id, hit
        if isinstance(hit, list):
            resolved = self._resolve_hit(hit)
            if resolved is None:
                return None
            top, selected, path, mob_id = resolved
            return top, selected, path, mob_id, None
        if isinstance(hit, int):
            result = self._hit_tester.find_mobject_and_path(hit, self._scene)
            if result is None:
                return None
            top, selected, path = result
            return top, selected, path, hit, None
        return None

    def on_mouse_double_click(self, px: int, py: int) -> bool:
        """Handle mouse double click to toggle isolation mode."""
        math_x, math_y = self._coord.pixel_to_math(px, py)
        
        mob_ids = self._hit_tester.test(math_x, math_y)
        hit_result = self._resolve_hit(mob_ids)
        
        if hit_result is None:
            # Clicked empty space -> Exit isolation mode
            if self._engine_state.isolated_mobject_key is not None:
                self._engine_state.isolated_mobject_key = None
                self._engine_state.isolated_mobject_path = []
                self._engine_state.request_render()
                logger.info("Exited isolation mode.")
            return False
            
        top_level_mob, hit_mob, path, mob_id = hit_result
        top_key = getattr(top_level_mob, '_bisync_line_number', id(top_level_mob))
        
        # Enter isolation mode for the top-level parent if not already isolated
        if self._engine_state.isolated_mobject_key != top_key:
            self._engine_state.isolated_mobject_key = top_key
            self._engine_state.isolated_mobject_path = []
            logger.info(f"Entered isolation mode for mobject {top_key}")
        else:
            # Already isolated, drill down one level deeper
            isolated_depth = len(self._engine_state.isolated_mobject_path)
            if path[:isolated_depth] == self._engine_state.isolated_mobject_path and len(path) > isolated_depth:
                self._engine_state.isolated_mobject_path = path[:isolated_depth + 1]
                logger.info(f"Drilled down to path {self._engine_state.isolated_mobject_path} in isolated mobject")
            
        self._engine_state.request_render()
        return True

    def on_mouse_press(self, px: int, py: int) -> bool:
        """Handle mouse press — hit-test and select only.

        Args:
            px, py: Pixel coordinates of click

        Returns:
            True if an object was selected (drag started)
        """
        math_x, math_y = self._coord.pixel_to_math(px, py)
        
        anim_ref = self._engine_state.selected_animation
        if anim_ref is not None:
            # Ghost drag mode is fully disabled to prevent the "duplicate object" user confusion.
            # We instantly deselect the animation and fall through to normal object dragging.
            self._engine_state.selected_animation = None
            anim_ref = None

        hit = self._call_hit_test(math_x, math_y)
        hit_result = self._hit_to_mobjects(hit)
        
        if hit_result is None:
            self._engine_state.set_selected_object(None)
            self._engine_state.set_selected_mobject_name(None)
            self._press_candidate = None
            return False

        top_level_mob, hit_mob, path, mob_id, structured_hit = hit_result

        # Determine which mobject to actually select based on isolation mode
        top_key = getattr(top_level_mob, '_bisync_line_number', id(top_level_mob))
        
        if self._engine_state.isolated_mobject_key == top_key:
            # We are in isolation mode for this object. Select the child that is ONE level deeper than the current isolation depth.
            isolated_depth = len(self._engine_state.isolated_mobject_path)
            
            if path[:isolated_depth] == self._engine_state.isolated_mobject_path:
                if len(path) > isolated_depth:
                    target_depth = isolated_depth + 1
                    selected_path = path[:target_depth]
                    
                    # Traverse down to the target depth
                    mob = top_level_mob
                    for idx in selected_path:
                        mob = mob.submobjects[idx]
                else:
                    mob = hit_mob
                    selected_path = path
            else:
                # Outside isolated path but inside top_level_mob
                mob = top_level_mob
                selected_path = []
        else:
            # Normal mode: select the top-level object
            mob = top_level_mob
            selected_path = []

        # Get variable name and line number for AST updates.
        # Do not block selection if source provenance is missing:
        # users should still be able to select/drag in live preview.
        ast_ref = self._hit_tester.get_ast_ref(top_level_mob)
        if ast_ref is not None:
            var_name = ast_ref.variable_name
            line_num = ast_ref.line_number
        else:
            live_ref = self._ast_mutator.get_live_bind(id(top_level_mob))
            if live_ref is None and mob is not top_level_mob:
                live_ref = self._ast_mutator.get_live_bind(id(mob))
            var_name = live_ref.variable_name if live_ref is not None else None
            line_num = live_ref.line_number if live_ref is not None else None

        # Calculate drag offset (click position relative to object center)
        center = np.array(mob.get_center(), dtype=np.float64)
        self._drag_offset_x = float(np.float64(math_x) - center[0])
        self._drag_offset_y = float(np.float64(math_y) - center[1])

        # Arm a drag candidate only. The file watcher and AST remain untouched
        # until movement crosses DRAG_THRESHOLD_PX.
        self._dragging = False
        self._has_moved = False
        self._press_px = px
        self._press_py = py
        self._press_candidate = {
            "mob": mob,
            "mob_id": mob_id,
            "var_name": var_name,
            "line_num": line_num,
            "path": selected_path,
            "offset_x": self._drag_offset_x,
            "offset_y": self._drag_offset_y,
        }
        
        # Display name could show path, e.g. axes[0][1].
        # Fall back to runtime type for objects without source binding.
        base_name = var_name or type(mob).__name__
        display_name = base_name + "".join(f"[{i}]" for i in selected_path)
        selection = None
        object_registry = getattr(self._engine_state, "object_registry", None)
        if object_registry is not None:
            selection = object_registry.create_selection(
                top_level_mobject_id=id(top_level_mob),
                selected_mobject_id=id(mob),
                path=tuple(selected_path),
            )
        if structured_hit is not None and selection is None:
            from engine.object_registry import SelectionRef
            selection = SelectionRef(
                mobject_id=structured_hit.selected_mobject_id,
                top_level_id=structured_hit.top_level_mobject_id,
                variable_name=structured_hit.variable_name or display_name,
                line_number=structured_hit.line_number,
                constructor_name=structured_hit.constructor_name or type(mob).__name__,
                source_key=structured_hit.source_key,
                editability=structured_hit.editability,
                read_only_reason=structured_hit.read_only_reason,
                path=tuple(structured_hit.path),
                display_name=structured_hit.display_name or display_name,
            )
        if selection is not None:
            self._engine_state.set_selected_object(selection)
        else:
            self._engine_state.set_selected_mobject_name(display_name)

        logger.info(
            f"Selection armed: {display_name} (Line {line_num}) "
            f"at ({math_x:.2f}, {math_y:.2f})"
        )
        return True

    def on_mouse_move(self, px: int, py: int) -> None:
        """Handle mouse move during drag — store latest position.

        SPSC-style: Just overwrite _pending_pos. The 60Hz timer
        will pick up the latest position and apply it.
        No SSD writes here — purely in-memory.
        """
        if not self._dragging and self._press_candidate is not None:
            dx = px - self._press_px
            dy = py - self._press_py
            if (dx * dx + dy * dy) ** 0.5 < self.DRAG_THRESHOLD_PX:
                return
            candidate = self._press_candidate
            self._selected_mob = candidate["mob"]
            self._selected_mob_id = candidate["mob_id"]
            self._selected_var_name = candidate["var_name"]
            self._selected_mob_line_num = candidate["line_num"]
            self._selected_mob_path = list(candidate["path"])
            self._drag_offset_x = candidate["offset_x"]
            self._drag_offset_y = candidate["offset_y"]
            self._dragging = True
            if self._file_watcher:
                self._file_watcher.pause()
            self._drag_timer.start()
            logger.info("Drag started: %s", self._selected_var_name)

        if not self._dragging:
            return

        self._has_moved = True
        math_x, math_y = self._coord.pixel_to_math(px, py)

        # Apply drag offset for natural feel
        target_x = math_x - self._drag_offset_x
        target_y = math_y - self._drag_offset_y

        # SPSC overwrite — only latest position matters
        self._pending_pos = (target_x, target_y)

    def on_mouse_release(self, px: Optional[int] = None, py: Optional[int] = None) -> None:
        """Handle mouse release — save final position to AST.

        This is the only point where we touch the SSD.
        """
        if getattr(self._engine_state, 'is_external_reload_pending', False):
            logger.warning("Drag save aborted: External file edit detected.")
            self._dragging = False
            self._has_moved = False
            self._selected_mob = None
            self._selected_mob_id = None
            self._selected_var_name = None
            self._selected_mob_line_num = None
            self._selected_mob_path = []
            self._pending_pos = None
            if self._file_watcher:
                self._file_watcher.resume()
            return

        if not self._dragging:
            self._press_candidate = None
            return

        # Stop the throttled update timer
        self._drag_timer.stop()

        # Fix Destructive Overwrites: if user just clicked without dragging, don't modify AST
        if not getattr(self, '_has_moved', False):
            self._dragging = False
            self._selected_mob = None
            self._selected_mob_id = None
            self._selected_var_name = None
            self._selected_mob_line_num = None
            self._selected_mob_path = []
            self._pending_pos = None
            self._press_candidate = None
            if self._file_watcher:
                self._file_watcher.resume()
            return

        # Process any remaining pending position
        self._process_pending_drag()

        # Get final position for AST update
        if self._selected_mob is not None and self._selected_var_name is not None:
            anim_ref = self._engine_state.selected_animation
            
            if anim_ref is not None:
                # Phase 5: Update animation target in AST
                # The _process_pending_drag updated anim_ref.args in memory
                # Now save to AST
                try:
                    # Get the current dragged position from the anim_ref args
                    pos = anim_ref.args[0]
                    final_x = round(float(pos[0]), 2)
                    final_y = round(float(pos[1]), 2)
                    
                    if self._ast_mutator.update_animation_target(
                        target_var=anim_ref.target_var,
                        method_name=anim_ref.method_name,
                        x=final_x,
                        y=final_y,
                        line_number=anim_ref.line_number,
                    ):
                        self._ast_mutator.save_atomic()
                    
                    logger.info(
                        f"Animation drag complete: {anim_ref.target_var} → "
                        f"({final_x}, {final_y})"
                    )
                except Exception as e:
                    logger.error(f"Failed to update animation target: {e}")
            else:
                # Phase 4/6: Initial State update
                center = self._selected_mob.get_center()
                final_x = round(float(center[0]), 2)
                final_y = round(float(center[1]), 2)

                # Update AST: add/modify .shift() or .move_to() call
                self._update_ast_position(
                    self._selected_var_name,
                    final_x,
                    final_y,
                    self._selected_mob_line_num,
                    self._selected_mob_path,
                    source_key=getattr(getattr(self._engine_state, "selected_object", None), "source_key", None),
                )

                display_name = self._selected_var_name + "".join(f"[{i}]" for i in self._selected_mob_path)
                logger.info(
                    f"Drag complete: {display_name} → "
                    f"({final_x}, {final_y})"
                )

        # Resume file watcher (Socket 5)
        if self._file_watcher:
            # Notify that this was our own save, not an external edit.
            # This clears is_external_reload_pending and sets suppression
            # so the file watcher doesn't treat our save as external.
            notify = getattr(self._file_watcher, "notify_internal_commit", None)
            if callable(notify):
                notify()
            self._file_watcher.resume()

        # Clear drag state
        self._dragging = False
        self._has_moved = False
        self._selected_mob = None
        self._selected_mob_id = None
        self._selected_var_name = None
        self._selected_mob_line_num = None
        self._selected_mob_path = []
        self._pending_pos = None
        self._press_candidate = None

    def _process_pending_drag(self) -> None:
        """60Hz timer callback: Apply pending position to mobject.

        This is the SPSC consumer — picks up the latest position
        and moves the mobject. Only runs in-memory, no SSD writes.
        """
        if self._pending_pos is None or self._selected_mob is None:
            return

        target_x, target_y = self._pending_pos
        self._pending_pos = None  # Consumed

        try:
            # Move the actual mobject in-memory
            self._selected_mob.move_to(
                np.array([target_x, target_y, 0.0])
            )
            
            if self._animation_player is not None:
                # Keep all snapshots visually synced so play/pause doesn't snap back
                def _update_points(copied_mob):
                    copied_mob.move_to(np.array([target_x, target_y, 0.0]))
                self._animation_player.update_snapshot(self._selected_mob, _update_points)

            # Trigger re-render
            self._engine_state.request_render()

        except Exception as e:
            logger.error(f"Drag update error: {e}")

    def _update_ast_position(
        self,
        var_name: str,
        x: float,
        y: float,
        mob_line_num: Optional[int] = None,
        path: list[int] = None,
        *,
        source_key: Optional[str] = None,
    ) -> None:
        """Update the AST with the final drag position.

        Strategy: We look for existing .shift() or .move_to() calls on the variable
        and update them. To handle duplicated variable names properly, we find the
        first move call that comes *after* the object's creation line.
        """
        import ast as ast_mod

        if path is None:
            path = []

        try:
            if hasattr(self._ast_mutator, "plan_position_persistence"):
                strategy = self._ast_mutator.plan_position_persistence(
                    var_name,
                    source_key=source_key,
                    path=tuple(path),
                )
                if getattr(strategy, "no_persist", False):
                    logger.info("Skipped position persist for %s: %s", var_name, strategy.reason)
                    self._engine_state.record_preview_drift(
                        f"{var_name} position drag: {strategy.reason}"
                    )
                    return
                if mob_line_num is None and getattr(strategy, "source_key", None):
                    ref = self._ast_mutator.get_binding_by_source_key(strategy.source_key)
                    if ref is not None:
                        mob_line_num = ref.line_number

            if mob_line_num is None and hasattr(self._ast_mutator, "get_binding_by_name"):
                ref = self._ast_mutator.get_binding_by_name(var_name)
                if ref is not None:
                    mob_line_num = ref.line_number

            if getattr(self._ast_mutator, "_file_path", None):
                try:
                    self._ast_mutator.parse_file(self._ast_mutator._file_path)
                except Exception as e:
                    logger.error(f"Failed to re-parse before drag update: {e}")
                    return

            if getattr(self._ast_mutator, "_tree", None) is None:
                return

            target_node = None
            
            # Helper to check if a node represents var_name[path[0]]...
            def matches_target(node):
                if not path:
                    return isinstance(node, ast_mod.Name) and node.id == var_name
                # Need to match Subscript nodes
                current = node
                for index in reversed(path):
                    if not isinstance(current, ast_mod.Subscript):
                        return False
                    if not isinstance(current.slice, ast_mod.Constant) or current.slice.value != index:
                        return False
                    current = current.value
                return isinstance(current, ast_mod.Name) and current.id == var_name

            for node in ast_mod.walk(self._ast_mutator._tree):
                if (
                    isinstance(node, ast_mod.Expr)
                    and isinstance(node.value, ast_mod.Call)
                    and isinstance(node.value.func, ast_mod.Attribute)
                    and node.value.func.attr in ("shift", "move_to")
                    and matches_target(node.value.func.value)
                ):
                    node_line = getattr(node, 'lineno', -1)
                    if mob_line_num is not None and node_line >= mob_line_num:
                        if target_node is None or node_line < target_node.lineno:
                            target_node = node
                    elif mob_line_num is None:
                        # Fallback if line num isn't provided (legacy safety)
                        target_node = node
                        break

            if target_node:
                target_node.value.func.attr = "move_to"
                
                new_list_node = ast_mod.List(
                    elts=[
                        ast_mod.Constant(value=x),
                        ast_mod.Constant(value=y),
                        ast_mod.Constant(value=0.0),
                    ],
                    ctx=ast_mod.Load(),
                )
                
                if target_node.value.args:
                    existing_arg = target_node.value.args[0]
                    if isinstance(existing_arg, (ast_mod.List, ast_mod.Tuple)):
                        target_node.value.args[0] = new_list_node
                    elif isinstance(existing_arg, ast_mod.IfExp) and getattr(existing_arg.test, "value", False) is True:
                        existing_arg.body = new_list_node
                    else:
                        target_node.value.args[0] = ast_mod.IfExp(
                            test=ast_mod.Constant(value=True),
                            body=new_list_node,
                            orelse=existing_arg
                        )
                else:
                    target_node.value.args = [new_list_node]
                    
                target_node.value.keywords = []
                ast_mod.fix_missing_locations(self._ast_mutator._tree)
                
                path_str = "".join(f"[{i}]" for i in path)
                logger.info(
                    f"AST Surgery: {var_name}{path_str}.move_to([{x}, {y}, 0.0]) at line {target_node.lineno}"
                )
            elif mob_line_num is not None:
                # The object doesn't have an existing .move_to() or .shift()
                # We must inject a NEW .move_to() call right after its definition line.
                class MoveCallInjector(ast_mod.NodeTransformer):
                    def __init__(self, target, path_indices, nx, ny, line):
                        self.target = target
                        self.path_indices = path_indices
                        self.nx = nx
                        self.ny = ny
                        self.line = line
                        self.injected = False
                        
                    def _build_target_node(self):
                        node = ast_mod.Name(id=self.target, ctx=ast_mod.Load())
                        for index in self.path_indices:
                            node = ast_mod.Subscript(
                                value=node,
                                slice=ast_mod.Constant(value=index),
                                ctx=ast_mod.Load()
                            )
                        return node

                    def _insert_or_update(self, node_list):
                        new_list = []
                        target_expr_code = ast_mod.unparse(self._build_target_node())
                        
                        # Find the index of the last existing move/transform to handle overrides
                        last_move_idx = -1
                        last_transform_idx = -1
                        
                        for i, stmt in enumerate(node_list):
                            if isinstance(stmt, ast_mod.Expr) and isinstance(stmt.value, ast_mod.Call) and isinstance(stmt.value.func, ast_mod.Attribute):
                                try:
                                    root = stmt.value.func.value
                                    while isinstance(root, ast_mod.Attribute): root = root.value
                                    
                                    matches = False
                                    if isinstance(root, ast_mod.Name) and root.id == self.target: matches = True
                                    elif isinstance(root, ast_mod.Attribute) and root.attr == self.target: matches = True
                                    
                                    if matches:
                                        if stmt.value.func.attr in ("move_to", "shift"):
                                            last_move_idx = i
                                        last_transform_idx = i
                                except: pass

                        for i, stmt in enumerate(node_list):
                            if not self.injected and i == last_move_idx:
                                # Update existing move_to
                                stmt.value.func.attr = "move_to"
                                new_arg = ast_mod.List(
                                    elts=[ast_mod.Constant(value=self.nx), ast_mod.Constant(value=self.ny), ast_mod.Constant(value=0.0)],
                                    ctx=ast_mod.Load()
                                )
                                if stmt.value.args: stmt.value.args[0] = new_arg
                                else: stmt.value.args.append(new_arg)
                                new_list.append(stmt)
                                self.injected = True
                                logger.info(f"AST Surgery: Updated existing movement for {self.target}")
                                continue

                            new_list.append(stmt)
                            
                            # Injection: If no move exists, inject after the LAST transform or creation line
                            if not self.injected:
                                # Prioritize injecting after the last transform (rotate/scale)
                                if last_move_idx == -1 and i == last_transform_idx:
                                    move_stmt = self._create_move_stmt()
                                    new_list.append(move_stmt)
                                    self.injected = True
                                # Fallback: inject after creation
                                elif last_transform_idx == -1 and getattr(stmt, 'lineno', -1) == self.line:
                                    move_stmt = self._create_move_stmt()
                                    new_list.append(move_stmt)
                                    self.injected = True
                        return new_list

                    def _create_move_stmt(self):
                        stmt = ast_mod.Expr(
                            value=ast_mod.Call(
                                func=ast_mod.Attribute(value=self._build_target_node(), attr='move_to', ctx=ast_mod.Load()),
                                args=[ast_mod.List(elts=[ast_mod.Constant(value=self.nx), ast_mod.Constant(value=self.ny), ast_mod.Constant(value=0.0)], ctx=ast_mod.Load())],
                                keywords=[]
                            )
                        )
                        self.injected = True
                        return stmt

                    def generic_visit(self, node):
                        super().generic_visit(node)
                        for field, value in ast_mod.iter_fields(node):
                            if isinstance(value, list) and value and isinstance(value[0], ast_mod.stmt):
                                setattr(node, field, self._insert_or_update(value))
                        return node

                injector = MoveCallInjector(var_name, path, x, y, mob_line_num)
                self._ast_mutator._tree = injector.visit(self._ast_mutator._tree)
                ast_mod.fix_missing_locations(self._ast_mutator._tree)
                path_str = "".join(f"[{i}]" for i in path)
                if injector.injected:
                    logger.info(f"AST Injection: Inserted {var_name}{path_str}.move_to([{x}, {y}, 0.0]) after line {mob_line_num}")
                else:
                    logger.warning(f"AST Injection failed: Could not find insertion point after line {mob_line_num}")
            
            # Save atomically
            self._ast_mutator.save_atomic()

        except Exception as e:
            logger.error(f"AST position update failed: {e}")

    @property
    def is_dragging(self) -> bool:
        """Check if a drag is currently in progress."""
        return self._dragging

    @property
    def has_pending_drag_candidate(self) -> bool:
        return self._press_candidate is not None and not self._dragging

    @property
    def selected_variable(self) -> Optional[str]:
        """Get the variable name of the currently selected object."""
        return self._selected_var_name

    def commit_active_drag(self) -> bool:
        """Finalize any active drag before export.

        Returns:
            True when no drag is active or commit succeeds.
        """
        if not self._dragging:
            return True
        try:
            self.on_mouse_release()
            return not self._dragging
        except Exception as e:
            logger.error(f"Failed to commit active drag: {e}")
            return False
