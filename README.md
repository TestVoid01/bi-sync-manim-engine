# Bi-Sync Manim Engine

A real-time graphical authoring tool for [Manim](https://www.manim.community/) — the math animation engine used by [3Blue1Brown](https://www.youtube.com/c/3blue1brown).

**Drag objects on a live canvas → Python source code updates automatically. Edit code → canvas refreshes instantly.**

No configuration needed. Just point it at any Manim scene file and start editing visually.

---

## What It Does

Bi-Sync Engine gives Manim a **visual GUI editor** with two-way synchronization:

- **Canvas → Code:** Drag, scale, or rotate any object on the canvas. The engine parses your Python source via AST, locates the exact constructor or modifier call, and writes the change back to disk.
- **Code → Canvas:** Edit your `.py` file in any external editor. The engine detects the change, hot-reloads the scene, and renders the updated frame instantly.
- **Property Panel:** Click any object to inspect and edit its properties (color, radius, position, font_size, etc.) through an interactive GUI panel. Changes persist to source code.
- **Animation Playback:** Step through your scene's animations frame-by-frame, or play them back in real time at 60fps.
- **Export:** Render the final animation to MP4/GIF directly from the GUI.

## Architecture

```
main.py                  → Entry point, Qt window, toolbar, export
engine/
├── canvas.py            → OpenGL rendering surface (hijacks Manim's renderer)
├── renderer.py          → Custom OpenGL renderer with FBO management
├── ast_mutator.py       → Python AST parser — reads/writes source code
├── property_panel.py    → Dynamic property editor (sliders, color pickers, code fields)
├── property_inspector.py→ Runtime introspection of Manim objects
├── property_policy.py   → Decides which properties are live-safe vs reload-only
├── drag_controller.py   → Mouse interaction — drag, scale, rotate on canvas
├── hit_tester.py        → Pixel-accurate click detection
├── animation_player.py  → Frame-by-frame animation playback engine
├── hot_swap.py          → Live code injection without full reload
├── file_watcher.py      → Watches source file for external edits
├── object_registry.py   → Maps live Manim objects to their AST source nodes
├── scene_loader.py      → Dynamic scene class discovery (any Scene subclass)
├── state.py             → Centralized application state
├── persistence_policy.py→ 3-tier persistence: exact_source / safe_patch / no_persist
├── runtime_provenance.py→ Tracks which line of code created each object
├── scene_sync.py        → Coordinates reload between canvas and AST
├── code_editor.py       → Built-in syntax-highlighted code viewer
└── export_dialog.py     → Resolution/format picker for final render
scenes/                  → Example Manim scene files
tests/                   → 57 automated test files
docs/                    → Architecture documentation
```

## Requirements

- **Python** 3.9+
- **Manim** (Community Edition) 0.18+
- **PyQt6** 6.5+
- **ModernGL** 5.8+
- **NumPy** 1.24+
- macOS or Linux (Windows not tested)

## Installation

```bash
# Clone the repository
git clone https://github.com/TestVoid01/bi-sync-manim-engine.git
cd bi-sync-manim-engine

# Install dependencies
pip install -r requirements.txt
```

> **Note:** Manim itself requires additional system dependencies (LaTeX, FFmpeg, Cairo).
> See [Manim Installation Guide](https://docs.manim.community/en/stable/installation.html).

## Usage

```bash
# Launch the engine (loads scenes/advanced_scene.py by default)
python3 main.py
```

### Controls

| Action | How |
|---|---|
| **Select object** | Click on it |
| **Drag object** | Click + drag |
| **Edit properties** | Select object → use the Property Panel on the right |
| **Play animations** | Press the Play button or `Space` |
| **Refresh scene** | `Cmd+R` or the Refresh button |
| **Save** | `Cmd+S` |
| **Export video** | File → Export |

### Using Your Own Scene

Edit `scenes/advanced_scene.py` or point the engine at any `.py` file containing a `Scene` subclass. The engine automatically discovers and loads the scene class — no hardcoded names required.

## How It Works (Technical Overview)

### AST-Based Source Editing

When you drag a `Circle` on the canvas, the engine doesn't just update an in-memory variable. It:

1. Parses your Python file into an Abstract Syntax Tree (AST)
2. Finds the exact `Circle(radius=1.5, color=BLUE)` constructor call
3. Modifies the `radius` keyword argument node in the AST
4. Writes the modified source back to disk atomically (via tempfile + rename)

This means your source file is always the single source of truth.

### Property Classification

Not all properties can be safely edited live. The engine classifies each property:

- **`live_safe`** — Visual properties (color, opacity) that update instantly without side effects
- **`reload_only`** — Geometric properties (radius, side_length) that require a scene rebuild
- **`read_only`** — Computed or runtime-only values shown for inspection but not editable

### Persistence Strategy

Every edit goes through a 3-tier decision:

1. **`exact_source`** — Direct AST node found → modify and save
2. **`safe_patch`** — No exact node, but safe to inject a new keyword → patch and save
3. **`no_persist`** — Cannot safely write to source → apply in-memory only, warn user of "preview drift"

## Project Status

The core engine is **stable and functional**. All 6 development slices are complete:

- ✅ Slice 1 — Canvas rendering and OpenGL context hijacking
- ✅ Slice 2 — Object selection, dragging, and hit testing
- ✅ Slice 3 — AST parsing and bi-directional source sync
- ✅ Slice 4 — Animation playback and timeline control
- ✅ Slice 5 — Advanced property widgets (tuples, code expressions)
- ✅ Slice 6 — Persistence reliability and export verification

### Known Limitations

- 3D scene support is partial (camera manipulation works, but 3D drag is limited)
- Complex chained method calls (e.g., `obj.scale(2).rotate(PI).shift(UP)`) may not all persist
- Loop-generated objects are runtime-only (cannot trace back to a single source line)

## A Note from the Creator (Built with AI)

I come from a **C++ background** and do not actively code in Python. This entire project—the complex AST parsing logic, OpenGL context hijacking, and real-time GUI synchronization—was built through **Pair Programming with an AI Agent**. 

My role was driven by my vision for what this tool could be: I researched the implementation with an AI agent, constantly tested the observations, and guided the development process. The actual Python coding was handled by the AI as we pair-programmed.

I am completely open-sourcing this because I want the Python and Manim community to take ownership of it, refine the codebase, and use it to its full potential. I've taken my vision as far as I can through AI pairing, and I want to hand it over to the experts without any restrictions.

## Contributing

Since I am stepping back from active Python development on this tool, **I am looking for community maintainers** to take the lead. Contributions are welcome in all areas:

- 🐛 Bug fixes and crash reports
- 🎨 UI/UX improvements
- 🧪 Test coverage expansion
- 📖 Documentation
- 🔧 New property widget types
- 🌐 Windows/Linux platform testing

Please open an issue before submitting large PRs.

## License

[MIT License](LICENSE) — use it however you want, no strings attached.
