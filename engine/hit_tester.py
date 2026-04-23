"""
Bi-Sync Hit Tester — AABB Object Selection
=============================================

Phase 4: Interactive Canvas Controller

Tests mouse click coordinates against Socket 2's AABB hitbox
registry to identify which Manim Mobject was clicked.

Uses Axis-Aligned Bounding Box (AABB) comparison — much faster
than mesh ray-casting. O(N) loop terminates on first hit.

The hitboxes are populated by HijackedRenderer.render_mobject()
every frame, so they're always up-to-date.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Optional

logger = logging.getLogger("bisync.hit_tester")

if TYPE_CHECKING:
    from engine.state import EngineState
    from engine.ast_mutator import ASTMutator, ASTNodeRef


class HitTester:
    """Tests math coordinates against AABB hitboxes for object selection.

    Uses Socket 2's hitbox registry (populated each frame by the renderer).

    Hit-test priority:
        - Smallest bounding box wins (most specific object)
        - This handles overlapping objects correctly
    """

    def __init__(self, engine_state: EngineState, ast_mutator: ASTMutator) -> None:
        self._engine_state = engine_state
        self._ast_mutator = ast_mutator
        logger.info("HitTester initialized")

    def test(self, math_x: float, math_y: float) -> Optional[int]:
        """Test a math coordinate against all hitboxes.

        Args:
            math_x: X in Manim math coordinates
            math_y: Y in Manim math coordinates

        Returns:
            mobject_id (Python id()) of the hit object, or None
        """
        hitboxes = self._engine_state.get_hitboxes()
        if not hitboxes:
            return None

        best_id: Optional[int] = None
        best_area: float = float("inf")

        for mob_id, (min_x, min_y, max_x, max_y) in hitboxes.items():
            # AABB containment test
            if min_x <= math_x <= max_x and min_y <= math_y <= max_y:
                # Prefer smallest bounding box (most specific object)
                area = (max_x - min_x) * (max_y - min_y)
                if area < best_area:
                    best_area = area
                    best_id = mob_id

        if best_id is not None:
            logger.debug(
                f"Hit: mobject {best_id} at ({math_x:.2f}, {math_y:.2f})"
            )

        return best_id

    def find_mobject_by_id(self, mobject_id: int, scene: Any) -> Optional[Any]:
        """Find the actual Mobject instance from its Python id().

        Args:
            mobject_id: Python id() of the target mobject
            scene: The Manim Scene containing mobjects

        Returns:
            The Mobject instance, or None
        """
        if scene is None:
            return None

        for mob in scene.mobjects:
            if id(mob) == mobject_id:
                return mob
            # Also check submobjects
            if hasattr(mob, 'submobjects'):
                for sub in mob.submobjects:
                    if id(sub) == mobject_id:
                        return sub

        return None

    def get_ast_ref(self, mobject: Any) -> Optional[ASTNodeRef]:
        if not hasattr(mobject, "_bisync_line_number"):
            logger.debug(f"mobject {type(mobject).__name__} has no _bisync_line_number")
            return None
            
        line_num = mobject._bisync_line_number
        ref = self._ast_mutator.bindings.get(line_num)
        if ref is None:
            logger.debug(f"Line {line_num} not found in bindings dict. Keys: {list(self._ast_mutator.bindings.keys())}")
        return ref

    def get_variable_name(self, mobject: Any) -> Optional[str]:
        """Legacy helper for getting just the variable name.

        Also registers the live bind so Socket 4 architecture is complete.
        """
        ref = self.get_ast_ref(mobject)
        if ref:
            # Wire up Socket 4: register live bind for mobject→code
            self._ast_mutator.register_live_bind(id(mobject), ref.variable_name)
            return ref.variable_name
        return None
