#!/usr/bin/env python3
"""
First-run setup: pick Zoha's brain and write .env.

    python setup_wizard.py

Zoha works with any model. Bigger models give better answers and tool use; small local ones keep
everything offline. You can change all of this later in the app (Settings) or in .env.
"""

from __future__ import annotations

import getpass
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent
ENV, EXAMPLE = ROOT / ".env", ROOT / ".env.example"

BRAINS = {
    "1": ("Gemini (Google, free tier available)", "gemini"),
    "2": ("Any OpenAI-compatible API (OpenAI, OpenRouter, Groq, LM Studio...)", "openai"),
    "3": ("Local Ollama model (offline, private, needs a GPU for good speed)", "local"),
}


def ask(q: str, default: str = "") -> str:
    a = input(f"{q}{f' [{default}]' if default else ''}: ").strip()
    return a or default


def main() -> None:
    print("\nZoha setup\n─────────")
    vals: dict = {}
    vals["USER_NAME"] = ask("What should Zoha call you", "friend")
    vals["HOME_CITY"] = ask("Your city (for weather and local answers)", "")
    vals["ASSISTANT_NAME"] = ask("Assistant name", "Zoha")

    print("\nWhich brain?")
    for k, (label, _) in BRAINS.items():
        print(f"  {k}. {label}")
    choice = ask("Pick 1-3", "1")
    provider = BRAINS.get(choice, BRAINS["1"])[1]
    vals["LLM_PROVIDER"] = provider

    if provider == "gemini":
        print("Free key: https://aistudio.google.com/apikey")
        vals["GEMINI_API_KEY"] = getpass.getpass("Gemini API key (hidden): ").strip()
        vals["GEMINI_MODEL"] = ask("Model", "gemini-2.5-flash")
    elif provider == "openai":
        vals["LLM_BASE_URL"] = ask("Base URL", "https://openrouter.ai/api/v1")
        vals["LLM_API_KEY"] = getpass.getpass("API key (hidden, blank for none): ").strip()
        vals["LLM_MODEL"] = ask("Model name", "openrouter/auto")
    else:
        print("Install Ollama from https://ollama.com, then run:  ollama pull <model>")
        print("Tip: 4B models handle simple commands; 8B-14B+ are much better at multi-step tasks and writing.")
        vals["LOCAL_LLM_MODEL"] = ask("Ollama model", "qwen3.5:9b")

    if provider != "local":
        fb = ask("\nUse a local Ollama model when the cloud is down or out of quota? (y/n)", "n").lower()
        vals["LLM_FALLBACK"] = "local" if fb.startswith("y") else "none"
        if fb.startswith("y"):
            vals["LOCAL_LLM_MODEL"] = ask("Fallback Ollama model", "qwen3.5:4b")

    text = (ENV if ENV.exists() else EXAMPLE).read_text(encoding="utf-8")
    for k, v in vals.items():
        line = f"{k}={v}"
        if re.search(rf"^{k}=.*$", text, re.M):
            text = re.sub(rf"^{k}=.*$", lambda _m: line, text, count=1, flags=re.M)
        else:
            text += f"\n{line}"
    ENV.write_text(text, encoding="utf-8")
    print(f"\nSaved {ENV.name}. Start Zoha with:  python gui.py   (or  python main.py --text)\n")


if __name__ == "__main__":
    main()
