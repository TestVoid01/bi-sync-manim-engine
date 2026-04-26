# Next Move

## Why this document exists

Yeh document hamari recent saari discussions ka consolidated conclusion hai. Iska purpose yeh hai ki hum clear tareeke se samajh sakein ki hum apne `Bi-Sync Manim Engine` ko kis direction mein le ja rahe hain, kyun le ja rahe hain, aur actual target kya hai.

Ab tak ki observation se ek baat bilkul clear hai:

- hum sirf ek property editor nahi bana rahe
- hum sirf ek AST editor bhi nahi bana rahe
- hum sirf ek Manim preview app bhi nahi bana rahe

Hum jo bana rahe hain, woh ek **intelligent visual coding system** hai jo:

- Manim code ko samjhe
- usko render kare
- uske objects ko identify kare
- unko click/drag/edit karne de
- code changes ko bhi real time mein reflect kare
- aur final truth ko source code ke saath sync rakhe

Simple language mein:

**target yeh hai ki user chahe code se kaam kare ya canvas se, system dono taraf se smart aur responsive feel ho.**

---

## Sabse pehla direct answer: kya yeh possible hai?

### Haan, possible hai.

Lekin ek important condition ke saath:

**interaction ke dauran jo user dekh raha hoga, woh hamesha source code ka direct render nahi hoga.**

Uske badle system ko ek smart layered model use karna padega:

- user ko canvas par smooth, instant, real-time preview dikhana
- background mein source ko process karna
- phir quietly real scene aur source ko sync kar dena

Yahi correct direction hai.

Iska matlab:

- agar user slider move kare
- arrow buttons press kare
- mouse se drag kare
- code editor mein value badle
- ya poora naya Manim code paste kare

tab bhi system user ko **instant visual feedback** de sakta hai

**lekin source commit, AST reconciliation, reload, export consistency background mein smart tareeke se honi chahiye.**

---

## Main strategic conclusion

### Humein apne engine ko `source-first editor` se `intent-driven visual system` mein convert karna hai.

Abhi system ka dard yeh hai ki yeh har edit ko seedha code update ki tarah treat karta hai. Isi wajah se:

- latency aati hai
- preview toot jata hai
- property panel atak jata hai
- wrong object map ho sakta hai
- reload aur export mismatch ho jata hai

Humein yeh model chhodna hoga.

Correct model yeh hona chahiye:

1. user gesture ko seedha code edit mat samjho
2. user gesture ko `edit intent` samjho
3. pehle us intent ka smooth preview dikhao
4. phir us intent ko best possible source representation mein convert karo

Yeh poore engine ka central philosophical shift hai.

---

## Ham kya bana rahe hain actually?

Hum ek aisa engine banana chahte hain jo:

- **Zero-Config** ho
- **Any valid Manim code** ko accept kar sake
- complex code par bhi crash na kare
- unknown/custom objects ko bhi at least safely select ya inspect kar sake
- source-backed editing jahan possible ho wahan kare
- jahan exact source mapping possible na ho, wahan safe fallback de
- user ko kabhi misleading control na de

Is project ka real vision ab yeh hai:

### A universal Manim intake and live manipulation engine

Jo teen cheezen ek saath kare:

1. **understand code**
2. **understand rendered scene**
3. **maintain illusion of instant editing**

---

## Real-time editing ka sahi model

Real-time experience ke liye ek hi pipeline kaafi nahi hogi. Humein alag-alag layers chahiye.

### Recommended layered architecture

#### 1. Source Truth Layer

Yeh asli `.py` file hai.

Ismein hota hai:

- user ka actual Manim code
- import structure
- constructor calls
- modifier chains
- animation calls
- helper functions
- custom classes

Yeh final export ka ultimate source hai.

#### 2. Source Analysis Layer

Yeh AST aur semantic extraction ka layer hai.

Iska kaam:

- mobject-producing expressions identify karna
- constructor, factory method, chained calls ko classify karna
- source anchors banana
- properties, params, chain metadata nikalna
- exact write targets identify karna

Yeh layer ke bina smart persistence possible nahi hai.

#### 3. Live Scene Layer

Yeh current loaded Manim scene hai.

Ismein actual runtime mobjects rehte hain:

- rendered shapes
- groups
- glyphs
- custom objects
- animation targets

Yahi canvas par draw hota hai.

#### 4. Preview Overlay Layer

Yeh sabse important layer hai.

User interaction ke dauran:

- drag
- scale feel
- live movement
- color preview
- property tweak
- temporary visual transformation

is layer mein dikhna chahiye, na ki direct source save ke through.

Yahi layer “illusion of instant editing” degi.

#### 5. Reconcile / Commit Layer

User ka kaam khatm hone ke baad:

- system decide karega edit ko source mein kaise persist karna hai
- exact AST update
- safe patch injection
- fallback override record
- full reload if needed
- final rebind and sync

Yeh layer slow ho sakti hai.

User ko issue nahi hoga, because visual feedback pehle hi mil chuka hoga.

---

## Sabse bada UX principle

### Interaction ke waqt preview truth hai.
### Export ke waqt source truth hai.

Yeh dual-truth model accept karna hoga.

Agar hum insist karenge ki user ke har frame movement ka matlab turant source edit ho, to:

- lag aayega
- sync issues aayenge
- scene rebuild tootega
- object mapping confuse hogi

Isliye:

- editing ke waqt system speculative ho
- commit ke waqt system exact ho

Yahi best architecture hai.

---

## Code editor workflow ke baare mein final conclusion

User ne ek bahut important sawal poocha:

> Agar main code panel mein poora alag Manim code paste kar doon, to kya canvas par real-time change dekhne ko mil sakta hai?

### Answer: haan, lekin “real-time” ka sahi matlab define karna hoga.

Typing aur pasting ke dauran code kai baar temporary invalid hota hai.

Example:

- import incomplete ho sakta hai
- bracket half-open ho sakti hai
- scene class incomplete ho sakti hai
- function body partial ho sakti hai
- syntax momentarily toot sakta hai

Toh har keystroke par actual rebuild karna na smart hai, na stable.

### Isliye correct model hoga:

#### A. Last Good Preview

Canvas par hamesha last valid render visible rahe.

Yani user paste karte waqt agar code 500 ms ke liye invalid ho gaya, to:

- canvas blank na ho
- app crash na ho
- property panel insane na ho
- old valid preview visible rahe

#### B. Debounced Parsing

User typing/pasting ke baad short debounce window:

- `150ms`
- `250ms`
- ya `400ms`

ke baad background parse chale.

#### C. Shadow Build

Naya code directly live scene ko destroy na kare.

Pehle:

- shadow AST build ho
- shadow source graph बने
- shadow scene construct ho
- validation ho

#### D. Atomic Swap

Agar shadow build healthy ho:

- live preview ko new scene se replace kar do
- property panel rebind karo
- selection remap karo agar possible ho
- toolbar queue refresh karo

Yeh swap smooth feel hona chahiye.

#### E. Invalid Code Handling

Agar code invalid ho:

- last good preview visible rahe
- code panel mein errors show ho
- property panel ya to freeze ho ya draft-mode mein jaye
- user ko visual chaos na mile

### Is model se kya milega?

- code paste experience smooth hoga
- typing ke beech canvas blink nahi karega
- invalid draft states app ko break nahi karengi
- valid hone par new scene rapidly visible ho jayega

Yani:

**yes, code panel based editing ko bhi bahut smooth banaya ja sakta hai.**

---

## Graphical editing aur code editing ko alag systems nahi, ek hi system banna hoga

Ab tak ka sabse important architectural conclusion yeh hai:

### Graphical editing aur code editing dono ko same canonical model par chalna hoga.

Abhi bug isi wajah se aate hain kyunki:

- code side ka source model alag behave karta hai
- canvas side ka live object model alag behave karta hai
- property panel kabhi code ko dekh raha hota hai
- kabhi live object ko
- aur kabhi stale binding ko

Correct approach:

- ek canonical scene graph
- ek canonical source anchor system
- ek canonical selection target
- ek canonical property classification

Phir user code se edit kare ya canvas se, dono same state machine se guzren.

---

## Property panel ke baare mein final conclusion

Property panel ko ab “random live attributes inspector” nahi rehna chahiye.

Usko structured aur truthful banna hoga.

### Humein property panel ko 3 lanes mein sochna chahiye:

#### 1. Source Properties

Woh properties jo directly source code mein backed hain.

Examples:

- constructor kwargs
- reliable positional args
- chained modifier args
- animation effect args

#### 2. Source Chain / Behavior

Woh cheezen jo object ke behavior ya placement ko define karti hain.

Examples:

- `next_to`
- `to_edge`
- `shift`
- `move_to`
- `scale`
- `rotate`
- animation `shift`, `run_time`, etc.

#### 3. Live Readout

Exact clicked runtime object ki current state.

Examples:

- current color
- current width
- current center
- current opacity
- child glyph ya submobject ka live state

### Important rule

Property panel ko hamesha sach bolna chahiye.

Yani:

- agar property exact source-backed hai, to editable dikhao
- agar property live-only hai, to live-readout dikhao
- agar property ambiguous hai, to reload-only ya read-only dikhao

Misleading controls nahi hone chahiye.

---

## Slider problem ka final UX conclusion

User ki observation sahi hai:

- mouse-driven slider inaccurate hota hai
- cursor drift karta hai
- overshoot hota hai
- precision kharab hoti hai

### Isliye final recommendation:

slider ko primary control mat banao

Primary control yeh hona chahiye:

- `-` button
- numeric field
- `+` button
- step selector
- optional mini-slider for coarse motion

Example:

```text
radius    [-]   1.20   [+]    step: 0.01 | 0.1 | 1
```

Aur behavior:

- left arrow = `-step`
- right arrow = `+step`
- Shift = coarse
- Alt/Option = fine
- wheel over field = incremental changes

### Real-time smoothness ke liye

button press ya arrow hold ke dauran:

- preview live ho
- source save delay/release par ho

Isse UI precise bhi hogi aur fast bhi.

---

## Universal Manim intake ke baare mein final conclusion

Yeh project tab powerful banega jab yeh kisi ek demo scene par dependent na rahe.

### Target yeh hona chahiye:

user koi bhi valid Manim code de:

- simple scene
- mathematical plot
- custom VMobject
- helper-return object
- loop-generated objects
- group/comprehension-based layout
- inline `self.add(Circle(...))`
- animation-heavy scene
- third-party/custom package object

aur engine:

- parse kar sake
- crash na kare
- jo editable hai use editable banaye
- jo exact source-backed nahi hai usko safe fallback de
- kabhi silent corruption na kare

### Degradation guarantee

Yeh bahut important principle hai:

**“accept any valid Manim code” ka matlab yeh nahi ki har cheez exact source-editable hogi.**

Iska matlab yeh hona chahiye:

- render safe
- selection safe
- inspection safe
- persistence safe

Jahan exact edit possible ho:

- exact source edit

Jahan mushkil ho:

- safe patch

Jahan woh bhi na ho:

- live read-only / override fallback

Lekin app tootni nahi chahiye.

---

## Persistence ke liye final model

Graphical ya code-based edits ko persist karne ke liye ek **persistence ladder** chahiye.

### Level 1: Exact Source Edit

Best case.

Examples:

- constructor kwarg update
- existing `move_to(...)` update
- existing `shift(...)` update
- modifier arg update
- animation arg update

### Level 2: Safe Patch Edit

Jab original expression complex ho.

Examples:

- object create hua, but exact nested structure rewrite risky hai
- to creation ke baad stable patch add karo

Jaise:

```python
obj.move_to([...])
obj.set_color(...)
```

### Level 3: Override / Sidecar Layer

Jab source exact rewrite practical na ho.

Examples:

- helper-return object
- generated object
- third-party weird factory
- nested inline object jiska stable rewrite hard ho

Tab engine temporary ya semi-persistent override record rakhe.

Final export ke time system usko merge ya apply kare.

### Why this matters

Kyuki user ne clearly kaha:

**“kuchh bhi chhutna nahi chahiye, chahe complex se complex kyon na ho”**

Is requirement ko pura karne ka practical tareeka yahi hai.

Har case exact AST rewrite se solve nahi hoga.

Lekin har case ko **persistable** banaya ja sakta hai.

---

## Selection system ke baare mein conclusion

Selection system ko simple `clicked mobject id = source object` logic par nahi chalna chahiye.

Yeh too fragile hai.

### Correct selection model:

User click kare to system ko return karna chahiye:

- exact clicked runtime object
- nearest source-backed parent
- selected source key
- editability mode
- child path

Isse:

- glyph par click karo to parent `MathTex` mil sakta hai
- VGroup child par click karo to exact child ya nearest anchored parent mil sakta hai
- custom object par click safe fallback de sakta hai

### Property panel behavior then becomes truthful:

- source controls for nearest source-backed target
- live readout for exact clicked child

Yeh current confusion ko bahut had tak solve karega.

---

## Animation editing ke baare mein conclusion

Animation ko bhi same “illusion first, reconcile later” model par lana hoga.

During drag:

- end position ya effect preview canvas par instantly dikh sakta hai

After release:

- system figure out kare:
  - `move_to`
  - `shift`
  - effect `shift`
  - chained animate call update

Yeh save-time concern hai, preview-time concern nahi.

### Key insight

Animation preview aur animation persistence ko same cheez treat nahi karna chahiye.

Preview can be approximate.
Persistence must be deliberate.

---

## Preview ke liye golden rules

### Rule 1

Preview should never depend on file save for every tiny movement.

### Rule 2

User ke har frame gesture ko AST mutation mein translate mat karo.

### Rule 3

Only latest final state matters for persistence.

### Rule 4

If source is invalid, keep last good preview alive.

### Rule 5

If exact mapping uncertain hai, degrade gracefully, mislead mat karo.

---

## What we are trying to achieve now

Ab hamara actual target ek sentence mein yeh hai:

### Build a universal, low-latency, truth-preserving Manim editing engine.

Is sentence ko todkar dekhein to hum 5 cheezen ek saath chahte hain:

#### 1. Universal Intake

Koi bhi valid Manim code accept ho.

#### 2. Instant Feeling

Canvas par edits smooth aur immediate feel hon.

#### 3. Truthful Controls

Panel kabhi jhooth na bole. Editable kya hai aur read-only kya hai, clearly samajh aaye.

#### 4. Safe Persistence

Graphical changes eventually source/export truth mein convert hon.

#### 5. Stable Recovery

Typing mistakes, invalid drafts, unknown objects, third-party classes, heavy scenes: app tootni nahi chahiye.

---

## Final conceptual model of the product

Humein apne software ko ab is tarah dekhna chahiye:

### It is not just a “property panel for Manim”.

It is:

- a scene parser
- a runtime tracker
- a speculative preview system
- a source reconciliation engine
- a safety-first persistence engine
- and a dual-mode editor for both coders and visual users

Yahi hamari real identity hai.

---

## Most important design sentence

### Interaction ke waqt illusion.
### Commit ke waqt intelligence.
### Export ke waqt truth.

Yeh hamare engine ka core doctrine hona chahiye.

---

## Practical high-level direction going forward

Without implementation detail mein jaaye bina, conceptual direction yeh honi chahiye:

1. source aur preview ko temporarily decouple karo
2. code editor ke liye last-good-preview + shadow-parse model lao
3. canvas edits ke liye speculative overlay lao
4. property panel ko truthful 3-lane model par lao
5. persistence ladder define karo: exact, patch, override
6. universal intake ko degrade-safe banao
7. selection ko nearest source-backed target model par le jao
8. reload ko atomic aur health-checked banao

---

## Final conclusion

Haan, woh future jisme:

- user canvas par drag kare aur smooth live change dekhe
- user property panel mein precise arrow/step controls se change kare
- user code panel mein value badle aur visual result quickly dekhe
- user poora naya Manim code paste kare aur engine usko safely ingest kare
- source, preview, aur export end mein sync ho jaayein

**poori tarah possible hai.**

Lekin uske liye humein incremental bug-fixing se upar uthkar architecture-level shift lena hoga.

Hum ab ek simple editor patch nahi kar rahe.

Hum ek aisa intelligent Manim system define kar rahe hain jo:

- user intent ko samjhe
- temporary illusion de
- aur final truth ko preserve kare

Yahi hamara next move hai.
