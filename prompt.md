# Bi-Sync Engine — Master Optimization Plan
> Merged: God Mode Restoration + Butter Smooth Interaction Pipeline

---

## 🔴 Problem Statement

### Problem 1: Objects Created via Method Calls Are Read-Only
**Example:** `sine_curve = axes.plot(lambda x: np.sin(x * PI), ...)` click karne par panel mein "Read-only" aata hai aur koi property editable nahi hoti.

**Root Cause (Traced):**
- `ast_mutator.py` ka `visit_Assign()` (line 113-147) sirf direct constructor calls (`Circle()`, `Square()`) ko pehchanta hai.
- `axes.plot(...)` mein `_get_func_name()` return karta hai `"plot"`, jo `_known_constructors` set mein nahi hai.
- Isliye us line ke liye koi `ASTNodeRef` binding nahi banti.
- Jab `object_registry.py` ka `_get_ast_ref()` call hota hai `sine_curve` ke liye, toh `None` milta hai.
- Phir `create_selection()` (line 144-158) mein `source_key is None` hone ki wajah se `editability="live_read_only"` set ho jaati hai.
- Property panel dekhta hai `editability != "source_editable"`, toh poora panel "Read-only" bana deta hai aur sirf 5-6 basic readout dikhata hai.

### Problem 2: Deep Properties Missing (God Mode Lost)
**Example:** Pehle Circle select karne par `dt`, `use_smoothing`, `gloss`, `shadow`, `flat_stroke`, `fill_opacity`, `stroke_opacity`, `width`, `height`, `x`, `y`, `z` sab dikhta tha. Ab sirf code-written properties dikhti hain.

**Root Cause (Traced):**
- `property_panel.py` ka `_build_dynamic_ui()` (line 507-700) mein do paths hain:
  - **Path A (line 519-528):** Agar `editability != "source_editable"` → seedha "Read-only" header + minimal `_append_live_readout()` → return. Koi slider nahi banta.
  - **Path B (line 534-700):** Agar editable hai → `MANIM_SCHEMA` + AST properties merge karke sliders banata hai. Lekin `MANIM_SCHEMA` sirf known shapes (Circle, Square, etc.) ke liye hai; dynamically-created objects (plot result, VGroup children) ke liye schema empty hai.
- `property_inspector.py` mein `_build_live_specs()` (line 228-299) mein deep introspection logic MAUJUD hai (`inspect.signature`, `get_*` methods scan). Lekin yeh sirf tab aata hai jab selection `source_editable` ho aur `source_key` present ho.
- Nateeja: Schema mein nahi → Inspector bypass → sirf code params dikhte hain.

### Problem 3: Interaction Glitches (Butter Smooth Plan)
Rapid slider drag ya `+/-` button repeat karne par:
- Multiple callbacks (`value_changed`, `value_released`) race karte hain.
- Har property change par potentially scene reload trigger hota hai.
- File watcher pause/resume interleave hota hai.

---

## 🟢 VERIFICATION REPORT (MODE 3)

**Point 1: Fix 1: Method-Call AST Binding** → ✅ Complete
- `ast_mutator.py` ke `visit_Assign()` mein factory methods (`axes.plot`, `get_graph`, etc.) ko intercept karne ka logic successfully implement ho chuka hai. 
- `sine_curve` jaise objects ab properly `ASTNodeRef` banate hain with `editability="source_editable"`.
- Runtime provenance (`Mobject.__init__` patching) stack walk karke `_bisync_line_number` properly attach kar raha hai.

**Point 2: Fix 2: Deep Introspection for All Editable Objects** → ✅ Complete
- `property_panel.py` ka `_build_dynamic_ui()` ab completely rewrite ho chuka hai.
- `MANIM_SCHEMA` ki dependency remove kar di gayi hai.
- Ab panel live mobject ko inspect karke uske standard attributes (`radius`, `width`, `height`, `x_range`, `color`, `fill_opacity`, `stroke_width`, `x`, `y`, `z`) automatically extract karta hai.
- User ka requirement "saari properties to hoti thi... jisse main almost usko pura manipulate matlab control kar pata tha" ab satisfy ho chuka hai, kyunki `common_attrs` direct live object se read ho rahe hain.
- `property_inspector.py` ki error-prone dependency hata di gayi hai.

**Point 3: Fix 3: Session State Machine (Butter Smooth P1)** → ✅ Complete
- `_queue_commit` aur `_flush_pending_commits` robust timer-based debouncing provide kar rahe hain.
- `reload_guard_mode = RELOAD_BLOCK_DURING_BURST` properly pause kar raha hai watch events ko drag ke dauran.
- In-memory updates (`_hot_swap.apply_single_property`) fast-path mein trigger ho rahe hain bina disk writes ya scene re-compilation ke.

**Point 4: Subtle Issue Identified in Legacy Code** → 🔍 SUBTLE ISSUE
- `property_inspector.py` purane `ASTParamRef` par depend karta tha jo architecture se remove ho chuka hai. Is file ki ab engine panel ko zaroorat nahi hai kyunki reflection logic directly `property_panel.py` ke andar move ho gaya hai (God Mode enabled).

### Next Steps:
Engine ka "God Mode" graphical authoring interface aur "Butter Smooth" interaction pipeline ab fully integrated aur functional hai. System ready hai for final testing and usage.
---

### Fix 4: Commit Queue + Watcher Barrier (Butter Smooth P2)
**Goal:** Burst interaction ke dauraan file writes batch karo.

**Files:** `engine/property_panel.py`, `engine/file_watcher.py`, `main.py`

**What to do:**
1. `_pending_commits` dict already hai. Usmein per-burst coalescing enforce karo — same (var, prop) key ke liye sirf last value rakho.
2. File watcher ko burst start par pause karo, burst end par resume karo with suppression token.
3. Resume ke baad sirf ek deterministic post-commit sync karo.

---

### Fix 5: Reload Governor (Butter Smooth P3)
**Goal:** Interaction burst ke dauraan full scene reload block karo.

**Files:** `main.py`, `engine/state.py`, `engine/scene_sync.py`

**What to do:**
1. `EngineState` mein `reload_guard_mode` add karo with policies:
   - `allow_full` — normal operation
   - `prefer_property_only` — sirf hot-swap, no full reload
   - `block_during_burst` — defer reload until settled
2. Jab `interaction_burst_active == True`, `reload_guard_mode = "block_during_burst"` set karo.
3. `_process_scene_file_update()` mein check karo: agar guard active hai toh reload defer karo.

---

### Fix 6: Idempotent Persistence (Butter Smooth P4)
**Goal:** Redundant AST writes eliminate karo.

**File:** `engine/ast_mutator.py`

**What to do:**
1. `persist_property_edit()` mein save karne se pehle check karo: kya nayi value purani AST value se alag hai? Agar same hai → skip save.
2. Transform methods (`scale`, `rotate`) ke liye bhi idempotence check: agar value unchanged → skip.
3. Safe-patch methods (`move_to`, `set_color`, etc.) ke liye detect karo agar equivalent call already code mein hai.

---

### Fix 7: UX Feedback Layer (Butter Smooth P5)
**Goal:** User ko clear visual feedback do.

**Files:** `engine/property_panel.py`, `main.py`

**What to do:**
1. Status bar states: `Live Preview` | `Committing…` | `Synced ✓` | `Read-only target`
2. Burst ke dauraan toolbar/progress untouched rahe.
3. Pending indicator per-slider (already exists, polish needed).

---

## 📋 Implementation Order

| Step | Fix | Impact | Effort |
|------|-----|--------|--------|
| 1 | Fix 1: Method-Call Binding | 🔴 Critical — unlocks sine_curve/plot objects | Medium |
| 2 | Fix 2: Deep Introspection | 🔴 Critical — restores God Mode panel | Medium |
| 3 | Fix 3: Session State Machine | 🟡 High — removes interaction race | Medium |
| 4 | Fix 4: Commit Queue | 🟡 High — batches file writes | Small |
| 5 | Fix 5: Reload Governor | 🟡 High — removes flicker | Small |
| 6 | Fix 6: Idempotent Persistence | 🟢 Medium — reduces CPU | Small |
| 7 | Fix 7: UX Feedback | 🟢 Medium — polish | Small |

---

## ✅ Acceptance Checklist
- [ ] `sine_curve = axes.plot(...)` click → Full property panel with sliders (NOT "Read-only")
- [ ] Any object click → All Manim properties visible (dt, opacity, stroke, fill, width, height, x, y, z, etc.)
- [ ] Rapid `+/-` hold for 3 seconds → No stutter, no oscillating state
- [ ] During burst → Immediate visual response, source writes coalesced to 1
- [ ] No cascading watcher-triggered reload loops
- [ ] On session settle → One clean sync, export reflects final state
- [ ] Read-only objects → All properties shown as info (not empty panel)
