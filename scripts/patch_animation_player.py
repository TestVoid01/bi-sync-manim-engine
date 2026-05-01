import re

with open("engine/animation_player.py", "r") as f:
    content = f.read()

method = """
    def update_snapshot(self, original_mob: Any, updater_func: Any) -> None:
        \"\"\"Applies an updater function to all snapshot copies of the given mobject.\"\"\"
        for entry in self._original_queue:
            state_snapshot = entry[3]
            if original_mob in state_snapshot:
                copied_state = state_snapshot[original_mob]
                try:
                    updater_func(copied_state)
                except Exception as e:
                    logger.warning(f"Failed to update snapshot: {e}")
"""

content = content.replace("    def play(self) -> None:", method + "\n    def play(self) -> None:")

with open("engine/animation_player.py", "w") as f:
    f.write(content)

