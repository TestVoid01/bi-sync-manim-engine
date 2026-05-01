# 🗺️ Bi-Sync Manim Engine: Complete Reading Blueprint

Welcome! This is your ultimate guide to reading and understanding the **Bi-Sync Manim Engine** from scratch. 
Do not read files randomly. Follow this **line-by-line logical path**. It is divided into 7 distinct chapters, taking you from the core brain of the engine all the way up to the graphical user interface.

*Not a single file has been missed in this blueprint.*

---

## 📖 Chapter 1: The Core Brain & Data Flow (Foundation)
*Start here. This chapter defines how the engine stores its state and reads/modifies Python code.*

1. **`engine/state.py`**
   - **Why read this first?** This is the central nervous system of the engine. It defines `EngineState`, which stores all global flags, interaction modes (idle, dragging), and the Sockets used for communication across different parts of the app.
2. **`engine/ast_mutator.py`**
   - **What it does:** The "Single Source of Truth" system. Read this to understand how the engine parses your Python code using `libcst`, injects persistent UUIDs into variables, and surgically modifies coordinates or values in the file without destroying comments.
3. **`engine/scene_sync.py`**
   - **What it does:** A small policy file that compares old and new AST (Abstract Syntax Tree) states. It decides whether a file change can be injected quickly (Hot Swap) or if the whole canvas needs to be reloaded.

---

## 🧠 Chapter 2: Identity & Object Memory (Provenance)
*How does the engine know which code line created which circle on the screen? Read these next.*

4. **`engine/property_policy.py`**
   - **What it does:** Defines which visual properties (like `color`, `radius`, `width`) can be edited for which Manim object.
5. **`engine/persistence_policy.py`**
   - **What it does:** Defines the rules for saving changes. It decides if a drag should be saved as a simple `.move_to()` chain, or if it should directly edit the object's creation arguments (e.g., `Circle(radius=5)`).
6. **`engine/runtime_provenance.py`**
   - **What it does:** Contains the data classes (`ProvenanceKey`) that represent the identity of an object across file saves.
7. **`engine/object_registry.py`**
   - **What it does:** The central database. It maps the AST tokens (from Chapter 1) to the actual running `Mobject` instances in your computer's RAM using the UUIDs.
8. **`engine/property_inspector.py`**
   - **What it does:** Uses Python's `inspect` module to dynamically look at a running `Mobject` and figure out what its default values are. This is what allows "Zero-Configuration" UI sliders.

---

## 🎨 Chapter 3: The Graphics & Rendering Pipeline (The Hijack)
*How do we steal Manim's video output and show it in a custom UI?*

9. **`engine/renderer.py`**
   - **What it does:** The `HijackedRenderer`. This is a masterpiece of hacking. It intercepts Manim's internal OpenGL calls and redirects them into our PyQt6 window instead of Manim's default window. It also recursively calculates "hitboxes" for every object on the screen.
10. **`engine/canvas.py`**
   - **What it does:** `ManimCanvas` is the actual Qt Widget you see on the screen. It owns the `HijackedRenderer`, handles the OpenGL framebuffers, and manages the lifecycle of reloading a Scene.
11. **`engine/animation_player.py`**
   - **What it does:** The Timeline. It captures Manim's `Scene.play()` calls, takes snapshots of the objects, and allows you to scrub backward and forward through animations without rerunning the code.

---

## 🖱️ Chapter 4: Interaction & Math (The Magic Canvas)
*How do mouse clicks actually move things?*

12. **`engine/coordinate_transformer.py`**
   - **What it does:** Converts your computer mouse's pixel coordinates (e.g., `x: 1080, y: 720`) into Manim's infinite 3D math space coordinates (e.g., `x: 3.5, y: -2.1`).
13. **`engine/hit_tester.py`**
   - **What it does:** Takes the math coordinates from Chapter 4 and tests them against the hitboxes generated in Chapter 3. This tells the engine *exactly* which nested `Mobject` you clicked on.
14. **`engine/drag_controller.py`**
   - **What it does:** The input brain. It listens for mouse presses, double-clicks (Isolation Mode), and drags. When you let go of the mouse, it tells `ast_mutator.py` to write the new position to your hard drive.

---

## ⚡ Chapter 5: The Synchronization Engine (Live Editing)
*How does typing in VS Code instantly update the Canvas?*

15. **`engine/file_watcher.py`**
   - **What it does:** Listens to your hard drive for changes. It contains strict locking mechanisms so that if you drag an object at the exact same millisecond you save the file in VS Code, the engine doesn't crash (Race Condition prevention).
16. **`engine/hot_swap.py`**
   - **What it does:** The `HotSwapInjector`. When you change a small number (like `run_time=2` to `run_time=3`), this file executes *just that piece of code* and injects it into the running scene without reloading everything.

---

## 🖥️ Chapter 6: User Interface (PyQt6 Components)
*The graphical panels you see on the sides.*

17. **`engine/property_panel.py`**
   - **What it does:** The Right Dock. It reads data from `property_inspector`, generates Sliders and Dropdowns dynamically, and sends your slider movements back to the engine to be saved.
18. **`engine/code_editor.py`**
   - **What it does:** The Left Dock. A built-in basic text editor that syncs perfectly with your external file.
19. **`engine/export_dialog.py`**
   - **What it does:** The window that pops up when you click "Export Video". It handles MP4/GIF rendering settings.

---

## 🔌 Chapter 7: The Wiring & The Input
*Bringing it all together.*

20. **`engine/__init__.py`**
   - **What it does:** Simply groups the engine files together so Python knows it's a package.
21. **`main.py`**
   - **What it does:** The `MainWindow`. This is where the application actually starts. It creates all the objects from the previous chapters and wires them together using PyQt Signals and Slots. 
22. **`scenes/advanced_scene.py`**
   - **What it does:** The actual user code. This is what you (the user) write, and what the engine spends its entire life trying to parse, render, and modify.
23. **`requirements.txt`**
   - **What it does:** The list of Python packages required to run the engine (`PyQt6`, `manim`, `libcst`, etc).

---

### 🎉 You're Done!
By reading the project in this exact order, you will build a mental model starting from **how data is saved**, to **how it is rendered**, to **how it is interacted with**, and finally **how it is displayed**. Happy reading!
