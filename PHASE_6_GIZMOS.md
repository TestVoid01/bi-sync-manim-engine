# Phase 6: Deep Graphical Control & Smart Gizmos

## 🎯 Objective (Lakshya)
Bi-Sync Engine ko ek basic drag-and-drop tool se upgrade karke ek advanced graphical editor mein badalna. User ko Canvas par kisi bhi complex object (jaise `Axes`, `ParametricFunction`, `VGroup`) ke har ek sub-element aur mathematical property ko mouse se control karne ki azaadi dena.

## 🏗️ Core Architectures (Kya Banana Hai)

### 1. Smart Gizmos & Bounding Boxes (Visual Handles)
**Kya Hai:** Jab kisi object ko select kiya jaye, toh uske aapas ek bounding box aaye jismein Resize (Scale) aur Rotate ke handles hon.
**AI Implementation Details:**
- **Canvas Overlay:** `engine/canvas.py` mein ek UI overlay draw karna hoga jo selected mobject ki `get_bounding_box()` values read kare.
- **AST Mapping:** Drag handles ke movement ko mathematical multipliers mein convert karke `engine/ast_mutator.py` ke through `.scale()` aur `.rotate()` calls mein inject karna hai.

### 2. Dynamic Property Inspector (Right Panel UI)
**Kya Hai:** Canvas par select kiye gaye object ki saari Python properties (jaise `color`, `stroke_width`, `radius`, `x_range`) ek UI panel mein Sliders aur Color Pickers ke roop mein dikhegi.
**AI Implementation Details:**
- **AST Kwarg Extraction:** `ASTMutator` ko upgrade karna hoga taaki wo `ast.Call` ke `keywords` (kwargs) ko read kar sake.
- **Qt Reflection UI:** Ek naya PyQt Widget (`property_inspector.py`) banana hoga jo object ka type dekh kar dynamically UI generate kare (e.g. agar property integer hai toh Slider, color hai toh Color Dialog).
- **Two-Way Binding:** Slider move hone par seedha `save_atomic()` call hona chahiye jisse file turant update ho.

### 3. Isolation Mode (Deep Hierarchy Drill-down)
**Kya Hai:** `Axes` jaise `VGroup` objects ke andar ghus kar uske sub-elements (Lines, Numbers) ko specifically select aur edit karne ki kshamata.
**AI Implementation Details:**
- **Double Click Detection:** `mouseDoubleClickEvent` in `canvas.py`.
- **HitTester Upgrade:** `engine/hit_tester.py` mein `submobjects` array ke andar recursive ray-casting add karni hogi taaki child objects ki ID return ho sake.
- **AST Target Resolution:** Sub-object modify hone par AST Mutator ko pata hona chahiye ki parent code block ke index access (e.g., `axes[0].set_color()`) ko kaise modify karna hai.

### 4. Mathematical Parametric Nodes (Sine Wave Trackers)
**Kya Hai:** `lambda x: np.sin(x)` jaise functions ko visually edit karne ke liye curve ki peak par invisible glowing tracker points.
**AI Implementation Details:**
- **Function Parsing:** `ast.Lambda` node ko parse karna aur constants/multipliers ko extract karna.
- **Virtual Dots:** Renderer mein ek virtual `Dot` pass karna jo function ke highest Y-value par snap ho. Is dot ka Y-movement amplitude multiplier update karega.

## 🛠️ Step-by-Step Execution Plan (AI Agent Roadmap)
1. **Pehle:** `property_inspector.py` banayein aur `ASTMutator` mein `extract_kwargs()` function add karein.
2. **Dusra:** `canvas.py` mein Bounding Box drawer lagayein jo `selected_mobject` ke corners par boxes render kare.
3. **Teesra:** `drag_controller.py` mein naye modes add karein: `DRAG_MODE_SCALE` aur `DRAG_MODE_ROTATE`.
4. **Chautha:** `hit_tester.py` ko deep hierarchy isolation ke liye upgrade karein.

## ⚠️ Danger Zones (Dhyan Rakhne Wali Baatein)
- `ast` library complex kwargs (e.g., nested lists like `x_range=[-3,3,1]`) ko heavily nested trees mein store karti hai. Unhe modify karte waqt code formatting break nahi honi chahiye.
- Live slider dragging 60 FPS par AST disk saves trigger karegi. SSD wear aur IDE lag bachane ke liye UI sliders mein `QTimer` debounce lagana zaroori hoga (disk save ke liye, in-memory hot-swap instantly hoga).
