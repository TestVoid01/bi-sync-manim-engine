# Bi-Sync Manim Engine — Complete Mechanism Documentation

## Project Overview

**Bi-Sync Manim Engine** is a real-time interactive animation editor that fuses **PyQt6 GUI** with **Manim OpenGL rendering** through a zero-copy framebuffer hijack. It allows users to:

- Edit Python scene files (`.py`) and see changes instantly in the viewport
- Drag objects on the canvas and have the source code auto-updated
- Control properties via sliders that modify code in real-time
- Play/pause/replay captured animations frame-by-frame
- Select objects and navigate deep scene hierarchies

---

## Architecture Overview

### The Three Pillars

```
┌─────────────────────────────────────────────────────────────┐
│                    MAIN.PY (Application)                   │
│                                                             │
│  ┌───────────────────┐   ┌───────────────────┐              │
│  │   PyQt6 Window    │   │   Manim Scene      │              │
│  │   (GUI + Events)  │   │   (Data Model)     │              │
│  └─────────┬─────────┘   └─────────┬─────────┘              │
│            │                       │                        │
│            ▼                       ▼                        │
│  ┌────────────────────────────────────────────────────────┐ │
│  │                   MANIMCANVAS (QOpenGLWidget)          │ │
│  │                    THE RENDERING CORE                  │ │
│  │                                                        │ │
│  │  • Owns OpenGL context (from PyQt)                     │ │
│  │  • Creates ModernGL ctx (standalone=False)             │ │
│  │  • Hands context to HijackedRenderer                   │ │
│  │  • Drives render loop via paintGL()                    │ │
│  └────────────────────────────────────────────────────────┘ │
│            │                       │                        │
│            ▼                       ▼                        │
│  ┌───────────────────┐   ┌───────────────────┐              │
│  │  Renderer         │   │  Engine State      │              │
│  │  (HijackedRenderer)   │  (Central Socket) │              │
│  └───────────────────┘   └───────────────────┘              │
└─────────────────────────────────────────────────────────────┘
```

---

## Core Concepts

### 1. OpenGL Context Hijack (The Heart of the System)

**Problem**: Manim wants to create its own OpenGL window. PyQt6 already has an OpenGL context. We need them to share.

**Solution**: "Zero-Copy FBO Hijack"

```
PyQt6 Window                    Manim
     │                            │
     ├──► QOpenGLWidget creates   │
     │    OpenGL Context (OS/GPU)  │
     │                            │
     ├──► ManimCanvas paintGL()   │
     │    creates ModernGL ctx    │
     │    (standalone=False)      │
     │    ← ADOPTS PyQt's ctx     │
     │                            │
     ├──► HijackedRenderer uses   │
     │    that context            │
     │                            │
     └──► detect_framebuffer()    │
          ← gets PyQt's FBO       │
          (VRAM directly)        │
```

**Step-by-step flow**:

1. `QMainWindow.__init__()` creates `ManimCanvas`
2. `QOpenGLWidget` constructor triggers OS to allocate GPU context
3. First `paintGL()` call:
   - Calls `moderngl.create_context(standalone=False)` 
   - This adopts the existing PyQt context instead of creating new one
   - Creates `HijackedRenderer`, calls `set_external_context(ctx)`
4. `renderer.init_scene(scene)`:
   - Sets `self.context = external_ctx`
   - Calls `ctx.detect_framebuffer()` — gets PyQt's FBO pointing to VRAM
5. Every subsequent `paintGL()`:
   - Calls `renderer.update_fbo()` (re-detects FBO for resize safety)
   - Calls `renderer.update_frame(scene)` — renders into PyQt's VRAM
   - Result appears directly in the Qt window

**Key insight**: No RAM→GPU copy. Manim shaders write directly to PyQt's framebuffer in VRAM.

---

### 2. Socket Architecture (Decoupled Communication)

`EngineState` is the central hub with 5 sockets:

```
Socket 1: on_scene_parsed()
├── Purpose: Called after scene.construct() completes
├── Who calls: ManimCanvas
├── Who listens: AST Mutator builds variable→mobject mapping
└── Data: None (triggers AST scan)

Socket 2: push_hitbox(id, bbox)
├── Purpose: AABB bounding boxes for mouse hit-testing
├── Who calls: Renderer after each frame
├── Who reads: HitTester for click detection
└── Data: {mobject_id: (min_x, min_y, max_x, max_y)}

Socket 3: request_render(dt)
├── Purpose: Trigger repaint from external code
├── Who calls: HotSwap, DragController, AnimationPlayer
├── Who listens: ManimCanvas._on_render_request
└── Data: delta time (optional)

Socket 4: (in ASTMutator) live_bind(mobject_id, var_name)
├── Purpose: O(1) lookup from rendered shape to code line
├── Who calls: HitTester on click
├── Who reads: DragController for AST updates
└── Data: {mobject_id: variable_name}

Socket 5: pause/resume_file_watcher
├── Purpose: Prevent feedback loop during drag
├── Who calls: DragController, PropertyPanel
├── Who listens: FileWatcher
└── Data: pause/resume signals
```

---

## Data Flow Architecture

### A. Startup Flow

```
main.py
  │
  ├── configure_manim() ──► Set MANIM_RENDERER=opengl, preview=False
  │
  ├── patch_manim_earcut() ──► Fix C++ earcut type mismatch
  │
  ├── patch_manim_creation_tracking() ──► Track line numbers on mobjects
  │
  └── MainWindow.__init__()
        │
        ├── setup_ui() ──► Create PyQt6 widgets
        │
        ├── engine_state = EngineState() ──► Create state hub
        │
        ├── canvas = ManimCanvas(scene_class, engine_state)
        │     │
        │     └── (First paintGL) → _do_first_init()
        │           ├── create ModernGL ctx (standalone=False)
        │           ├── create HijackedRenderer
        │           ├── renderer.init_scene(scene)
        │           │     └── detect_framebuffer() → get PyQt's FBO
        │           └── emit scene_parsed
        │                 └── ASTMutator.parse_file() → builds bindings
        │
        ├── drag_controller = DragController(engine_state, ...)
        ├── animation_player = AnimationPlayer(engine_state, ...)
        ├── property_panel = PropertyPanel(...)
        │
        └── file_watcher = SceneFileWatcher(engine_state, on_change)
              │
              └── QFileSystemWatcher.addPath(scene_file)
```

### B. Rendering Flow (Continuous 60fps)

```
paintGL()
  │
  ├── If first call: _do_first_init()
  │
  ├── If init_error: return (black screen protection)
  │
  ├── renderer.update_fbo()
  │     └── ctx.detect_framebuffer() → re-get PyQt FBO
  │
  ├── Check selected_animation (Phase 5 Ghost Renderer)
  │
  ├── renderer.update_frame(scene)
  │     ├── render_mobject() for each mobject
  │     │     ├── Calculate AABB bounding box
  │     │     └── push_hitbox(mob_id, bbox) → EngineState
  │     │
  │     └── Write to FBO (PyQt's VRAM)
  │
  └── Result appears in Qt window

Note: 60fps driven by QTimer calling update() every 16ms
```

### C. Code Edit → Visual Update Flow (Hot-Swap)

```
User edits scenes/advanced_scene.py in external editor
         │
         ▼
FileWatcher detects change (QFileSystemWatcher)
         │
         ▼
_debounce_timer.start(300ms) ──► Collapse duplicate events
         │
         ▼
_do_reload() → HotSwapInjector.reload_from_file()
         │
         ├── Read new source code from disk
         │
         ├── ast_mutator.parse_source_text(path, source)
         │     └── Rebuild AST bindings with new line numbers
         │
         ├── exec(code) in isolated namespace
         │     └── Extract new Scene class
         │
         ├── Create temp scene, call construct()
         │     └── Capture all mobjects added via self.add()
         │
         ├── _apply_updates(new_mobjects)
         │     ├── Match by _bisync_line_number
         │     ├── Fallback: class type + order
         │     └── Update existing scene mobjects
         │
         └── engine_state.request_render()
               └── ManimCanvas.update() → paintGL()
```

### D. Drag Object → Code Update Flow

```
MousePress on canvas
         │
         ▼
ManimCanvas.mousePressEvent()
         │
         ▼
drag_controller.on_mouse_press(px, py)
         │
         ├── coord_transformer.pixel_to_math(px, py)
         │
         ├── hit_tester.test(math_x, math_y)
         │     └── Returns mobject_ids sorted by AABB area
         │
         ├── Resolve hit (respecting isolation mode)
         │
         ├── Get AST ref via hit_tester.get_ast_ref(mob)
         │
         ├── file_watcher.pause() ──► Socket 5
         │
         └── _drag_timer.start(16ms) ──► 60Hz throttled updates
               │
               ▼
DragTimer fires every 16ms
         │
         ▼
_process_pending_drag()
         │
         ├── Read _pending_pos (latest mouse position)
         ├── Calculate new center
         ├── mob.move_to(new_center) ──► In-memory only, no SSD write
         └── engine_state.request_render()
               │
               ▼
paintGL() renders updated position

... (many drag events) ...

MouseRelease
         │
         ▼
drag_controller.on_mouse_release()
         │
         ├── mob.move_to(final_position)
         │
         ├── ast_mutator.update_position(var_name, line_num, new_center)
         │     ├── Locate AST Assign node for variable
         │     ├── Find or create .move_to() call
         │     ├── Update coordinates in AST
         │     └── ast.unparse() → new source
         │
         ├── ast_mutator.save_atomic(path, new_source)
         │     ├── Write to temp file
         │     └── os.rename() → atomic replace
         │
         ├── file_watcher.notify_internal_commit(500ms)
         │     └── Suppress watcher for 500ms
         │
         └── file_watcher.resume() ──► Socket 5
```

### E. Property Slider → Code Update Flow

```
User drags slider in PropertyPanel
         │
         ▼
slider.value_changed.emit(value)
         │
         ├── hot_swap.apply_single_property(var_name, prop, value)
         │     ├── Parse AST if needed
         │     ├── Locate property in constructor call
         │     ├── Update value in AST node
         │     └── Return modified source (no save yet)
         │
         ├── hot_swap.reload_with_source(new_source)
         │     ├── Apply updates to live scene mobjects
         │     └── request_render()
         │
         └── (Slider still moving) ──► in-memory only, no disk write

Slider released
         │
         ▼
slider.value_released.emit(final_value)
         │
         ├── ast_mutator.update_property(var_name, prop, final_value)
         │     ├── PropertyUpdater transformer
         │     └── ast.unparse()
         │
         ├── ast_mutator.save_atomic()
         │     └── Atomic file write
         │
         └── file_watcher.resume()
```

---

## Component Deep Dive

### 1. ManimCanvas (QOpenGLWidget)

**Role**: The rendering core that owns the OpenGL context and drives the render loop.

**Key States**:
- `_initialized`: Has first paintGL completed?
- `_init_error`: Did initialization fail (black screen trap)?
- `_ctx`: ModernGL context (created in first paintGL)
- `_renderer`: HijackedRenderer instance
- `_scene`: Live Manim Scene instance

**Lifecycle**:
```
1. __init__: Store scene_class and engine_state
2. set_render_callback: Register for Socket 3
3. First paintGL: _do_first_init() → create ctx, renderer, scene
4. Subsequent paintGL: update_fbo() + update_frame()
5. resizeGL: Update viewport (no scene reconstruction)
```

**Phase 5 Ghost Renderer Logic** (lines in paintGL):
- When `selected_animation` is set, render a semi-transparent "ghost" mobject
- Ghost position follows animation target args
- User can drag the ghost to reposition animation

### 2. HijackedRenderer (OpenGLRenderer subclass)

**Role**: Subclass Manim's renderer to use external GL context.

**Key methods**:
- `set_external_context(ctx)`: Inject PyQt's ModernGL context
- `init_scene(scene)`: Initialize with external context + detect PyQt's FBO
- `update_fbo()`: Re-detect FBO on resize
- `should_create_window()`: Always returns False (prevents rogue windows)

**NullFileWriter**: Prevents all SSD I/O from Manim's file writer.

### 3. EngineState (Central State Hub)

**Role**: Decouple all components via socket callbacks.

**Key attributes**:
```python
_scene_parsed_callbacks    # Socket 1
_hitboxes                  # Socket 2
_render_callback          # Socket 3
_file_watcher_paused      # Socket 5
selected_animation         # Phase 5
object_registry            # Phase 6
isolated_mobject_id/path   # Phase 6
```

### 4. ASTMutator (Code ↔ Scene Bridge)

**Role**: Parse Python source as AST, enable surgical edits.

**Key classes**:
- `PropertyFinder`: Visits AST to find `var = Constructor(...)` patterns
- `PropertyUpdater`: Transforms specific property values
- `ASTNodeRef`: Metadata about found node (line, col, properties)

**Key attributes**:
```python
bindings: dict[int, ASTNodeRef]  # line_number → node ref
_live_binds: dict[int, str]      # mobject_id → variable_name (Socket 4)
```

**Key operations**:
- `parse_file(path)`: Load .py, walk AST, build bindings
- `update_property(var, prop, value)`: Surgical edit
- `save_atomic(path, source)`: Write via tempfile + rename (crash-proof)
- `register_live_bind(mob_id, var_name)`: Socket 4 registration

### 5. HotSwapInjector (Zero-Restart Reload)

**Role**: Reload scenes by exec-ing new code without restarting.

**Flow**:
```
reload_from_file(path)
  │
  ├── Read source from disk
  ├── Update ASTMutator with new code
  ├── exec() in isolated namespace → get new Scene class
  ├── Create temp scene, call construct()
  ├── Capture mobjects via patched self.add()
  ├── _apply_updates(new_mobjects) → match by line number
  └── request_render()
```

**Key safety**: Original scene preserved if reload fails.

### 6. DragController (Interactive Manipulation)

**Role**: Handle mouse → object interaction with throttled updates.

**State machine**:
```
IDLE → (mouse press + hit) → DRAGGING → (mouse release) → IDLE
```

**SPSC-style throttle**: 
- `_pending_pos`: Stores only the LATEST mouse position
- `_drag_timer`: Fires at 60Hz, reads pending pos, applies once per frame
- Result: Hundreds of mouse events collapse into one update per frame

**SSD debounce**:
- During drag: In-memory `mob.move_to()` only
- On release: AST Mutator saves to disk atomically
- File watcher paused during drag to prevent feedback loop

### 7. HitTester (Object Selection)

**Role**: AABB hit-testing for mouse clicks.

**Algorithm**:
```
test(x, y):
  for each (mob_id, bbox) in hitboxes:
    if bbox contains (x, y):
      calculate area
      add to hits
  sort by area (smallest first)
  return mob_ids
```

**Smallest bounding box wins** — handles overlapping objects correctly.

### 8. CoordinateTransformer (Pixel ↔ Math)

**Role**: Convert Qt pixel coordinates to Manim math coordinates.

**Formula** (from manim defaults):
```python
# Manim default: height=8 units, width=height * aspect_ratio
math_x = (pixel_x - width/2) / (width/2) * (8 * aspect_ratio / 2)
math_y = (height/2 - pixel_y) / (height/2) * 4.0
```

### 9. FileWatcher (QFileSystemWatcher)

**Role**: Detect external file changes, trigger hot-swap.

**Debounce**: 300ms QTimer collapses duplicate filesystem events from atomic writes.

**Socket 5 integration**:
- `pause()`: Stop reacting during drag/slider
- `resume()`: Re-enable, trigger pending reload if any

### 10. AnimationPlayer (Frame-by-Frame Playback)

**Role**: Non-blocking animation replay via QTimer.

**Capture phase** (during scene.construct()):
```python
# ManimCanvas patches scene.play:
scene.play = lambda *anims, **kw: capture_play_call(scene, anims, kw, snapshot)
```

**Playback phase** (on user play):
```python
_tick():
  interpolate_all(alpha)  # Call animation.interpolate(alpha)
  emit progress
  request_render()
```

**State snapshots**: Store deep copies of mobjects before animation. Restore on seek.

### 11. PropertyPanel (PyQt Slider UI)

**Role**: GUI sliders that modify code in real-time.

**During drag**: In-memory update via HotSwapInjector (fast path)
**On release**: AST Mutator saves to disk (authoritative path)

### 12. ObjectRegistry (Scene Graph Tracker)

**Role**: Map live mobject ids to canonical AST-backed identities.

**Data structure**:
```python
_refs_by_id: dict[int, LiveObjectRef]              # mob_id → metadata
_top_level_ids_by_var: dict[str, int]              # var_name → top_level_id
_source_key_to_id: dict[str, int]                  # source_key → mob_id
```

**Supports deep hierarchies**: Path tuples like `(0, 2, 1)` for `axes[0][2][1]`

---

## Phase Progression

### Phase 1: Core Rendering & GUI Fusion
- ManimCanvas (QOpenGLWidget)
- OpenGL context hijack
- Basic render loop

### Phase 2: Scene File Parsing
- ASTMutator
- Variable→Mobject mapping
- Source code as edit target

### Phase 3: Bi-Directional Sync Bridge
- HotSwapInjector (exec-based reload)
- FileWatcher (QFileSystemWatcher)
- PropertyPanel (slider UI)
- Socket 5 pause/resume

### Phase 4: Interactive Canvas Controller
- HitTester (AABB selection)
- DragController (SPSC throttle)
- CoordinateTransformer (pixel→math)
- Real-time object manipulation

### Phase 5: Animation Visual Editing
- AnimationPlayer (frame-by-frame)
- Ghost renderer (semi-transparent preview)
- Timeline keyframes

### Phase 6: Deep Graphical Control
- ObjectRegistry (scene graph)
- Isolation mode (drill into hierarchies)
- SelectionRef payload

---

## Key Safety Mechanisms

### 1. Black Screen Trap
```python
if self._init_error is not None:
    return  # Don't render if init failed
```

### 2. Atomic File Writes
```python
with tempfile.NamedTemporaryFile(mode='w', delete=False) as f:
    f.write(new_source)
os.rename(temp_path, target_path)  # Atomic on POSIX
```

### 3. Try/Except Wrapping
All callbacks and external operations wrapped to prevent crashes.

### 4. Feedback Loop Prevention
File watcher paused during slider drag and object drag.

---

## Data Structures Summary

### ASTNodeRef
```python
variable_name: str           # "circle"
line_number: int             # 42
col_offset: int              # 4
constructor_name: str        # "Circle"
bisync_uuid: str             # Persistent identifier
properties: dict            # {"radius": 1.5, "color": "BLUE"}
transforms: dict             # {"scale": 2.0, "rotate": 45}
source_key: str              # "circle:42:4"
```

### LiveObjectRef (ObjectRegistry)
```python
mobject_id: int
top_level_id: int
variable_name: Optional[str]
line_number: Optional[int]
constructor_name: str
path: tuple[int, ...]        # [0, 2, 1] for axes[0][2][1]
```

### SelectionRef (UI Payload)
```python
mobject_id: int
top_level_id: int
variable_name: str
line_number: Optional[int]
source_key: Optional[str]
editability: str             # "source_editable" or "live_read_only"
path: tuple[int, ...]
display_name: str           # "circle[0][2][1]"
```

### ASTAnimationRef (Phase 5)
```python
target_var: str             # "circle"
method_name: str            # "move_to"
args: list                  # [[1, 2, 0]]
line_number: int
col_offset: int
kwargs: dict                # {"run_time": 2}
```

---

## Configuration Constants

| Constant | Value | Purpose |
|----------|-------|---------|
| `MANIM_RENDERER` | `"opengl"` | Use GPU rendering |
| `DEBOUNCE_TIMER` | `300ms` | Collapse file system events |
| `DRAG_TIMER_INTERVAL` | `16ms` | 60fps throttled updates |
| `MULTIPLIER` | `10` | Float slider→int range |
| `SUPPRESS_AFTER_INTERNAL` | `500ms` | Prevent watcher trigger after save |

---

## File Dependencies

```
main.py
├── engine/
│   ├── canvas.py          # ManimCanvas, renderer integration
│   ├── state.py           # EngineState (central hub)
│   ├── renderer.py        # HijackedRenderer, NullFileWriter
│   ├── ast_mutator.py     # AST parsing and surgical edits
│   ├── hot_swap.py        # Zero-restart reload
│   ├── file_watcher.py   # QFileSystemWatcher wrapper
│   ├── hit_tester.py      # AABB selection
│   ├── drag_controller.py # Mouse state machine
│   ├── coordinate_transformer.py  # Pixel ↔ Math
│   ├── property_panel.py # PyQt slider UI
│   ├── animation_player.py # Frame-by-frame playback
│   ├── object_registry.py # Scene graph tracking
│   ├── code_editor.py     # Built-in code editing
│   ├── export_dialog.py   # Video export
│   └── scene_sync.py      # Reload decision logic
└── scenes/
    └── advanced_scene.py   # User's Manim scene
```

---

## End-to-End Example: Drag Circle

1. User clicks on rendered Circle
2. `mousePressEvent` → `drag_controller.on_mouse_press(px, py)`
3. `coord_transformer.pixel_to_math(px, py)` → math coords
4. `hit_tester.test(math_x, math_y)` → returns `[circle_id]`
5. `hit_tester.get_ast_ref(mob)` → `ASTNodeRef(variable_name="circle", line_number=15)`
6. DragController stores `selected_var_name="circle"`, `selected_line_num=15`
7. FileWatcher pauses (Socket 5)
8. DragTimer starts (60Hz)
9. Mouse moves → `_pending_pos` updated (SPSC overwrite)
10. DragTimer fires → `_process_pending_drag()` → `circle.move_to(new_pos)`
11. `request_render()` → `paintGL()` renders at new position
12. Mouse released → `on_mouse_release()`
13. `ast_mutator.update_position("circle", 15, new_center)`
    - Parses AST, finds Circle at line 15
    - Finds or creates `.move_to([x, y, z])` call
    - Updates coordinates in AST
    - `ast.unparse()` → new source
14. `save_atomic(path, new_source)` → atomic file write
15. FileWatcher notified, then resumed
16. Final render shows circle at new position

**Total time**: ~16ms per frame during drag, ~1ms for final AST save.
