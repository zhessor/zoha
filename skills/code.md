---
name: code
description: Write complete, runnable code files: no stubs, a header comment, sensible structure and error handling.
---

# Skill: code files

## Rules
- Complete and runnable as written: no "...", no TODO stubs, no pseudo-code.
- Start with a 1–3 line comment: what the file does and how to run it (e.g. `python script.py input.csv`).
- Clear names; small functions; comments only where the logic isn't obvious.
- Handle the obvious failures (missing file, bad input, network error) with a clear message, not a crash.
- Never put passwords, API keys or tokens in code – read them from environment variables.
- Windows-friendly: pathlib for paths, utf-8 when reading/writing files.
- Python: standard library first; if a package is needed, say `pip install x` in the top comment.
- JavaScript: modern syntax (const/let, arrow functions, async/await), no jQuery.

## Checklist
- [ ] Runs as-is; every function used is defined; imports present
- [ ] Top comment explains purpose and how to run
- [ ] Errors handled with readable messages
- [ ] No secrets in the code
