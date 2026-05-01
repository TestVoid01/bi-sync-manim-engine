import sys
import time
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QTimer
import main

app = QApplication(sys.argv)
window = main.MainWindow()
window.show()

def check():
    print("Checking engine state after 3 seconds...")
    print("Health:", window.canvas._engine_state.scene_is_healthy)
    print("Render state:", window.canvas._engine_state.render_state)
    print("Animations captured:", len(window.canvas._animation_player._original_queue))
    app.quit()

QTimer.singleShot(3000, check)
app.exec()
