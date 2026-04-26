# Next Move Decomposition — Stability-First Small Slices

## Summary
- Chosen defaults:
  - `Stability First`
  - `Small Slices`
- `next move.md` ko ab ek bade architecture vision ke roop mein nahi, balki 8 sequential implementation slices ke roop mein execute karna chahiye.
- Har slice:
  - independently testable hoga
  - previous slice par depend karega
  - ek clear user-facing pain ko reduce karega
  - next slice ke liye base banayega
- Rule:
  - koi bhi later slice start nahi hogi jab tak previous slice ka manual + automated acceptance pass na ho.

## Slice Breakdown

### Slice 1 — Render Health + Unified Reload Lifecycle
- Goal:
  - startup, refresh, code-triggered reload, aur play-reset ke baad canvas reliably visible rahe
  - black/yellow/stale frame bugs eliminate hon
- Main changes:
  - one render-health state machine
  - one unified reload-finalization path
  - interaction gating until preview healthy
  - toolbar reset/sync same path se ho
- Success criteria:
  - fresh launch par scene visible ho without extra click
  - `Refresh` ke baad scene visible rahe
  - `Play` ke baad completion state correct ho aur canvas stale na ho

### Slice 2 — Selection Truth + Property Panel Rebinding
- Goal:
  - jis object par click ho, wahi panel mein aaye
  - panel ek hi object par stuck na rahe
  - wrong-object move/save bug khatam ho
- Main changes:
  - raw hit id ke badle canonical `SelectionTarget`
  - nearest AST-backed parent resolution
  - exact clicked live child + selected source target dono carry karna
  - reload ke baad selection rebind by source identity, not stale runtime ids
- Success criteria:
  - visible `circle`, `dot`, `curve`, `MathTex` objects select hon
  - panel हर click par correctly update ho
  - empty space click cleanly selection clear kare

### Slice 3 — Property Safety Policy
- Goal:
  - panel truthful bane: live-safe, preview-only, reload-only, read-only
  - dangerous geometry edits live path se source corruption na karein
- Main changes:
  - central `PropertyApplyDecision`
  - transformed size props like `radius`, `width`, `height`, `font_size` ambiguous case mein reload-only
  - unsupported props editable dikhe hi nahi ya explicit read-only reason ke saath dikhe
  - panel labeling clear ho, e.g. `radius (base)` vs live readout
- Success criteria:
  - `dot`/`circle` size explosion bug band ho
  - slider/property changes ka semantics preview, refresh, export mein consistent ho
  - misleading controls remove ho

### Slice 4 — Persistence Ladder + Export Truth
- Goal:
  - graphical ya panel edit ka final exported result wahi ho jo user ne kiya
  - save pipeline source ko silently corrupt na kare
- Main changes:
  - three persistence strategies:
    - exact source edit
    - safe post-creation patch
    - read-only / fallback no-persist
  - export preflight always pending edits commit kare
  - AST writes exact source anchors se ho, heuristic line-only writes se nahi
- Success criteria:
  - drag, property change, aur export aligned hon
  - invalid constructor kwarg corruption repeat na ho
  - helper/unmapped objects kabhi accidental source write trigger na karein

### Slice 5 — Code Editor Live Preview Backbone
- Goal:
  - code panel mein typing/paste karte waqt experience stable aur fast ho
  - invalid in-between code se app break na ho
- Main changes:
  - `last good preview`
  - debounced parse
  - shadow build of AST + scene
  - successful build par atomic scene swap
  - invalid code par preview freeze, not crash/blank
- Success criteria:
  - user poora naya valid Manim code paste kare to preview quickly update ho
  - temporary invalid code ke dauran old preview visible rahe
  - property panel aur toolbar only on valid swap update hon

### Slice 6 — Speculative Preview Overlay
- Goal:
  - drag, step buttons, slider movement, aur quick property tweaks smooth feel den
  - har tiny movement par source write na ho
- Main changes:
  - preview overlay / edit session model
  - interaction-time visual changes live scene ya overlay par show hon
  - commit on release / debounce end
  - source reconciliation async ya deferred ho
- Success criteria:
  - drag smooth ho
  - panel adjustment continuous preview de
  - source save only final intent ko persist kare

### Slice 7 — Universal Manim Intake Scene Graph
- Goal:
  - app sirf top-level `name = Constructor(...)` code par depend na rahe
  - any valid Manim code safe tarike se ingest ho
- Main changes:
  - `SourceAnchor` + `SceneNodeRef` based AST scene graph
  - support:
    - direct constructors
    - chained expressions
    - factory-returned mobjects like `axes.plot(...)`
    - inline objects in `self.add(...)`, `VGroup(...)`, `self.play(...)`
    - custom / third-party Mobjects
  - non-mobject computations filter out hon
  - helper-return objects safe read-only fallback mein jayein
- Success criteria:
  - different Manim scenes parse without engine confusion
  - `No Property` cases sharply reduce hon
  - inline / chained / factory objects at least truthful selectable hon

### Slice 8 — Precision Control UX
- Goal:
  - slider-only interaction ki jagah accurate, low-friction editing experience dena
- Main changes:
  - hybrid control row:
    - `-`
    - numeric field
    - `+`
    - step selector
    - optional mini-slider for coarse edits
  - keyboard arrow support
  - `Shift` coarse, `Alt/Option` fine adjustment
  - per-property default steps
- Success criteria:
  - user exact increments se edit kar sake
  - mouse drift problem largely remove ho
  - live preview + precise stepping ek saath mile




## Test Plan
- Slice 1:
  - fresh launch, refresh, play/reset on real app
  - no black/yellow/stale canvas
- Slice 2:
  - click `circle`, `dot`, `curve`, equation glyph region
  - panel target must change correctly every time
- Slice 3:
  - radius/width/font-size edits on transformed and non-transformed objects
  - no size explosion after refresh
- Slice 4:
  - drag + property edit + export round-trip
  - exported video matches final visible committed state
- Slice 5:
  - paste entirely different valid Manim scene
  - type temporary syntax error and recover
- Slice 6:
  - continuous drag and rapid step changes feel smooth
  - source file changes only after release/debounce
- Slice 7:
  - chained assignment, `axes.plot`, `self.add(Circle(...))`, `VGroup(...)`, helper-return, custom Mobject, loop-generated objects
- Slice 8:
  - arrow buttons, keyboard arrows, step sizes `0.01`, `0.1`, `1`
  - coarse vs fine changes verified visually --yolo

## Assumptions
- Correctness-first policy locked hai:
  - ambiguous edits ko read-only ya reload-only banana acceptable hai
- Universal support ka v1 meaning:
  - any valid Manim code should load safely
  - exact source editing only where anchor reliable ho
  - otherwise graceful fallback
- Smooth UX ka v1 meaning:
  - perceptually instant preview
  - not necessarily true source mutation on every frame
- Sequence lock:
  - pehle stability backbone
  - phir truthful selection/panel
  - phir safe persistence
  - phir code-preview and universal intake
  - phir UX polish  
