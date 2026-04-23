# Bi-Sync Manim Engine — Problem Analysis

**Date:** 2026-04-23
**Status:** Analysis Complete — No Changes Made

---

## Problem 1: Python 3.9.6 (Outdated Runtime)

**Severity:** Medium

**Issue:**
The project runs on Python 3.9.6 (April 2026). This is acceptable for `ast.unparse()` (added 3.9) but limits access to newer Python features and typing improvements.

**Impact:**
- No `match-case` syntax (3.10+)
- No `str.removeprefix()` standard (3.9+ but was added)
- Older `typing` features missing
- Manim 0.19.0 may drop Python 3.9 support soon

---

## Problem 2: AST `PropertyUpdater` — Replacing vs Merging Properties

**Severity:** High

**Location:** `engine/ast_mutator.py` — `PropertyUpdater.visit_Assign`

**Issue:**
When updating a property, the code **replaces** the entire keyword value node:

```python
kw.value = ast.Constant(value=self._new_value)
```

This works for simple constants, but:
- If the original was `radius=1.5+0.5`, it becomes `radius=2.0` (loses expression)
- If the value is a complex expression (like `UP * 2`), it becomes a flat constant

**Expected Behavior:**
Only replace when the value is a simple constant. For complex expressions, either preserve them or log a warning.

**Current Code (line 219):**
```python
kw.value = ast.Constant(value=self._new_value)  # Always replaces
```

---

## Problem 3: `bindings` Dict is Indexed by Line Number, Not Variable Name

**Severity:** Medium

**Location:** `engine/ast_mutator.py`

**Issue:**
The `bindings` dict uses `lineno` (int) as key, but most operations need to lookup by `variable_name` (str):

```python
self.bindings[node.lineno] = ref  # Key is line number
```

Then lookup requires O(N) iteration:
```python
for r in self._bindings.values():
    if r.variable_name == target_var:  # Linear search every time
```

**Impact:**
- `read_property()`, `update_property()`, `register_live_bind()` all do O(N) lookups
- Adding new variables with same line number would overwrite
- `live_binds` dict maps `mobject_id → ASTNodeRef` but finding the ref requires iteration

---

## Problem 4: `PropertyFinder.visit_Call` Only Handles `self.play(obj.animate.method())`

**Severity:** High

**Location:** `engine/ast_mutator.py` — `PropertyFinder.visit_Call`

**Issue:**
Animation detection is hardcoded to exactly one pattern:

```python
if isinstance(arg.func, ast.Attribute) and isinstance(arg.func.value, ast.Attribute) ...
```

**Misses these common patterns:**
```python
self.play(circle.animate.shift(UP))           # OK — but complex UP not resolved
self.play(Create(circle))                     # Function-style animation
self.play(circle.shift, UP)                   # Callable animation
self.wait(1)                                  # Not captured
self.play(FadeIn(circle), run_time=1)         # Not captured
```

**Also:** AST constants like `UP`, `DOWN`, `LEFT`, `RIGHT` are not resolved to coordinates. They remain as `ast.Name` nodes that can't be converted back to math coordinates during animation target editing.

---

## Problem 5: `flush_writes()` is a No-Op

**Severity:** High

**Location:** `engine/state.py` — `flush_writes()`

**Issue:**
The method logs and clears pending writes but **never actually writes to disk**:

```python
def flush_writes(self) -> None:
    if not self._pending_writes:
        return
    count = len(self._pending_writes)
    logger.info(f"flush_writes: {count} pending writes (Phase 2 will implement)")
    self._pending_writes.clear()  # Data lost!
```

**Comment says "Phase 2 will implement"** — but Phase 2 is already done. The actual atomic write is in `ASTMutator.save_atomic()`, not here. This creates confusion about who owns the write responsibility.

**Impact:**
- During drag operations, if `flush_writes()` is called instead of `save_atomic()`, data is lost
- The debounce architecture is split between two classes unnecessarily

---

## Problem 6: `scene_is_healthy` Not Consistently Reset on Success

**Severity:** Medium

**Location:** `engine/canvas.py` vs `engine/hot_swap.py`

**Issue:**
In `canvas.py`, `scene_is_healthy` is set to `True` after successful `construct()`:
```python
self._scene.construct()
self._engine_state.scene_is_healthy = True  # Set on success
```

But in `hot_swap.py`, `reload_from_file()` sets it to `True` **before** `_apply_updates()` runs:
```python
self._engine_state.scene_is_healthy = True  # Set BEFORE we know if update succeeded
```

If `_apply_updates()` fails or finds no mobjects, the flag incorrectly remains `True`.

---

## Problem 7: `canvas.py` Imports `HitTester` Inside `mouseMoveEvent`

**Severity:** Low (Performance)

**Location:** `engine/canvas.py` — `mouseMoveEvent`

**Issue:**
```python
def mouseMoveEvent(self, event: QMouseEvent) -> None:
    ...
    from engine.hit_tester import HitTester  # Import every mouse move!
```

This import runs on every mouse move event (60 times/second). Should be a module-level import or class attribute.

---

## Problem 8: `_copy_properties` Limited to Few Property Types

**Severity:** Medium

**Location:** `engine/hot_swap.py` — `_copy_properties`

**Issue:**
Only these properties are copied:
- Position (`move_to`)
- Color (`set_color`)
- Fill opacity
- Stroke opacity
- Scale (via width)

**Missing common properties:**
- `stroke_width`
- `fill_color`
- `stroke_color`
- `font_size` (for Text)
- `tex_string` (for MathTex)
- `scale` (transform)
- `angle` (rotation)
- submobject relationships

If user changes a property not in this list, hot-swap silently ignores it.

---

## Problem 9: Ghost Rendering Hardcoded Type Matching

**Severity:** Medium

**Location:** `engine/canvas.py` — `paintGL()` (lines 153-181)

**Issue:**
```python
if (anim_ref.target_var == "circle" and mob_type == "Circle") or \
   (anim_ref.target_var == "square" and mob_type == "Square") or \
   (anim_ref.target_var == "triangle" and mob_type == "Triangle") or \
   (anim_ref.target_var == "dot" and mob_type == "Dot"):
```

This is a hardcoded allowlist. If user creates `star = Star()` or `rect = Rectangle()`, ghost rendering won't work for them.

**Should:** Use a generic mobject-to-variable matching system based on `ast_mutator.bindings`.

---

## Problem 10: `live_binds` Population Missing — `register_live_bind()` Never Called

**Severity:** High

**Location:** `engine/ast_mutator.py` — `register_live_bind()`

**Issue:**
The method exists and is documented as "Socket 4":
```python
def register_live_bind(self, mobject_id: int, variable_name: str) -> None:
    """Register a link between a rendered Mobject and its AST node."""
```

But **no code in the entire codebase calls this method**. The `HitTester` and `DragController` never register binds.

**Impact:**
- Mobject selection by clicking can't find the variable name reliably
- `get_live_bind()` always returns `None`
- The entire Socket 4 architecture is dead code

---

## Problem 11: `PropertyFinder` Uses `generic_visit` After `visit_Assign`

**Severity:** Low

**Location:** `engine/ast_mutator.py` — `PropertyFinder.visit_Assign`

**Issue:**
```python
def visit_Assign(self, node: ast.Assign) -> None:
    ...  # Process assignment
    self.generic_visit(node)  # This re-visits all children including Call nodes
```

Then `visit_Call` also exists and processes calls independently.

**Problem:** For code like `circle = Circle(radius=2)`, the `visit_Call` visitor processes the `Circle()` call **twownce** — once explicitly (via `generic_visit`) and once through the Call visitor. This isn't wrong but is redundant and potentially confusing.

**Worse:** For nested structures, the visitor pattern may not handle depth correctly.

---

## Problem 12: `_on_timeline_scrub` Animation Index Mismatch

**Severity:** Medium

**Location:** `main.py` — `_on_timeline_scrub()`

**Issue:**
```python
anim_idx = min(int(progress * self.animation_player.animation_count), total_anims - 1)
if anim_idx < len(self.ast_mutator.animations):
    self.engine_state.selected_animation = self.ast_mutator.animations[anim_idx]
```

**Problems:**
1. `animation_player.animation_count` and `len(ast_mutator.animations)` may differ (one counts queued, one counts from AST)
2. Progress is 0.0–1.0 but mapping to integer index can be off-by-one
3. No validation that `anim_idx` is in range before accessing

---

## Problem 13: No Cleanup of Old Scene State on Reload

**Severity:** Medium

**Location:** `engine/canvas.py` — `reload_scene_from_module()`

**Issue:**
```python
if self._scene is not None:
    self._scene.mobjects.clear()  # Only clears mobjects list
```

**What should be cleaned but isn't:**
- `renderer._mobject_cache` (if any)
- `animation_player` internal state
- `_live_binds` in ast_mutator
- `engine_state._hitboxes`

This can cause ghost objects from previous scenes to linger in state.

---

## Problem 14: Export Uses Cairo Renderer But Global Config Sets OpenGL

**Severity:** Medium

**Location:** `main.py` — lines 29-40 and `engine/export_dialog.py`

**Issue:**
At module load time, `main.py` sets:
```python
os.environ["MANIM_RENDERER"] = "opengl"
manim_config.renderer = "opengl"
```

But `export_dialog.py` overrides this with `--renderer=cairo` flag. This works but creates an inconsistency — the live preview uses OpenGL while exports use Cairo. The "Draft Mode" approach (as documented in memory.md) justifies this, but it's a hidden configuration that could confuse future developers.

---

## Problem 15: `_patched_earcut` Patch Applied to Multiple Locations

**Severity:** Low (Potential Conflicts)

**Location:** `main.py` — lines 49-107

**Issue:**
The earcut patch is applied to:
1. `_space_ops.earcut`
2. `_space_ops.earclip_triangulation`
3. `_ogl_vmob.earclip_triangulation`

And then also patched again in `space_ops` directly. If Manim internally imports earcut in other places not covered here, those would still crash.

**Not future-proof** — if Manim updates its internal earcut usage, this patch might not cover all cases.

---

## Summary Table

| # | Problem | Severity | File |
|---|---------|----------|------|
| 1 | Python 3.9.6 outdated | Medium | — |
| 2 | PropertyUpdater replaces expressions | High | ast_mutator.py |
| 3 | bindings indexed by line not variable | Medium | ast_mutator.py |
| 4 | Animation detection limited pattern | High | ast_mutator.py |
| 5 | flush_writes is no-op | High | state.py |
| 6 | scene_is_healthy not consistent | Medium | hot_swap.py |
| 7 | HitTester import in mouseMoveEvent | Low | canvas.py |
| 8 | _copy_properties limited props | Medium | hot_swap.py |
| 9 | Ghost rendering hardcoded types | Medium | canvas.py |
| 10 | register_live_bind never called | High | ast_mutator.py |
| 11 | PropertyFinder generic_visit redundancy | Low | ast_mutator.py |
| 12 | Timeline scrub animation index mismatch | Medium | main.py |
| 13 | No cleanup on scene reload | Medium | canvas.py |
| 14 | OpenGL/Cairo config inconsistency | Medium | main.py |
| 15 | earcut patch not comprehensive | Low | main.py |

---

**End of Analysis — No modifications made to any files.**
