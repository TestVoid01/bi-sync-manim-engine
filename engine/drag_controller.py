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

        logger.info("DragController initialized")

    def set_scene(self, scene: Any) -> None:
        """Set the active scene for mobject lookup."""
        self._scene = scene

    def on_mouse_press(self, px: int, py: int) -> bool:
        """Handle mouse press — test for hit and start drag.

        Args:
            px, py: Pixel coordinates of click

        Returns:
            True if an object was selected (drag started)
        """
        math_x, math_y = self._coord.pixel_to_math(px, py)
        
        anim_ref = self._engine_state.selected_animation

        if anim_ref is not None:
            # Phase 5: We are dragging an animation target (ghost)
            target_var = anim_ref.target_var
            
            # Find the original mobject to validate
            mob = None
            for m in self._scene.mobjects:
                if self._hit_tester.get_variable_name(m) == target_var:
                    mob = m
                    break
            
            if mob is None:
                return False

            self._dragging = True
            self._has_moved = False
            self._selected_mob = mob
            self._selected_var_name = target_var
            self._selected_mob_line_num = anim_ref.line_number
            self._engine_state.set_selected_mobject_name(target_var)
            
            # Fix Ghost Snap-to-Cursor Jump: Calculate offset based on animation target args
            try:
                if len(anim_ref.args) > 0 and isinstance(anim_ref.args[0], (list, tuple)):
                    target_pos = anim_ref.args[0]
                    self._drag_offset_x = math_x - float(target_pos[0])
                    self._drag_offset_y = math_y - float(target_pos[1])
                else:
                    self._drag_offset_x = 0.0
                    self._drag_offset_y = 0.0
            except Exception:
                self._drag_offset_x = 0.0
                self._drag_offset_y = 0.0
            
            if self._file_watcher:
                self._file_watcher.pause()
            
            self._drag_timer.start()
            logger.info(f"Drag started (Animation Target): {target_var}")
            return True

        # Hit-test against Socket 2 AABB hitboxes
        mob_id = self._hit_tester.test(math_x, math_y)
        if mob_id is None:
            self._engine_state.set_selected_mobject_name(None)
            return False

        # Find the actual mobject instance
        mob = self._hit_tester.find_mobject_by_id(mob_id, self._scene)
        if mob is None:
            return False

        # Get variable name and line number for AST updates
        ast_ref = self._hit_tester.get_ast_ref(mob)
        if ast_ref is None:
            logger.debug(f"No AST mapping for {type(mob).__name__}, skipping drag")
            return False

        var_name = ast_ref.variable_name
        line_num = ast_ref.line_number

        # Calculate drag offset (click position relative to object center)
        center = mob.get_center()
        self._drag_offset_x = math_x - float(center[0])
        self._drag_offset_y = math_y - float(center[1])

        # Enter DRAGGING state
        self._dragging = True
        self._has_moved = False
        self._selected_mob = mob
        self._selected_mob_id = mob_id
        self._selected_var_name = var_name
        self._selected_mob_line_num = line_num
        self._engine_state.set_selected_mobject_name(var_name)

        # Pause file watcher (Socket 5)
        if self._file_watcher:
            self._file_watcher.pause()

        # Start throttled update timer
        self._drag_timer.start()

        logger.info(
            f"Drag started: {var_name} (Line {line_num}) "
            f"at ({math_x:.2f}, {math_y:.2f})"
        )
        return True

    def on_mouse_move(self, px: int, py: int) -> None:
        """Handle mouse move during drag — store latest position.

        SPSC-style: Just overwrite _pending_pos. The 60Hz timer
        will pick up the latest position and apply it.
        No SSD writes here — purely in-memory.
        """
        if not self._dragging:
            return

        self._has_moved = True
        math_x, math_y = self._coord.pixel_to_math(px, py)

        # Apply drag offset for natural feel
        target_x = math_x - self._drag_offset_x
        target_y = math_y - self._drag_offset_y

        # SPSC overwrite — only latest position matters
        self._pending_pos = (target_x, target_y)

    def on_mouse_release(self, px: int, py: int) -> None:
        """Handle mouse release — save final position to AST.

        This is the only point where we touch the SSD.
        """
        if not self._dragging:
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
            self._pending_pos = None
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
                # Phase 4: Initial State update
                center = self._selected_mob.get_center()
                final_x = round(float(center[0]), 2)
                final_y = round(float(center[1]), 2)

                # Update AST: add/modify .shift() or .move_to() call
                self._update_ast_position(
                    self._selected_var_name, final_x, final_y, self._selected_mob_line_num
                )

                logger.info(
                    f"Drag complete: {self._selected_var_name} → "
                    f"({final_x}, {final_y})"
                )

        # Resume file watcher (Socket 5)
        if self._file_watcher:
            self._file_watcher.resume()

        # Clear drag state
        self._dragging = False
        self._has_moved = False
        self._selected_mob = None
        self._selected_mob_id = None
        self._selected_var_name = None
        self._selected_mob_line_num = None
        self._pending_pos = None

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
            anim_ref = self._engine_state.selected_animation
            
            if anim_ref is not None:
                # Phase 5: Update the ghost object's target arguments in memory
                # The canvas's paintGL will draw it using these updated arguments
                anim_ref.args = [[target_x, target_y, 0.0]]
            else:
                # Phase 4: Move the initial mobject in-memory
                import numpy as np
                self._selected_mob.move_to(
                    np.array([target_x, target_y, 0.0])
                )

            # Trigger re-render
            self._engine_state.request_render()

        except Exception as e:
            logger.error(f"Drag update error: {e}")

    def _update_ast_position(
        self, var_name: str, x: float, y: float, mob_line_num: Optional[int] = None
    ) -> None:
        """Update the AST with the final drag position.

        Strategy: We look for existing .shift() or .move_to() calls on the variable
        and update them. To handle duplicated variable names properly, we find the
        first move call that comes *after* the object's creation line.
        """
        import ast as ast_mod

        try:
            if self._ast_mutator._tree is None:
                return

            target_node = None
            for node in ast_mod.walk(self._ast_mutator._tree):
                if (
                    isinstance(node, ast_mod.Expr)
                    and isinstance(node.value, ast_mod.Call)
                    and isinstance(node.value.func, ast_mod.Attribute)
                    and node.value.func.attr in ("shift", "move_to")
                    and isinstance(node.value.func.value, ast_mod.Name)
                    and node.value.func.value.id == var_name
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
                import numpy as np
                target_node.value.func.attr = "move_to"
                target_node.value.args = [
                    ast_mod.List(
                        elts=[
                            ast_mod.Constant(value=x),
                            ast_mod.Constant(value=y),
                            ast_mod.Constant(value=0.0),
                        ],
                        ctx=ast_mod.Load(),
                    )
                ]
                target_node.value.keywords = []
                ast_mod.fix_missing_locations(self._ast_mutator._tree)
                logger.info(
                    f"AST Surgery: {var_name}.move_to([{x}, {y}, 0.0]) at line {target_node.lineno}"
                )
            elif mob_line_num is not None:
                # The object doesn't have an existing .move_to() or .shift()
                # We must inject a NEW .move_to() call right after its definition line.
                class MoveCallInjector(ast_mod.NodeTransformer):
                    def __init__(self, target, nx, ny, line):
                        self.target = target
                        self.nx = nx
                        self.ny = ny
                        self.line = line
                        self.injected = False

                    def insert_after(self, node_list):
                        new_list = []
                        for stmt in node_list:
                            new_list.append(stmt)
                            if not self.injected and getattr(stmt, 'lineno', -1) == self.line:
                                move_stmt = ast_mod.Expr(
                                    value=ast_mod.Call(
                                        func=ast_mod.Attribute(
                                            value=ast_mod.Name(id=self.target, ctx=ast_mod.Load()),
                                            attr='move_to',
                                            ctx=ast_mod.Load()
                                        ),
                                        args=[
                                            ast_mod.List(
                                                elts=[
                                                    ast_mod.Constant(value=self.nx),
                                                    ast_mod.Constant(value=self.ny),
                                                    ast_mod.Constant(value=0.0)
                                                ],
                                                ctx=ast_mod.Load()
                                            )
                                        ],
                                        keywords=[]
                                    )
                                )
                                ast_mod.copy_location(move_stmt, stmt)
                                new_list.append(move_stmt)
                                self.injected = True
                        return new_list

                    def generic_visit(self, node):
                        super().generic_visit(node)
                        for field, value in ast_mod.iter_fields(node):
                            if isinstance(value, list) and value and isinstance(value[0], ast_mod.stmt):
                                setattr(node, field, self.insert_after(value))
                        return node

                injector = MoveCallInjector(var_name, x, y, mob_line_num)
                self._ast_mutator._tree = injector.visit(self._ast_mutator._tree)
                ast_mod.fix_missing_locations(self._ast_mutator._tree)
                if injector.injected:
                    logger.info(f"AST Injection: Inserted {var_name}.move_to([{x}, {y}, 0.0]) after line {mob_line_num}")
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
    def selected_variable(self) -> Optional[str]:
        """Get the variable name of the currently selected object."""
        return self._selected_var_name
