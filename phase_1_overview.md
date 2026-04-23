# PHASE 1 (Overview): The Master Blueprint — "Manim-Fusion" Engine

> **Source:** `r.md` Lines 1–84
> **Role:** Strategic overview. High-level architecture decisions aur reasoning.

---

## Interrogation of Agent 1's Blueprint

1. **Threading Model:** Blueprint me `Main Thread` (PyQt) aur `Sub-Process` (Manim) ka idea hai. This is a classic, safe approach, but slow. Data ko `JSON` me serialize karna, `WebSocket` pe bhejna, dusre process me deserialize karna... is process me precious milliseconds waste honge. Electron flow me latency aayegi. This is unacceptable for a 144Hz vision.
2. **GUI Framework:** `PyQt6` is a solid choice. Iske paas `QOpenGLWidget` naam ka ek brahmastra hai, jisko hum exploit karenge.
3. **Code Mutation:** `ast` (Abstract Syntax Tree) is the only correct way. Blueprint is right. `Regex` se code modify karna is like aankh band karke surgery karna—disaster guaranteed.

---

## Revised Master Blueprint: The "Manim-Fusion" Engine

### Core Philosophy:

Hum do alag processes nahi banayenge. Hum Manim aur PyQt ko ek hi process, ek hi thread me fuse kar denge. Iske liye hum ek OS-level exploit use karenge jise main "OpenGL Context Hijack" kehta hoon.

### The Winning Language Stack (Gladiator's Verdict):

* **Primary Logic & UI:** `Python 3.10+`
* **GUI & Windowing:** `PyQt6`
* **Rendering Core:** `Manim` (Specifically the modern `manim.renderer.opengl_renderer.OpenGLRenderer`)
* **Code Mutation:** Python `ast` module.

---

## High-Level Phase Descriptions

### Phase 1: The Core Rendering & GUI Fusion (RGF)

Yeh sabse critical phase hai. Hum Manim ko uski apni window banane se rokenge.

* **OS Psychology:** Normally, jab aap Manim run karte ho, toh woh OS se request karta hai, "Mujhe ek window do aur uske andar ek `OpenGL context` create karo." Similarly, `PyQt` bhi apni window aur apna `OpenGL context` banata hai. Hum yahan OS ko trick karenge.
* **The 'OpenGL Context Hijack' Technique:**

1. `PyQt` application start hogi aur ek `QOpenGLWidget` create karegi. This widget owns a powerful, hardware-accelerated `OpenGL context`.
2. Hum Manim ke `OpenGLRenderer` class ko initialize karte waqt, usko directly is `QOpenGLWidget` ka existing context pass kar denge.
3. Result: Manim sochega ki woh apni window pe draw kar raha hai, but in reality, all its `shaders`, `vertex buffers`, and `draw calls` are being piped directly into the PyQt widget.

* **Visual Flow (Electron Path):**
`User writes Manim code` -> `Python executes Scene.construct()` -> `Manim calculates shapes` -> `Manim issues OpenGL draw commands` -> **[CONTEXT HIJACK]** -> `Commands execute on PyQt's QOpenGLWidget context` -> `Pixels appear instantly in the GUI panel`.
* **Benefit:** Zero latency. No IPC, no sockets, no data serialization. Raw GPU power, controlled by Python.

### Phase 2: The Bi-Directional Sync Bridge

Yeh two-way data flow ka nervous system hai.

* **Part A: GUI -> Code (The AST Injector):**
    * **Action:** User GUI me slider se Circle ka `radius` 2 se 5 karta hai.
    * **Logic:**
        1. `PyQt` signal emit hoga: `update_property(target_variable="my_circle", property="radius", new_value=5.0)`.
        2. `ASTMutator` script ko memory me load karega.
        3. Yeh `my_circle = Circle(radius=2)` line dhoondhega.
        4. Syntax tree ko surgically modify karke `radius=5.0` set karega.
        5. Modified code ko `.py` file me save karega (persistence ke liye).
        6. **Future-Proof Hook:** Yahan ek "hot-reload" hook hoga jo Manim ko direct signal dega ki scene ko re-render karo, bina file watcher ka wait kiye.

* **Part B: Code -> GUI (The Live Reloader & State Reconciliator):**
    * **Action:** User code editor me `radius=5.0` ko manually change karke `radius=1.0` likhta hai aur save karta hai.
    * **Logic:**
        1. `QFileSystemWatcher` file change detect karega.
        2. `importlib.reload()` se updated module ko memory me reload kiya jayega.
        3. Manim scene re-render hoga, aur graphics me circle chota ho jayega.
        4. **Future-Proof Slot (CRITICAL):** GUI slider sync — "State Reconciliation" function naye code ko parse karke slider ki value update kar dega. Loop closed.

### Phase 3: The Interactive Canvas Controller

Yeh mouse se direct manipulation ka logic hai.

* **Action:** User chote circle ko mouse se drag karke nayi position pe le jaata hai.
* **Logic:**
    1. `QOpenGLWidget` mouse click event (`x, y` in pixels) capture karega.
    2. `CoordinateTransformer` pixel -> Manim math coordinates convert karega.
    3. `Hit-Tester` Manim ke sabhi `Mobjects` check karega.
    4. Dragging ke dauraan naye coordinates calculate honge.
    5. AST Injector ko coordinates feed honge, code update hoga.
    6. Code update hoga, Manim re-render karega. Real-time.

---

## Hardware & Safety Rules

1. **Strict Single-Thread:** The `OpenGL Context Hijack` forces a single-threaded architecture for rendering. This eliminates race conditions and the need for complex mutexes.
2. **Memory Safety:** Manim's `Mobject` lifecycle and PyQt's `QObject` lifecycle will be managed independently by their respective garbage collectors. The bridge is just a context pointer, which is safe.
3. **AST-Only Mutation:** Re-confirming the golden rule. File ko as a simple text/string kabhi treat nahi karna hai. All code writes MUST go through the `ast` module.
