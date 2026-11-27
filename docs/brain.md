# Choosing a brain

Zoha doesn't ship a model. Pick one in `setup_wizard.py`, or edit `.env`:

| Brain | Set | Also set |
|---|---|---|
| Gemini | `LLM_PROVIDER=gemini` | `GEMINI_API_KEY`, `GEMINI_MODEL` |
| Any OpenAI-compatible API (OpenRouter, OpenAI, ...) | `LLM_PROVIDER=openai` | `LLM_BASE_URL`, `LLM_API_KEY`, `LLM_MODEL` |
| Local model (Ollama) | `LLM_PROVIDER=local` | `LOCAL_LLM_URL`, `LOCAL_LLM_MODEL` (for example `qwen3.5:4b`) |

`LLM_FALLBACK` names a second brain to switch to when the first runs out of quota or is offline (`none` turns it off). Simple commands such as open, volume and time are also handled by Zoha's built-in parser before any model is called.
