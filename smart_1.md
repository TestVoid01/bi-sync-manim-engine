# Universal Smart Property Panel: Architecture & Implementation

## 1. Core Philosophy (Smart Software, No Hardcoding)
Hum AI/Agent manually ja kar code mein ek-ek property ke liye if-else conditions ya whitelists nahi likhenge. 
Iska matlab hai ki kal ko agar koi third-party library ka object aata hai (e.g., `PhysicsObject(gravity=9.8)`), toh engine usey bhi bina sikhaye samajh lega. Engine khud Python ke level par itna smart ho jayega ki wo kisi bhi object ke DNA (attributes aur signature) ko padh sake.

## 2. Yeh Kaise Work Karega? (The Pipeline)

### Step A: Source Code Scanner (AST Mutator)
Jab bhi user code likhega (jaise `Star(n=7, color=RED)`), `ast_mutator.py` file ko as a "Text" nahi, balki ek "Abstract Syntax Tree" (AST) ki tarah padhega.
- Wo `Star` constructor dhoondhega.
- Uske andar pass kiye gaye keyword arguments (`kwargs`) extract karega.
- Result ek Dictionary hogi: `{'n': 7, 'color': 'RED'}`.
- *Yeh ensures karta hai ki user ne jo explicitly likha hai, wo hamesha GUI mein dikhe.*

### Step B: Deep Python Introspection (The Brain)
Sirf likhi hui properties hi nahi, humein wo properties bhi chahiye jo Manim background mein hide kar deta hai (Defaults).
- Hum Python ke built-in `inspect` module ka use karenge: `inspect.signature(Star.__init__)`
- Yeh command turant bata degi ki `Star` class ko `inner_radius`, `outer_radius`, aur `density` bhi chahiye, bhale hi user ne likha ho ya na likha ho.
- Result ek Complete Dictionary banegi jismein **User Kwargs + Default Kwargs + Live Object Attributes** merge ho jayenge.

### Step C: Dynamic UI Generator (Property Panel)
Ab `property_panel.py` ke paas ek aisi list hai:
`{'n': 7, 'outer_radius': 1.2, 'color': 'RED', 'fill_opacity': 0.5}`

Yeh panel ek `for` loop chalayega:
1. Agar value `int` ya `float` hai -> **Slider banao**. (e.g., `n`, `outer_radius`)
2. Agar value `bool` hai (`True/False`) -> **Checkbox banao**.
3. Agar key mein "color" word hai -> **Color Picker/Dropdown banao**.

### Step D: Bi-Directional Code Writing
Jab user GUI mein `n` ka slider 7 se 8 par drag karega:
- GUI sidhe `ast_mutator.py` ko command dega: "Line number 24 par jo `Star` hai, uski property `n` ko 8 kardo".
- AST Mutator file memory mein open karega, specifically `n=7` waale node ko dhund kar `n=8` karega, aur file save kar dega.
- Hot-swap trigger hoga aur object canvas par change ho jayega.

## 3. Implementation Steps (What to code next)

#### Phase 1: Enhance `PropertyPanel._introspect_live_mobject`
- Import `inspect`.
- Add logic to get the class of the live mobject.
- Extract `inspect.signature(cls.__init__)` to discover all allowed kwargs and their defaults.
- Filter out internal/private variables (like `**kwargs`, `self`, or properties starting with `_`).

#### Phase 2: Dynamic Type Inference in `_build_dynamic_ui`
- Ensure the logic robustly maps different Python data types to PyQt widgets.
- Add dynamic range calculation for sliders (e.g., if a default is 100, range is 0 to 200. If default is 1.0, range is 0.0 to 5.0).

#### Phase 3: Generic `HotSwap` Applier
- Ensure `hot_swap.py`'s `apply_single_property` uses `setattr` or standard `kwargs` passing to update the live object in memory without needing explicit checks for `n` or `radius`.

## Summary
The software itself becomes the "Auditor". It interrogates every object on the screen, discovers its capabilities, and automatically renders a control panel for it. This is true Zero-Configuration.
