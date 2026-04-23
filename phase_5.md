# Phase 5: Visual Animation Editor (The Keyframe & Timeline Era)

## Overview
Ab tak humara Bi-Sync Engine sirf objects ki **Initial State** (X,Y position, scale, color) ko drag-and-drop aur sliders ke zariye edit kar pata tha. 
**Phase 5 ka lakshya (Goal):** Manim ke animations (jaise `.animate.move_to()`, `.shift()`, etc.) ko screen par directly mouse se manipulate karna aur us manipulation ko real-time mein wapas Python AST code mein inject karna. Isse engine ek true "WYSIWYG Visual Animation Studio" ban jayega.

---

## Core Challenges & Solutions

### 1. The "Time Paradox" (State over Time)
**Problem:** Ek hi object (e.g., `circle`) poore scene mein alag-alag time par alag-alag jagah ho sakta hai. Agar user circle ko drag karta hai, toh engine ko kaise pata chalega ki user `circle.move_to(A)` (T=0s) edit kar raha hai ya `self.play(circle.animate.move_to(B))` (T=5s)?
**Solution: The Timeline/Scrubber Concept**
- Hum UI mein ek timeline ya playback scrubber banayenge.
- Scrubber ki current position (Time `t`) decide karegi ki hum kis AST node ko target kar rahe hain. 
- Agar scrubber 0s par hai, toh drag event initial definition ko modify karega. Agar scrubber animation ke time par hai, toh drag event us specific `.animate` call ko modify karega.

### 2. "Ghost" Objects (Visual Handles)
**Problem:** Animation ka final destination (End State) screen par tab tak nahi dikhta jab tak animation wahan pahunch na jaye. User usko target kaise karega?
**Solution:**
- Jab user code mein kisi animation line (jaise `circle.animate.move_to(TARGET)`) ko select karega, Canvas par ek "Ghost" version (low opacity/dashed border) render hoga jo `TARGET` position dikhayega.
- User us Ghost object ko drag karega, na ki actual object ko. Ghost drag hone par AST mein naya `TARGET` coordinate save hoga.

### 3. Absolute (Mouse) vs Relative (Code) Math
**Problem:** Mouse se aane wale coordinates hamesha absolute (X, Y) hote hain. Lekin code mein aksar relative commands hoti hain jaise `circle.shift(UP * 2)`.
**Solution: AST Vector Translator**
- `ast_mutator.py` mein naya engine likhna hoga jo `shift()` jaise relative methods ko pehchane.
- Jab mouse drag hoga, hum naye absolute coordinate aur purane absolute coordinate ka difference (Delta X, Delta Y) nikalenge, aur us difference ko wapas relative format (e.g., `RIGHT * dx + UP * dy`) mein AST mein likhenge.

---

## Step-by-Step Implementation Roadmap

### Step 1: Animation AST Parser Upgrade (The Foundation)
- **Goal:** `ast_mutator.py` ko upgrade karna taaki wo `self.play()` ke andar pass kiye gaye objects aur unke methods ko identify kar sake.
- **Action:** Ek naya function likhna jo `Call` nodes (jinka func naam `play` ho) ke arguments ko traverse kare aur `.animate` keyword ko detect karke uske aage wale methods (jaise `move_to`) ke arguments ko extract aur bind kare.

### Step 2: The "Ghost" Renderer (Canvas Upgrade)
- **Goal:** Screen par animation targets ko visual handles ke roop mein dikhana.
- **Action:** `canvas.py` mein ek overlay system banana. Agar Editor/AST report karta hai ki line 45 (an animation) selected hai, toh renderer us animation ka final state calculate karke ek translucent (Ghost) mobject draw karega jise Hit-Tester detect kar sake.

### Step 3: Animation Drag Controller
- **Goal:** Ghost object ko drag karne par AST update karna.
- **Action:** `drag_controller.py` ko extend karna. Abhi wo sirf `move_to` (initial) ko update karta hai. Naya logic check karega ki selected object "Initial" hai ya "Animation Target". Agar Animation Target hai, toh delta calculate karke AST ke animation node ko modify karega.

### Step 4: Timeline Synchronization (The Ultimate Sync)
- **Goal:** Code, Animation Player, aur Scrubber ko ek sath jodna.
- **Action:** `animation_player.py` ke progress ko UI ke naye Timeline widget ke sath sync karna. Timeline par click karne se engine us time par ruk jayega (PAUSED state) aur us time ke aaspas wale AST animation nodes ko "Editable" mark kar dega.

---

## Technical Summary
Phase 5 requires shifting `ASTMutator` from a **Static Map** (Variable -> Object) to a **Temporal State Machine** (Variable @ Time T -> Animation Node). It's a massive leap that bridges the gap between text-based coding and visual motion graphics editing.
