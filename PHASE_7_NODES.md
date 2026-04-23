# Phase 7: Node-Based Visual Composer (Absolute Control)

## 🎯 Objective (Lakshya)
DaVinci Resolve Fusion ya Blender Geometry Nodes ki tarah Bi-Sync Engine mein ek Visual Data Flow Graph system banana. Jisme users ko Python code likhne ki zaroorat na ho, balki wo dibbo (Nodes) aur taaron (Wires) ko jod kar complex animations aur mathematical relations automatically generate kar sakein. Yeh engine ko text-editor se completely ek Professional Compositor mein badal dega.

## 🏗️ Core Architectures (Kya Banana Hai)

### 1. The Node Graph Interface (Bottom Panel)
**Kya Hai:** Ek visual workspace jahan blocks (Nodes) place kiye jate hain. Har node ka ek Input (Left) aur Output (Right) port hota hai.
**AI Implementation Details:**
- **Qt Integration:** `QGraphicsScene` aur `QGraphicsView` ka use karke custom Node Editor framework banana. Ya phir existing framework jaise `NodeGraphQt` ko integrate karna.
- **Node Syncing:** Canvas par jab bhi koi object create ya drag kiya jaye, to Node Graph mein automatically uska ek "Object Node" ban jana chahiye.

### 2. Node Typologies (Categories)
**Kya Hai:** Alag-alag kamo ke liye alag-alag nodes.
**AI Implementation Details:**
- **Constructor Nodes:** (e.g., `Square Node`, `Axes Node`). Yeh sidha class initialization ko darshate hain. Outputs: Geometry reference, Color, X/Y Position.
- **Modifier Nodes:** (e.g., `Scale Node`, `Shift Node`). Inputs: Object. Outputs: Modified Object.
- **Animation Nodes:** (e.g., `FadeIn`, `Transform`). Inputs: Target Object. Yeh nodes seedha `self.play()` compiler command mein tabdeel honge.
- **Relation Nodes:** (e.g., `Next To`, `Align`). Data-flow mapping banayenge jaise Node A -> Target, Node B -> Reference.

### 3. The Graph-to-AST Compiler (The Brain)
**Kya Hai:** Wires ko padh kar automatically Python syntax generate karna.
**AI Implementation Details:**
- **DAG Parsing:** Node editor ek Directed Acyclic Graph (DAG) produce karega. Ek naya compiler module (`engine/graph_compiler.py`) banana hoga jo is JSON/Dictionary format graph ko topologically sort karke valid `ast.AST` nodes mein badle.
- **Code Injection:** Generated AST ko wapas `advanced_scene.py` ki `construct()` method mein inject karna bina manually likhe gaye code ko bigade.

### 4. Visual Updaters (Always Redraw Linking)
**Kya Hai:** Do objects ki properties ko live wire se connect karna. (e.g., Dot ki position se number ka update hona).
**AI Implementation Details:**
- Agar `Dot Node` ka X-Port `MathTex Node` ke Value-Port se wire se juda hai, toh Graph Compiler automatically code mein `add_updater` ya `always_redraw` ka python closure/lambda generate karega.
- Yeh manually code likhne ke mukable 100x fast aur bug-free hoga.

## 🛠️ Step-by-Step Execution Plan (AI Agent Roadmap)
1. **Pehle:** Engine GUI ko Tri-Panel layout mein divide karein. Bottom mein `QGraphicsView` attach karein.
2. **Dusra:** Basic Node Data Classes banayein (Node, Port, Wire) aur unki drawing logic likhein.
3. **Teesra:** Two-Way Link establish karein. Canvas par banaye gaye objects ka automatically node ban jana.
4. **Chautha:** Ek prototype `GraphCompiler` banayein jo sirph "Shape Node" + "Animation Node" ki wire ko `self.play(Create(shape))` mein compile kare.
5. **Panchva:** Relations (next_to) aur Updaters ka support add karein.

## ⚠️ Danger Zones (Dhyan Rakhne Wali Baatein)
- **Spaghetti Code:** Graph se generate hone wala Python code insaano ke padhne layaq (Human-readable) hona chahiye. AST compilation strict formatting conventions follow karni chahiye.
- **Performance Overhead:** Node Graph lagataar state updates bhejega. PyQt ka `QGraphicsScene` optimized hona chahiye taaki drag karne par FPS drop na ho.
- **Infinite Loops:** Node wires mein cyclic connections (A -> B -> A) detect aur block karni hongi, warna Python recursion limit hit ho jayegi aur engine crash ho jayega.
