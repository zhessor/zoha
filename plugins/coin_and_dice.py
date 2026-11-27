"""Example plugin: coin flips and dice rolls. Copy this file to start your own."""
import random

from zoha.tools import tool


@tool("coin_flip", "Flip a coin when the user asks for heads or tails or a coin toss.", "Flipping a coin", "🪙")
def coin_flip() -> str:
    return random.choice(["Heads", "Tails"])


@tool("roll_dice", "Roll dice, e.g. 'roll a die' or 'roll two dice'.", "Rolling dice", "🎲",
      count=("integer", "How many dice (1-10), default 1", False),
      sides=("integer", "Sides per die, default 6", False))
def roll_dice(count: int = 1, sides: int = 6) -> str:
    count, sides = max(1, min(10, int(count or 1))), max(2, min(100, int(sides or 6)))
    rolls = [random.randint(1, sides) for _ in range(count)]
    return f"Rolled {rolls}" + (f", total {sum(rolls)}" if count > 1 else "")
