# Phase 5 Implementation Plan

## Step 1: AST Parser Upgrade (`engine/ast_mutator.py`)
1. **Create `ASTAnimationRef` Data Class:** 
   - Fields: `target_var` (e.g., 'circle'), `method_name` (e.g., 'move_to'), `args` (list of AST nodes or extracted values), `line_number`, `col_offset`.
2. **Update `PropertyFinder`:**
   - Add `visit_Call(self, node: ast.Call)` to detect `self.play(...)`.
   - Inside `self.play`, iterate through arguments. Detect patterns like `obj.animate.method(...)`.
   - In AST, this looks like `Call(func=Attribute(value=Attribute(value=Name(id='obj'), attr='animate'), attr='method'), args=[...])`.
   - Extract these into `self.animations: list[ASTAnimationRef]`.
3. **Update `ASTMutator`:**
   - Expose the extracted animations so other components can access them.
   - Add a `update_animation_target(target_var, method_name, new_args)` method to surgically replace the arguments of the animation call in the AST.

## Step 2: The "Ghost" Renderer (`engine/canvas.py`)
1. **EngineState additions:**
   - Add `selected_animation: Optional[ASTAnimationRef]` to track which animation the user is currently editing.
2. **Canvas Overlay:**
   - In `paintGL()`, if `engine_state.selected_animation` is set, render a translucent "Ghost" object representing the target state of that animation.
   - Alternatively, add the Ghost object to the actual Manim scene as a temporary, non-rendered (except in UI) Mobject.

## Step 3: Animation Drag Controller (`engine/drag_controller.py`)
1. **Mode Switch:**
   - Modify `mousePressEvent`, `mouseMoveEvent`, `mouseReleaseEvent` to check if we are dragging an "Initial State" or an "Animation Target (Ghost)".
2. **Delta Calculation & Vector Translation:**
   - If editing an animation target (like `move_to`), calculate the translation delta.
   - Convert absolute mouse coordinates to the appropriate relative math or absolute coordinate string (e.g., `UP * 2 + RIGHT * 3`) to rewrite into the AST.
3. **Trigger AST Update:**
   - Call `ast_mutator.update_animation_target(...)`.

## Step 4: Timeline Synchronization (`engine/animation_player.py` & GUI)
1. **Timeline UI:**
   - Add a scrubber/slider to `MainWindow` or `PropertyPanel` that binds to `animation_player.progress`.
2. **Scrubber Logic:**
   - Dragging the scrubber updates `animation_player` to pause and seek to that specific time.
   - Highlight the relevant animation in the code editor and set it as the `selected_animation` in `EngineState`.

---
*Note: We will begin by executing Step 1 first, ensuring the AST can successfully parse and mutate `.animate` calls, before moving to the visual and dragging logic.*