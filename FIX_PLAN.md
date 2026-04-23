# Bi-Sync Manim Engine — Fix Plan

**Date:** 2026-04-23
**Based on:** PROBLEM.md

---

## Priority Order

### Tier 1 — Critical (Fix First)
1. Problem 5: `flush_writes()` is a No-Op
2. Problem 10: `register_live_bind()` never called
3. Problem 2: PropertyUpdater replaces expressions
4. Problem 4: Animation detection limited pattern

### Tier 2 — High Impact
5. Problem 3: bindings dict indexed by line number
6. Problem 7: HitTester import in mouseMoveEvent
7. Problem 9: Ghost rendering hardcoded types
8. Problem 8: `_copy_properties` limited props

### Tier 3 — Medium Impact
9. Problem 6: `scene_is_healthy` inconsistency
10. Problem 12: Timeline scrub animation index mismatch
11. Problem 13: No cleanup on scene reload
12. Problem 14: OpenGL/Cairo config inconsistency

### Tier 4 — Low Impact / Future
13. Problem 11: PropertyFinder generic_visit redundancy
14. Problem 15: earcut patch not comprehensive
15. Problem 1: Python 3.9.6 outdated

---

## Tier 1: Critical Fixes

---

### Fix 1.1: Problem 5 — `flush_writes()` is a No-Op

**File:** `engine/state.py`

**Root Cause:** The method was left as a stub with "Phase 2 will implement" comment, but Phase 2 never implemented it here. The actual atomic write lives in `ASTMutator.save_atomic()`.

**Solution:** Remove `flush_writes()` from `EngineState` entirely. The debounce architecture should be simpler:
- `EngineState.queue_write()` queues AST trees
- `ASTMutator.save_atomic()` handles the actual write
- No need for `flush_writes()` in `EngineState`

**Changes:**

```python
# In state.py — REMOVE flush_writes() and related infrastructure:
# Remove: _pending_writes dict
# Remove: flush_writes() method
# Remove: queue_write() method
```

**Alternative (if keeping debounce):** Implement `flush_writes()` properly:
```python
def flush_writes(self) -> None:
    if not self._pending_writes:
        return
    for path, tree in self._pending_writes.items():
        try:
            new_source = ast.unparse(tree)
            # atomic write...
        except Exception as e:
            logger.error(f"flush_writes failed: {e}")
    self._pending_writes.clear()
```

**Recommendation:** Remove the infrastructure entirely. The debounce should live in `DragController` or `ASTMutator`, not split across two classes.

---

### Fix 1.2: Problem 10 — `register_live_bind()` Never Called

**Files:** `engine/ast_mutator.py`, `engine/hit_tester.py`, `engine/drag_controller.py`

**Root Cause:** The Socket 4 architecture was designed but never wired up. HitTester never calls `register_live_bind()` when it resolves a mobject ID to a variable name.

**Solution:** Wire up `register_live_bind()` in `HitTester.get_variable_name()`:

**Changes in `engine/hit_tester.py`:**

```python
# In HitTester.get_variable_name() — after resolving variable name:
if found:
    self._ast_mutator.register_live_bind(mobject_id, var_name)
    return var_name
```

**Also:** Clear `_live_binds` when scene reloads (Problem 13).

---

### Fix 1.3: Problem 2 — PropertyUpdater Replaces Expressions

**File:** `engine/ast_mutator.py` — `PropertyUpdater.visit_Assign`

**Root Cause:** Always replaces `kw.value` with `ast.Constant()`, losing expressions like `1.5 + 0.5`.

**Solution:** Check if existing value is a simple constant before replacing:

```python
def visit_Assign(self, node: ast.Assign) -> ast.Assign:
    if (
        len(node.targets) == 1
        and isinstance(node.targets[0], ast.Name)
        and node.targets[0].id == self._target_var
        and isinstance(node.value, ast.Call)
    ):
        for kw in node.value.keywords:
            if kw.arg == self._prop_name:
                # Only replace if existing value is a simple constant
                existing = kw.value
                if isinstance(existing, ast.Constant):
                    # Safe to replace constant
                    kw.value = ast.Constant(value=self._new_value)
                    self._modified = True
                else:
                    # Complex expression — log and skip
                    logger.warning(
                        f"Skipping {self._target_var}.{self._prop_name}: "
                        f"existing value is complex expression, not a constant"
                    )
    return node
```

---

### Fix 1.4: Problem 4 — Animation Detection Limited Pattern

**File:** `engine/ast_mutator.py` — `PropertyFinder.visit_Call`

**Root Cause:** Only matches `self.play(obj.animate.method())`. Misses `Create()`, `FadeIn()`, `wait()`, etc.

**Solution:** Expand `visit_Call` to handle multiple patterns:

```python
def visit_Call(self, node: ast.Call) -> None:
    """Visit call nodes to find animations."""
    func_name = self._get_func_name(node.func)

    # Pattern 1: self.play(obj.animate.method(...))
    if func_name == "play":
        for arg in node.args:
            self._extract_animation_from_play_arg(arg)

    # Pattern 2: self.wait(duration)
    elif func_name == "wait":
        if node.args:
            duration = self._extract_value(node.args[0])
            ref = ASTAnimationRef(
                target_var="__scene__",
                method_name="wait",
                args=[duration] if duration else [1.0],
                line_number=node.lineno,
                col_offset=node.col_offset,
            )
            self.animations.append(ref)

    self.generic_visit(node)

def _extract_animation_from_play_arg(self, arg) -> None:
    """Extract animation from a single argument to self.play()."""
    # Pattern: obj.animate.method(...)
    if isinstance(arg, ast.Call) and isinstance(arg.func, ast.Attribute):
        if arg.func.attr == "animate" and isinstance(arg.func.value, ast.Attribute):
            if isinstance(arg.func.value.value, ast.Name):
                target_var = arg.func.value.value.id
                method_name = arg.func.attr  # This is "animate" — get next
                # Actually for .animate.method(), the method is on the outer Attribute
                # Let me reconsider...

    # Pattern: Create(circle), FadeIn(circle), etc.
    if isinstance(arg, ast.Call) and isinstance(arg.func, ast.Name):
        func_name = arg.func.id
        if func_name in {"Create", "FadeIn", "FadeOut", "Grow", "Shrink",
                          "Rotate", "Scale", "MoveTo", "Shift"}:
            # Extract target from args
            target = arg.args[0] if arg.args else None
            if isinstance(target, ast.Name):
                ref = ASTAnimationRef(
                    target_var=target.id,
                    method_name=func_name.lower(),  # convention
                    args=[self._extract_value(a) for a in arg.args[1:]],
                    line_number=arg.lineno,
                    col_offset=arg.col_offset,
                )
                self.animations.append(ref)
```

**Note:** This needs careful AST structure analysis. The `.animate` pattern requires walking through `ast.Attribute` chain properly.

---

## Tier 2: High Impact Fixes

---

### Fix 2.1: Problem 3 — bindings Dict Indexed by Line Number

**File:** `engine/ast_mutator.py`

**Root Cause:** `bindings` uses `lineno` as key, forcing O(N) lookups.

**Solution:** Add a secondary index:

```python
@dataclass
class ASTMutator:
    def __init__(self) -> None:
        self._tree: Optional[ast.Module] = None
        self._source: Optional[str] = None
        self._file_path: Optional[Path] = None
        # Primary index: line_number → ASTNodeRef
        self._bindings: dict[int, ASTNodeRef] = {}
        # Secondary index: variable_name → ASTNodeRef (O(1) lookup)
        self._bindings_by_name: dict[str, ASTNodeRef] = {}
        self._animations: list[ASTAnimationRef] = []
        self._live_binds: dict[int, ASTNodeRef] = {}

    @property
    def bindings(self) -> dict[int, ASTNodeRef]:
        return self._bindings

    def parse_file(self, path: str | Path) -> dict[int, ASTNodeRef]:
        ...
        finder = PropertyFinder()
        finder.visit(self._tree)
        self._bindings = finder.bindings
        # Build name index
        self._bindings_by_name = {ref.variable_name: ref for ref in self._bindings.values()}
        self._animations = finder.animations
        ...

    def get_binding_by_name(self, var_name: str) -> Optional[ASTNodeRef]:
        """O(1) lookup by variable name."""
        return self._bindings_by_name.get(var_name)

    # Update all callers to use get_binding_by_name() instead of linear search
```

**Update `read_property()`:**
```python
def read_property(self, target_var: str, prop_name: str) -> Optional[Any]:
    ref = self._bindings_by_name.get(target_var)
    if ref:
        return ref.properties.get(prop_name)
    return None
```

---

### Fix 2.2: Problem 7 — HitTester Import in mouseMoveEvent

**File:** `engine/canvas.py`

**Solution:** Move import to module level or use already-imported HitTester:

```python
# At top of canvas.py, after other imports:
from engine.hit_tester import HitTester

# In mouseMoveEvent:
# Remove: from engine.hit_tester import HitTester
# Use HitTester directly (it's already imported)
```

Actually, `HitTester` is already instantiated in MainWindow and passed around. The import inside `mouseMoveEvent` is for a local instantiation that shouldn't be there. The existing `self._engine_state.get_hitboxes()` already provides hitbox data without creating a new HitTester.

---

### Fix 2.3: Problem 9 — Ghost Rendering Hardcoded Types

**File:** `engine/canvas.py` — `paintGL()`

**Solution:** Use AST bindings for generic mobject matching:

```python
# Replace hardcoded if/elif chain with:
if anim_ref is not None:
    # Get the AST binding for this animation's target
    binding = self._ast_mutator.get_binding_by_name(anim_ref.target_var)
    if binding:
        # Find mobject whose type matches the binding's constructor
        for mob in self._scene.mobjects:
            if type(mob).__name__ == binding.constructor_name:
                ghost_mob = mob.copy()
                # ... apply ghost properties
```

**Requires:** `get_binding_by_name()` from Fix 2.1.

---

### Fix 2.4: Problem 8 — `_copy_properties` Limited Props

**File:** `engine/hot_swap.py` — `_copy_properties`

**Solution:** Add reflection-based fallback like `_apply_property_to_mob()`:

```python
def _copy_properties(self, old_mob: Any, new_mob: Any) -> None:
    """Copy visual properties from new mobject to old mobject."""
    try:
        # Existing specific handlers...
        if hasattr(new_mob, 'get_center') and hasattr(old_mob, 'move_to'):
            ...

        # NEW: Generic property copy via reflection
        # Get all properties that have getter on new_mob and setter on old_mob
        new_props = dir(new_mob)
        for prop in new_props:
            if prop.startswith('_'):
                continue
            # Check for getter pattern (get_* or is_*) on new_mob
            getter = None
            if hasattr(new_mob, f'get_{prop}'):
                getter = getattr(new_mob, f'get_{prop}')
            elif hasattr(new_mob, f'is_{prop}'):
                getter = getattr(new_mob, f'is_{prop}')

            if getter and callable(getter):
                setter_name = f'set_{prop}' if prop.startswith('is_') else f'set_{prop}'
                if hasattr(old_mob, setter_name):
                    setter = getattr(old_mob, setter_name)
                    if callable(setter):
                        try:
                            val = getter()
                            if val is not None:
                                setter(val)
                        except Exception:
                            pass
    except Exception as e:
        logger.debug(f"Property copy error: {e}")
```

---

## Tier 3: Medium Impact Fixes

---

### Fix 3.1: Problem 6 — `scene_is_healthy` Inconsistency

**File:** `engine/hot_swap.py` — `reload_from_file()`

**Solution:** Set `scene_is_healthy` based on actual success:

```python
try:
    source = path.read_text(encoding="utf-8")
    code = compile(source, str(path), "exec")
    isolated_ns = {}
    exec("from manim import *", isolated_ns)
    exec(code, isolated_ns)
    ...
    if added_mobjects:
        self._apply_updates(added_mobjects)
        self._engine_state.scene_is_healthy = True
    else:
        self._engine_state.scene_is_healthy = False  # No mobjects = unhealthy

except Exception as e:
    self._engine_state.scene_is_healthy = False
    logger.warning(f"Hot-swap failed: {e}")
    return False
```

---

### Fix 3.2: Problem 12 — Timeline Scrub Index Mismatch

**File:** `main.py` — `_on_timeline_scrub()`

**Solution:** Use `len(ast_mutator.animations)` consistently and validate:

```python
def _on_timeline_scrub(self, value: int) -> None:
    if not self._progress_slider.isSliderDown():
        return

    progress = value / 1000.0
    self.animation_player.seek(progress)

    total_anims = len(self.ast_mutator.animations)
    if total_anims == 0:
        self.engine_state.selected_animation = None
        return

    # Use total_anims consistently, not animation_count
    anim_idx = int(progress * total_anims)
    anim_idx = max(0, min(anim_idx, total_anims - 1))  # Clamp to valid range

    self.engine_state.selected_animation = self.ast_mutator.animations[anim_idx]
    self.engine_state.request_render()
```

---

### Fix 3.3: Problem 13 — No Cleanup on Scene Reload

**File:** `engine/canvas.py` — `reload_scene_from_module()`

**Solution:** Add cleanup calls before rebuilding:

```python
def reload_scene_from_module(self, module_name: str, scene_file: str) -> bool:
    ...
    # Step 0: Clean up old state
    self._engine_state.clear_hitboxes()
    self._engine_state.selected_animation = None
    # Note: ast_mutator._live_binds cleared by MainWindow after this returns

    # Continue with existing reload logic...
```

**In `MainWindow._do_full_reload()`:**
```python
def _do_full_reload(self, path: str) -> None:
    # Clear live binds before reload
    self.ast_mutator._live_binds.clear()
    self.animation_player.reset()

    # Continue with canvas reload...
```

---

### Fix 3.4: Problem 14 — OpenGL/Cairo Config Inconsistency

**File:** `main.py` and `engine/export_dialog.py`

**Solution:** Document the separation clearly:

```python
# In main.py, near the MANIM_RENDERER config:
# LIVE PREVIEW: Uses OpenGL renderer (GPU-accelerated, 60fps)
# EXPORT: Uses Cairo renderer (CPU-based, 100% accurate)
# The export_dialog passes --renderer=cairo explicitly.
# This "Draft Mode" separation is intentional — live preview is
# for interactive editing, export is for final output.
```

---

## Tier 4: Low Impact / Future

---

### Fix 4.1: Problem 11 — PropertyFinder generic_visit Redundancy

**File:** `engine/ast_mutator.py`

**Solution:** Remove `generic_visit()` call from `visit_Assign()` since `visit_Call()` handles Call nodes explicitly:

```python
def visit_Assign(self, node: ast.Assign) -> None:
    # Existing processing...
    # REMOVE: self.generic_visit(node)
```

---

### Fix 4.2: Problem 15 — earcut Patch Not Comprehensive

**File:** `main.py`

**Solution:** Create a centralized patch function and apply once:

```python
def _patch_manim_earcut():
    """Patch Manim's earcut to handle numpy type conversion."""
    import numpy as np
    import manim.utils.space_ops as space_ops

    original = space_ops.earcut

    def patched(verts, rings):
        if not isinstance(rings, np.ndarray):
            rings = np.array(rings, dtype=np.uint32)
        elif rings.dtype != np.uint32:
            rings = rings.astype(np.uint32)
        if verts.dtype != np.float32:
            verts = verts.astype(np.float32)
        return original(verts, rings)

    space_ops.earcut = patched
    # Also patch in modules that hold direct references
    import manim.mobject.opengl.opengl_vectorized_mobject as _m
    if hasattr(_m, 'earcut'):
        _m.earcut = patched
    if hasattr(_m, 'earclip_triangulation'):
        _m.earclip_triangulation = space_ops.earclip_triangulation

_patch_manim_earcut()
```

---

### Fix 4.3: Problem 1 — Python 3.9.6

**Recommendation:** Upgrade to Python 3.11+ when possible. This is not a code fix but a runtime upgrade. No code changes needed for Python 3.11+ compatibility with current codebase.

---

## Implementation Order

1. **Fix 1.1** (flush_writes) — Remove dead code, simplify architecture
2. **Fix 1.2** (register_live_bind) — Wire up dead Socket 4
3. **Fix 1.3** (PropertyUpdater) — Prevent expression loss
4. **Fix 1.4** (Animation detection) — Expand pattern support
5. **Fix 2.1** (bindings index) — Performance improvement
6. **Fix 2.2** (HitTester import) — Quick perf fix
7. **Fix 2.3** (Ghost rendering) — Depends on 2.1
8. **Fix 2.4** (_copy_properties) — Expand property support
9. **Fix 3.1** (scene_is_healthy) — Consistency fix
10. **Fix 3.2** (Timeline scrub) — Fix index calculation
11. **Fix 3.3** (Cleanup on reload) — State hygiene
12. **Fix 3.4** (Config docs) — Documentation
13. **Fix 4.1** (generic_visit) — Cleanup
14. **Fix 4.2** (earcut patch) — Consolidation
15. **Fix 4.3** (Python version) — Runtime note

---

**End of Fix Plan — Ready for Implementation**
