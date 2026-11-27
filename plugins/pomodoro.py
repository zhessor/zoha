"""Example plugin: a focus timer ("start a pomodoro", "focus for 50 minutes")."""

from zoha.tools import CTX, tool


@tool("start_pomodoro", "Start a focus session timer with a break after it: 'start a pomodoro', 'focus for 50 minutes'.",
      "Focus session", "🍅", minutes=("number", "Focus length in minutes (default 25)", False),
      break_minutes=("number", "Break length in minutes (default 5)", False))
def start_pomodoro(minutes: float = 25, break_minutes: float = 5) -> str:
    focus = max(1.0, min(float(minutes or 25), 180.0))
    rest = max(1.0, min(float(break_minutes or 5), 60.0))
    CTX.schedule(focus * 60, "focus session", "timer")
    CTX.schedule((focus + rest) * 60, "break", "timer")
    return f"Focus for {focus:g} minutes. I'll tell you when to take your {rest:g}-minute break."
