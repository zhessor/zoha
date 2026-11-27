# Zoha plugins

Every `.py` file in this folder is loaded when Zoha starts. Use it to give Zoha new tools
without touching the core code.

```python
from zoha.tools import tool

@tool("tool_name", "When the model should use it (one clear sentence).", "Label shown in the app", "⚡",
      city=("string", "What this argument is", True))   # (type, description, required[, enum])
def tool_name(city: str) -> str:
    return "Short plain-text result for the model to summarise"
```

Rules for good plugins:
- **One job per tool**, with a description that says *when* to use it.
- **Return short text.** The model reads it and answers in its own words.
- **Never log or return secrets.** Read keys from `.env` with `os.getenv`.
- **Ask before anything that can't be undone** (sending, paying, deleting). Return a summary
  and let the user confirm, the way `zoha/site_plugin.py` does.
- Files starting with `_` are ignored, which is handy for drafts.

See `coin_and_dice.py` for a working example. Pull requests that add plugins are welcome.
