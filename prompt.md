# Next Task Prompt

Dost, humne jo Bi-Sync Manim Engine banaya hai, uski foundation bilkul sahi hai, lekin abhi isme mera asali lakshya (vision) adhura hai. Abhi humare paas sirf graphical canvas hai jahan hum mouse se shapes hilate hain ya property panel ke sliders se change karte hain. Mujhe background mein code change hota hua feel nahi ho raha hai.

Main chahta hoon ki humari application mein ek naya **"Code Editor Panel"** add kiya jaye. Isko theek waise hi kaam karna chahiye jaisa main bata raha hoon:

1. **Left Side mein Code Panel:** Application ke left side par ek text editor hona chahiye jisme mera current scene ka code (`demo_scene.py`) dikhe. 
2. **Code to Graphics (Live Type):** Agar main is left panel wale code mein kuch bhi type karun (jaise main `radius=2` ko mitakar `radius=5` likhun), toh mujhe baar-baar manual "Save" na karna pade. Mere typing rokne ke aadhi second baad (debounce timer lagakar) apne aap right side wala Canvas update ho jana chahiye.
3. **Graphics to Code (Live Ghost-Typing):** Yeh sabse zaroori hissa hai. Agar main right side wale Canvas mein kisi circle ko mouse se pakad kar idhar-udhar kheenchun, toh left side ke Code Editor mein jo `x` aur `y` ke numbers hain, wo apne aap live badalte hue dikhne chahiye! Aisa lagna chahiye ki code apne aap type ho raha hai.

Mujhe kisi bhi halat mein yeh "Two-Way" (Bi-Sync) experience chahiye, jahan main code ko bhi dekh/edit sakun aur graphical UI ko bhi, aur dono ek doosre ko hamesha real-time mein update karte rahein. Tum PyQt ka koi simple text editor use karke ise MainWindow ke left dock mein jod do, aur hamare purane AST aur File Watcher logic se isko aapas mein sync kar do.
