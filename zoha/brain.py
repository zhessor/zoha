"""
The brain: streaming LLM + tool calling.

Providers
  gemini  – Google Gemini via google-genai (free tier works). Native function calling.
  openai  – any OpenAI-compatible endpoint: OpenRouter (free models), Ollama/LM Studio
            on the RTX 5060 (fully offline), Groq, etc.

`Brain.run()` is an async generator of events:
  ("text", delta) · ("tool_start", name, args) · ("tool_end", name, result) · ("done", full_text)
"""

from __future__ import annotations

import asyncio
import datetime as dt
import json
import logging
import re
import time
import platform
from typing import Any, AsyncIterator, Dict, List, Optional

from . import tools as T

log = logging.getLogger("zoha.brain")
MAX_STEPS = 24  # browser tasks take many small steps


def turn_context(settings, awareness: str = "", extra: str = "") -> str:
    """The parts that change every turn (time, live PC state, recalled memories). Kept OUT of the system prompt so
    the long, unchanging start of the prompt is identical every time and Ollama can reuse it (~1 s saved per reply)."""
    now = dt.datetime.now()
    parts = [f"Now: {now:%A %d %B %Y, %I:%M %p} (local time)."]
    if awareness:
        parts.append('Live state of the PC right now (use it to understand vague requests like "pause it", '
                     '"make it full screen", "close that"):\n' + awareness)
    if extra:
        parts.append(extra)
    return "\n\n".join(parts)


def system_prompt(settings, memory, modality: str, awareness: str = "", dynamic: bool = True) -> str:
    now = dt.datetime.now()
    facts = memory.facts_text() if memory else ""
    voice = modality == "voice"
    style = (
        "You are speaking out loud. Reply like a sharp human assistant on a call: usually 1-3 short sentences, "
        "no markdown, no lists, no emojis, no URLs read out. Numbers and units written the way you'd say them. "
        "If the user explicitly asks for detail, a story, or an explanation, go longer but keep it flowing as speech. "
        "If the answer genuinely needs code or a table, give one spoken sentence and then the code block — it is shown on screen, not read aloud."
        if voice else
        "The user typed this. Markdown is fine (it renders in the chat). Be complete but tight."
    )
    return f"""You are {settings.assistant_name}, {settings.user_name}'s personal AI assistant on their {platform.system()} PC — in the spirit of JARVIS: calm, quick, quietly witty, fiercely competent, loyal. Open-source assistant made by Zhessor.

{('Now: ' + format(now, '%A %d %B %Y, %I:%M %p') + ' (local time). ') if dynamic else ''}Home city: {settings.home_city}. The current time and the live state of the PC are given with each message.

How you work:
- You can act on the computer through tools. When the user asks you to DO something (open, play, close, search, remind, type, check, find, remember), call the right tool — don't describe what you would do. Chain tools if needed (e.g. find_files then open_path).
- After a tool runs, confirm in a few words ("Done — Spotify's open."). Never read raw tool output verbatim; summarise it. Don't repeat details you already said earlier, and don't tack on "Need anything else?".
- If the website plugin is set up, the site_* tools read and change the user's own website/CMS (content, enquiries, analytics, change history); propose changes with site_propose and reply to enquiries with site_enquiry_reply – the user always confirms with a yes, you never apply or send anything yourself. Making, redesigning or improving a website/landing page for a business (gym, café, salon…) is FILE work: write_file for a new page, improve_file for the page you just made (no filename needed) – NEVER site_* tools.
- In your browser, the user only sees what's under "On screen right now" – never say you can see a section unless it is listed there.
- If a tool returns an Error, say briefly what went wrong and offer the next best thing.
- NEVER say you saved, deleted, opened, set, changed or "noted" anything unless you called the matching tool in this turn and it succeeded. If the user corrects something you said, apologise briefly and fix it — use remember/forget only if it concerns stored facts.
- Web results about a person may be about someone else with the same name. Only state what clearly matches {settings.user_name} (e.g. their city or work) and say plainly when you're not sure it's them.
- For anything current or after your training data (news, prices, scores, recent releases, "latest"), use web_lookup or news_headlines before answering. Don't guess dates or facts.
- "The browser" / "your browser" / "start the browser" ALWAYS means YOUR OWN browser: use browser_open (not open_website). Once it's open, keep using browser_* tools for that conversation.
- You have your OWN browser window (browser_* tools, Playwright). Use it whenever a task needs reading or acting ON a website: filling forms, searching inside a site, checking an order/booking/status, comparing products, reading an article, logging into a dashboard, etc. Use open_website/play_youtube only to simply show something.
  How: browser_open → read the numbered elements → browser_click / browser_type with the [ref] numbers → every action returns a fresh snapshot and the numbers CHANGE after each action, so always use the latest ones. Scroll if what you need isn't listed. Keep going step by step until the job is done, then report the result in a sentence or two (don't narrate every click when speaking).
  Never type passwords, OTPs, card or bank details — ask {settings.user_name} to enter them in the browser window and tell you when done. If you hit a captcha or login wall, say so and wait. Before an irreversible step (pay, place order, send, post, delete, submit an application) stop and ask; only then click with confirmed=true.
- Destructive or irreversible actions (shutdown, restart, closing apps with unsaved work) need a clear yes from the user first.
- If the request is ambiguous and a wrong guess would be costly, ask one short question. Otherwise just act.
- Speech-to-text can mishear: interpret the user's words charitably (e.g. "open crome" → Chrome, "play lo fi" → lofi).
- Address the user by name occasionally, not every reply. No filler like "As an AI".
{style}
{('What you know about ' + settings.user_name + ':' + chr(10) + facts) if facts else ''}
{settings.extra_instructions}
{('Live state of the PC right now (use it to understand vague requests like "pause it", "make it full screen", "close that"):' + chr(10) + awareness) if (awareness and dynamic) else ''}""".strip()


class Brain:
    def __init__(self, settings, memory):
        self.s = settings
        self.memory = memory
        self.provider = settings.llm_provider
        self._client = None
        self._clients: Dict[str, Any] = {}
        self._available_models: Optional[List[str]] = None
        self.model = {"gemini": settings.gemini_model, "local": settings.local_llm_model}.get(self.provider, settings.llm_model)
        self.gemini_cooldown_until = 0.0
        self._local_checked = 0.0
        self._local_ok = False
        self._recent_tools: set = set()
        self.awareness = ""  # filled by the engine before each turn
        self.turn_flags: List[str] = []  # lie-guard events of the current turn (for the journal)
        self._think_switch = True
        self.local_thinks = True  # updated from the model's capabilities once Ollama is ready
        self.local_runtime_model = settings.local_llm_model  # replaced by the tuned "zoha-…" model once prepared
        self.last_used = self.label()

    def label(self, which: Optional[str] = None) -> str:
        which = which or self.provider
        if which == "gemini":
            return self.model if self.provider == "gemini" else self.s.gemini_model
        if which == "local":
            return f"{self.s.local_llm_model} (local)"
        return self.s.llm_model

    def vision_fn(self, local_caps=None):
        """A blocking callable(prompt, jpeg_bytes) -> str for the active brain, or None if it can't see."""
        import base64

        if self.provider == "gemini" and self.s.gemini_api_key:
            def gemini_see(prompt, img):
                from google import genai
                from google.genai import types

                client = genai.Client(api_key=self.s.gemini_api_key)
                r = client.models.generate_content(model=self.model, contents=[
                    types.Part.from_bytes(data=img, mime_type="image/jpeg"), prompt])
                return (r.text or "").strip()
            return gemini_see
        if self.provider == "local" and local_caps is not None:
            own = "vision" in local_caps
            helper = (self.s.local_vision_model or "").strip()
            if not own and (not helper or helper == self.local_runtime_model):
                return None
            see_model = self.local_runtime_model if own else helper   # borrowed eyes: only for the look itself

            def ollama_see(prompt, img):
                import urllib.request

                root = self.s.local_llm_url.rstrip("/")
                root = root[:-3] if root.endswith("/v1") else root
                body = {"model": see_model, "stream": False, "keep_alive": "30m" if own else "2m",
                        "messages": [{"role": "user", "content": prompt, "images": [base64.b64encode(img).decode()]}],
                        "options": {"temperature": 0.2, "num_ctx": int(self.s.local_llm_ctx), "num_predict": 200}}
                if self.local_thinks or not own:
                    body["think"] = False
                req = urllib.request.Request(root + "/api/chat", data=json.dumps(body).encode(),
                                             headers={"Content-Type": "application/json"})
                with urllib.request.urlopen(req, timeout=120) as r:
                    msg = json.loads(r.read().decode()).get("message") or {}
                return _ThinkFilter().feed(msg.get("content") or "").strip()
            return ollama_see
        return None

    def text_fn(self):
        """A blocking callable(prompt) -> str: plain text from the active brain, no tools.
        Used by write_file so long code never travels inside a tool call (Ollama's tool-call
        parser breaks on HTML/XML in arguments)."""
        if self.provider == "gemini" and self.s.gemini_api_key:
            def gemini_write(prompt, think=False, temperature=0.4):
                from google import genai
                client = genai.Client(api_key=self.s.gemini_api_key)
                return (client.models.generate_content(model=self.model, contents=[prompt]).text or "")
            return gemini_write
        if self.provider == "local":
            def ollama_write(prompt, think=False, temperature=0.4):
                import urllib.request
                root = self.s.local_llm_url.rstrip("/")
                root = root[:-3] if root.endswith("/v1") else root
                body = {"model": self.local_runtime_model, "stream": False, "keep_alive": "30m",
                        "messages": [{"role": "user", "content": prompt}],
                        "options": {"temperature": float(temperature), "num_ctx": max(int(self.s.local_llm_ctx), 24576),
                                    "num_predict": 9000 if think else 6000}}
                if self.local_thinks:
                    body["think"] = bool(think)   # plan first (layout, sections, colours) only for fresh drafts
                req = urllib.request.Request(root + "/api/chat", data=json.dumps(body).encode(),
                                             headers={"Content-Type": "application/json"})
                with urllib.request.urlopen(req, timeout=300) as r:
                    msg = json.loads(r.read().decode()).get("message") or {}
                return _ThinkFilter().feed(msg.get("content") or "")
            return ollama_write
        return None

    async def local_available(self) -> bool:
        """Is Ollama (or another local server) answering? Cached for 30 s."""
        if time.time() - self._local_checked < 30:
            return self._local_ok
        self._local_checked = time.time()
        base = self.s.local_llm_url.rstrip("/")
        root = base[:-3] if base.endswith("/v1") else base
        def probe():
            import urllib.request

            try:
                with urllib.request.urlopen(root + "/api/tags", timeout=1.5) as r:
                    data = json.loads(r.read().decode())
                names = [m.get("name", "") for m in data.get("models", [])]
                want = self.s.local_llm_model
                return any(n == want or n.split(":")[0] == want.split(":")[0] for n in names) if names else False
            except Exception:
                try:
                    with urllib.request.urlopen(base + "/models", timeout=1.5):
                        return True
                except Exception:
                    return False
        self._local_ok = await asyncio.to_thread(probe)
        return self._local_ok

    # ------------------------------------------------------------------
    def _history(self) -> List[Dict[str, str]]:
        return self.memory.recent() if self.memory else []

    async def run(self, user_text: str, modality: str = "voice") -> AsyncIterator[tuple]:
        self.turn_flags = []
        extra = ""
        try:
            from . import learn
            extra = learn.get().prompt_context(user_text, self.memory)
        except Exception:
            log.exception("learned context failed")
        # local model: unchanging system prompt (cache-friendly) + per-turn context sent with the message.
        # cloud models: everything in the system prompt, as before.
        self._static_prompt = system_prompt(self.s, self.memory, modality, dynamic=False)
        self._turn_context = turn_context(self.s, self.awareness, extra)
        sys_prompt = system_prompt(self.s, self.memory, modality, self.awareness) + ("\n\n" + extra if extra else "")
        full: List[str] = []

        async def drive(gen, label):
            self.last_used = label
            async for ev in gen:
                if ev[0] == "text":
                    full.append(ev[1])
                yield ev

        use_local_fallback = self.s.llm_fallback == "local" and self.provider != "local"
        if self.provider == "gemini" and time.time() < self.gemini_cooldown_until and use_local_fallback \
                and await self.local_available():
            yield ("notice", f"Gemini is cooling down ({self._cooldown_text()}), so I'm using {self.label('local')}.")
            async for ev in drive(self._run_ollama(user_text, sys_prompt, modality), self.label("local")):
                yield ev
            yield ("done", "".join(full).strip())
            return

        primary = (self._run_gemini(user_text, sys_prompt) if self.provider == "gemini"
                   else self._run_ollama(user_text, sys_prompt, modality) if self.provider == "local"
                   else self._run_openai(user_text, sys_prompt, self.provider))
        produced = 0
        try:
            async for ev in drive(primary, self.label()):
                produced += 1
                yield ev
        except Exception as e:
            self._note_failure(e)
            if produced == 0 and use_local_fallback and await self.local_available():
                log.warning("Primary brain failed (%s) – falling back to local model", str(e)[:160])
                yield ("notice", f"{_why(e)} Switching to {self.label('local')}.")
                async for ev in drive(self._run_ollama(user_text, sys_prompt, modality), self.label("local")):
                    yield ev
            else:
                raise
        yield ("done", "".join(full).strip())

    def _note_failure(self, e: Exception):
        msg = str(e)
        if self.provider != "gemini":
            return
        if ("429" in msg or "RESOURCE_EXHAUSTED" in msg) and ("PerDay" in msg or "per day" in msg.lower()):
            # daily quota resets at midnight Pacific time
            import datetime as _dt

            now = _dt.datetime.now(_dt.timezone.utc)
            pt = now - _dt.timedelta(hours=8)
            reset = (pt.replace(hour=0, minute=0, second=0, microsecond=0) + _dt.timedelta(days=1) + _dt.timedelta(hours=8))
            self.gemini_cooldown_until = reset.timestamp()
        elif "429" in msg or "RESOURCE_EXHAUSTED" in msg:
            self.gemini_cooldown_until = time.time() + _retry_delay(msg, 60)
        elif any(k in msg for k in ("503", "UNAVAILABLE", "overloaded", "high demand")):
            self.gemini_cooldown_until = time.time() + 45

    def _cooldown_text(self) -> str:
        left = max(0, int(self.gemini_cooldown_until - time.time()))
        return f"{left // 3600}h {left % 3600 // 60}m left" if left > 3600 else f"{left}s left"

    # ── Gemini ────────────────────────────────────────────────────────
    def _gemini(self):
        if self._client is None:
            from google import genai

            self._client = genai.Client(api_key=self.s.gemini_api_key)
        return self._client

    async def _gemini_fallbacks(self) -> List[str]:
        """Models to try if the configured one fails: discovered from the API, flash-class first."""
        if self._available_models is None:
            try:
                names = []
                pager = await self._gemini().aio.models.list()
                async for m in pager:
                    n = (m.name or "").removeprefix("models/")
                    acts = getattr(m, "supported_actions", None) or []
                    if "generateContent" in acts and "gemini" in n and not any(x in n for x in ("tts", "image", "embedding", "live", "audio", "preview-tts")):
                        names.append(n)
                import re as _re

                def ver(n):
                    m = _re.search(r"gemini-(\d+(?:\.\d+)?)", n)
                    return float(m.group(1)) if m else 0.0

                # Flash-Lite first: on the free tier it has ~25x the daily quota of full Flash
                flash = sorted([n for n in names if "flash" in n],
                               key=lambda n: ("preview" in n or "exp" in n, "lite" not in n, -ver(n), len(n)))
                self._available_models = flash[:4]
            except Exception as e:
                log.warning("Could not list Gemini models: %s", e)
                self._available_models = []
        return [m for m in self._available_models if m != self.model]

    async def _run_gemini(self, user_text: str, sys_prompt: str):
        from google.genai import types

        decls = [types.FunctionDeclaration(name=t["name"], description=t["description"], parameters_json_schema=t["parameters"])
                 for t in T.schemas()]
        config = types.GenerateContentConfig(
            system_instruction=sys_prompt,
            temperature=0.6,
            tools=[types.Tool(function_declarations=decls)],
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        )
        contents = [types.Content(role="model" if h["role"] == "assistant" else "user", parts=[types.Part.from_text(text=h["text"])])
                    for h in self._history()]
        contents.append(types.Content(role="user", parts=[types.Part.from_text(text=user_text)]))

        models = [self.model]
        tried_fallbacks = False
        retried_busy = False
        rpm_waits = 0
        step = 0
        while step < MAX_STEPS:
            parts: List[Any] = []
            calls = []
            emitted = False
            try:
                stream = await self._gemini().aio.models.generate_content_stream(model=models[0], contents=contents, config=config)
                async for chunk in stream:
                    cand = chunk.candidates[0] if chunk.candidates else None
                    if not cand or not cand.content or not cand.content.parts:
                        continue
                    for part in cand.content.parts:
                        parts.append(part)
                        if part.function_call:
                            calls.append(part.function_call)
                        elif part.text and not getattr(part, "thought", False):
                            emitted = True
                            yield ("text", part.text)
            except Exception as e:
                if emitted:
                    raise
                per_minute = ("429" in str(e) or "RESOURCE_EXHAUSTED" in str(e)) and "PerDay" not in str(e)
                if per_minute and step > 0 and rpm_waits < 3:
                    # mid-task (e.g. a long browser job): wait out the per-minute window instead of failing
                    rpm_waits += 1
                    delay = min(35.0, _retry_delay(str(e), 20))
                    log.warning("Gemini per-minute limit mid-task – waiting %.0fs", delay)
                    yield ("notice", f"Hit Gemini's per-minute limit; continuing in {int(delay)} s…")
                    await asyncio.sleep(delay)
                    continue
                busy = any(k in str(e) for k in ("503", "UNAVAILABLE", "overloaded", "high demand", "500", "INTERNAL"))
                if busy and not retried_busy:
                    retried_busy = True
                    log.warning("Gemini %s busy (%s) – retrying once", models[0], str(e)[:80])
                    await asyncio.sleep(1.2)
                    continue
                if not tried_fallbacks:
                    tried_fallbacks = True
                    fb = await self._gemini_fallbacks()
                    if fb:
                        log.warning("Gemini model %s failed (%s); trying %s", models[0], e, fb)
                        models = fb
                        continue
                if len(models) > 1:
                    models = models[1:]
                    continue
                raise
            if models[0] != self.model:
                log.info("Switched to working Gemini model: %s", models[0])
                self.model = models[0]
            contents.append(types.Content(role="model", parts=_merge_text_parts(parts, types)))
            if not calls:
                return
            responses = []
            for fc in calls:
                args = dict(fc.args or {})
                yield ("tool_start", fc.name, args)
                result = await asyncio.to_thread(T.call_tool, fc.name, args)
                yield ("tool_end", fc.name, result)
                responses.append(types.Part.from_function_response(name=fc.name, response={"result": result}))
                if fc.id:
                    responses[-1].function_response.id = fc.id
            contents.append(types.Content(role="user", parts=responses))
            step += 1

    # ── OpenAI-compatible (OpenRouter / Ollama / LM Studio / Groq) ─────
    def _oa(self, which: str = "openai"):
        if which not in self._clients:
            from openai import AsyncOpenAI

            if which == "local":
                base, key = self.s.local_llm_url, "ollama"
            else:
                base, key = self.s.llm_base_url, self.s.llm_api_key or "none"
            headers = {"HTTP-Referer": "https://github.com/zhessor/zoha", "X-Title": "Zoha Assistant"}
            self._clients[which] = AsyncOpenAI(base_url=base, api_key=key, default_headers=headers,
                                               timeout=180 if which == "local" else 60)
        return self._clients[which]

    async def _run_openai(self, user_text: str, sys_prompt: str, which: str = "openai"):
        tools = [{"type": "function", "function": t} for t in T.schemas()]
        model = self.local_runtime_model if which == "local" else self.s.llm_model
        if which == "local":
            sys_prompt += "\n/no_think"  # Qwen3: answer directly, no visible reasoning
        msgs: List[Dict[str, Any]] = [{"role": "system", "content": sys_prompt}]
        msgs += [{"role": h["role"], "content": h["text"]} for h in self._history()]
        msgs.append({"role": "user", "content": user_text})
        use_tools = True
        for _ in range(MAX_STEPS):
            text_parts: List[str] = []
            calls: Dict[int, Dict[str, str]] = {}
            try:
                kwargs = dict(model=model, messages=msgs, stream=True, temperature=0.6)
                if use_tools:
                    kwargs["tools"] = tools
                stream = await self._oa(which).chat.completions.create(**kwargs)
                thinker = _ThinkFilter()
                async for chunk in stream:
                    if not chunk.choices:
                        continue
                    d = chunk.choices[0].delta
                    if d is None:
                        continue
                    if getattr(d, "content", None):
                        visible = thinker.feed(d.content)
                        if visible:
                            text_parts.append(visible)
                            yield ("text", visible)
                    for tc in getattr(d, "tool_calls", None) or []:
                        slot = calls.setdefault(tc.index or 0, {"id": "", "name": "", "args": ""})
                        if tc.id:
                            slot["id"] = tc.id
                        if tc.function and tc.function.name:
                            slot["name"] += tc.function.name
                        if tc.function and tc.function.arguments:
                            slot["args"] += tc.function.arguments
            except Exception as e:
                if use_tools and not text_parts and ("tool" in str(e).lower() or "function" in str(e).lower()):
                    log.warning("Model %s doesn't support tools (%s) – continuing without tools", model, e)
                    use_tools = False
                    continue
                raise
            if not calls:
                return
            msgs.append({"role": "assistant", "content": "".join(text_parts) or None, "tool_calls": [
                {"id": c["id"] or f"call_{i}", "type": "function", "function": {"name": c["name"], "arguments": c["args"] or "{}"}}
                for i, c in sorted(calls.items())]})
            for i, c in sorted(calls.items()):
                try:
                    args = json.loads(c["args"] or "{}")
                except json.JSONDecodeError:
                    args = {}
                yield ("tool_start", c["name"], args)
                result = await asyncio.to_thread(T.call_tool, c["name"], args)
                yield ("tool_end", c["name"], result)
                msgs.append({"role": "tool", "tool_call_id": c["id"] or f"call_{i}", "content": result})

    async def _force_choice(self, client, root, user_text, hist, names) -> Optional[Dict[str, Any]]:
        """Constrained decoding: the model MUST answer with one tool name from the list (or "none") as JSON."""
        offered = sorted(n for n in names if n in T.REGISTRY)
        # never guess a destructive action: only offer it if the user's own words ask for it
        for n, rx in DESTRUCTIVE.items():
            if n in offered and not __import__("re").search(rx, user_text, __import__("re").I):
                offered.remove(n)
        catalog = []
        for n in offered:
            t = T.REGISTRY[n]
            params = ", ".join(f"{k}{'' if k in t.parameters.get('required', []) else '?'}"
                               + (f"=[{'|'.join(v['enum'])}]" if v.get("enum") else f":{v.get('type', 'string')}")
                               for k, v in t.parameters.get("properties", {}).items())
            catalog.append(f"- {n}({params}): {_short(t.description)}")
        recent = "\n".join(f"{h['role']}: {h['text'][:160]}" for h in hist[-4:])
        prompt = (f"PC actions you can run:\n" + "\n".join(catalog) +
                  (f"\n\nRecent conversation:\n{recent}" if recent else "") +
                  f"\n\nThe user just said: \"{user_text}\"\n(Speech recognition may mishear words, e.g. 'skim' = 'skip', "
                  f"'radius' = 'raise'.) Choose the ONE action that carries out what the user wants, with its arguments. "
                  f"If they are not asking for anything to be done on the PC, choose \"none\".")
        schema = {"type": "object", "required": ["tool", "arguments"],
                  "properties": {"tool": {"type": "string", "enum": offered + ["none"]}, "arguments": {"type": "object"}}}
        body = {"model": self.local_runtime_model, "stream": False, "keep_alive": "30m", "format": schema,
                "messages": [{"role": "system", "content": "You map a user's request to exactly one PC action. Answer only with JSON."},
                             {"role": "user", "content": prompt}],
                "options": {"temperature": 0, "num_ctx": int(self.s.local_llm_ctx), "num_predict": 120}}
        if self.local_thinks and self._think_switch:
            body["think"] = False
        try:
            async with client.post(root + "/api/chat", json=body) as r:
                data = json.loads(await r.text())
            pick = json.loads(((data.get("message") or {}).get("content") or "{}"))
        except Exception as e:
            log.warning("forced choice failed: %s", e)
            return None
        name = pick.get("tool")
        log.info("Forced choice: %s %s", name, pick.get("arguments"))
        getattr(self, "turn_flags", []).append(f"forced:{name}")
        if name in T.REGISTRY and name in offered:
            return {"name": name, "args": pick.get("arguments") or {}}
        return None

    # ── Local: native Ollama API (fast path) ──────────────────────────
    async def _run_ollama(self, user_text: str, sys_prompt: str, modality: str = "voice"):
        """
        Native /api/chat: thinking off, model kept loaded on the GPU, only the tools this
        request needs (a 40-tool prompt is what made local answers slow).
        """
        import aiohttp

        root = self.s.local_llm_url.rstrip("/")
        root = root[:-3] if root.endswith("/v1") else root
        hist = self._history()
        names = select_tools(user_text, hist, self._recent_tools)
        tools = _tool_list(names)
        static = getattr(self, "_static_prompt", None)
        ctx = getattr(self, "_turn_context", "") if static else ""
        if ctx and any(n.startswith("site_") for n in names):
            ctx += ("\n\nYou have direct access to the user's website and its admin/CMS right now through the site_* tools "
                    "(no login needed). Use them: site_read / site_enquiries / site_analytics to look, site_propose to change.")
        msgs: List[Dict[str, Any]] = [{"role": "system", "content": static or sys_prompt}]
        msgs += [{"role": h["role"], "content": h["text"]} for h in hist]
        msgs.append({"role": "user", "content": (f"<context>\n{ctx}\n</context>\n\n{user_text}" if ctx else user_text)})
        used = set()
        repeats: Dict[str, int] = {}
        stalled = 0
        t0 = time.time()
        # Small local models sometimes SAY they did something without calling a tool. So until a tool has
        # actually run in this turn, the reply is HELD and checked: an unbacked action claim is never shown.
        action_like = bool(ACTION_RX.search(user_text))
        forced_tried = False
        worked = set()  # tools that ran WITHOUT an error this turn
        last_error = ""
        timeout = aiohttp.ClientTimeout(total=None, sock_connect=5, sock_read=300)
        async with aiohttp.ClientSession(timeout=timeout) as client:
            for step in range(MAX_STEPS):
                # spoken replies are short; this also stops any runaway monologue
                cap = 450 if modality == "voice" else 2048
                body = {"model": self.local_runtime_model, "messages": msgs, "stream": True, "keep_alive": "30m",
                        "options": {"temperature": 0.5, "num_ctx": int(self.s.local_llm_ctx), "num_predict": cap}}
                if self.local_thinks and self._think_switch:
                    body["think"] = False  # hybrid models (e.g. qwen3:8b) honour this; reasoning goes to a hidden field
                if tools:
                    body["tools"] = tools
                text_parts: List[str] = []
                calls: List[Dict[str, Any]] = []
                thinker = _ThinkFilter()
                hold = not worked  # nothing has actually succeeded yet → don't let words run ahead of actions
                async with client.post(root + "/api/chat", json=body) as r:
                    if r.status >= 400:
                        err = (await r.text())[:300]
                        if "think" in err.lower() and self._think_switch:
                            self._think_switch = False  # model has no thinking mode: retry without the flag
                            retry = True
                        else:
                            raise RuntimeError(f"Ollama {r.status}: {err}")
                    else:
                        retry = False
                    async for raw in (r.content if not retry else _empty()):
                        line = raw.decode("utf-8", "replace").strip() if isinstance(raw, (bytes, bytearray)) else raw
                        if not line:
                            continue
                        ev = json.loads(line)
                        if ev.get("error"):
                            raise RuntimeError(f"Ollama: {ev['error']}")
                        m = ev.get("message") or {}
                        if m.get("content"):
                            vis = thinker.feed(m["content"])
                            if vis:
                                text_parts.append(vis)
                                if not hold:
                                    yield ("text", _no_emoji(vis) if modality == "voice" else vis)
                        for tc in m.get("tool_calls") or []:
                            fn = tc.get("function") or {}
                            args = fn.get("arguments") or {}
                            if isinstance(args, str):
                                try:
                                    args = json.loads(args or "{}")
                                except json.JSONDecodeError:
                                    args = {}
                            calls.append({"name": fn.get("name", ""), "args": args})
                        if ev.get("done"):
                            log.info("local step %d: prompt %s tok in %.1fs, reply %s tok in %.1fs (%d tools offered)",
                                     step, ev.get("prompt_eval_count"), (ev.get("prompt_eval_duration") or 0) / 1e9,
                                     ev.get("eval_count"), (ev.get("eval_duration") or 0) / 1e9, len(tools))
                if retry:
                    continue
                said = "".join(text_parts).strip()
                if not calls:
                    written = parse_text_calls(said)
                    if written:
                        log.info("Model wrote %d tool call(s) as text – executing them: %s", len(written), [c["name"] for c in written])
                        calls, said = written, ""
                if not calls and hold:
                    claims = bool(ACT_CLAIM_RX.search(said))
                    if claims and "?" in said and not DONE_RX.search(said):
                        claims = False  # a clarifying question ("Which one did you mean? I'll open it") is honest – don't force a tool
                    refused = False  # an honest "I can't" stays as is – forcing an action there picked random tools
                    if (claims or refused) and not forced_tried:
                        forced_tried = True
                        log.info("Unbacked reply (%s): %r – asking the model to pick an action", "claim" if claims else "refusal", said[:120])
                        self.turn_flags.append("unbacked_claim")
                        pick = await self._force_choice(client, root, user_text, hist, names)
                        if pick:
                            calls = [pick]
                        elif claims:
                            log.info("No action chosen – replacing the false claim with an honest answer")
                            said = ("I didn't actually do that. I couldn't tell which action you meant. "
                                    "Could you say it another way, like \"skip the ad\" or \"set volume to 50\"?")
                    elif claims:
                        said = (f"Sorry, that didn't work. {last_error}" if last_error else
                                "I didn't actually do that. I couldn't tell which action you meant. Could you say it another way?")
                    if not calls and said:
                        yield ("text", _no_emoji(said) if modality == "voice" else said)
                if not calls:
                    self._recent_tools = used
                    return
                msgs.append({"role": "assistant", "content": "".join(text_parts),
                             "tool_calls": [{"function": {"name": c["name"], "arguments": c["args"]}} for c in calls]})
                for c in calls:
                    used.add(c["name"])
                    if c["name"] not in names and c["name"] in T.REGISTRY:
                        names.add(c["name"])
                    key = c["name"] + json.dumps(c["args"], sort_keys=True, default=str)
                    repeats[key] = repeats.get(key, 0) + 1
                    if repeats[key] > 3:  # the exact same action a 4th time: it isn't working, stop looping
                        stalled += 1
                        self.turn_flags.append(f"loop:{c['name']}")
                        log.info("Loop guard: %s %s repeated %d times – stopping it", c["name"], c["args"], repeats[key])
                        if stalled >= 2:
                            yield ("text", "I'm going round in circles on this one. " +
                                   (f"{last_error} " if last_error else "") + "Could you do that step yourself, or tell me another way?")
                            self._recent_tools = used
                            return
                        result = ("Error: you already did exactly this 3 times and it didn't get anywhere. Don't repeat it. "
                                  "Try something different, or tell the user plainly what is blocking you.")
                        msgs.append({"role": "tool", "tool_name": c["name"], "content": result})
                        continue
                    yield ("tool_start", c["name"], c["args"])
                    result = await asyncio.to_thread(T.call_tool, c["name"], c["args"])
                    yield ("tool_end", c["name"], result)
                    if not str(result).lstrip().lower().startswith("error"):
                        worked.add(c["name"])
                    else:
                        last_error = str(result).strip().split(":", 1)[-1].strip()
                    msgs.append({"role": "tool", "tool_name": c["name"], "content": result})
                    ask = re.match(r"NOT DONE YET\. Ask the user exactly: '(.+)' Do nothing else\.", str(result).strip(), re.S)
                    if ask:
                        yield ("text", ask.group(1))
                        self._recent_tools = used
                        return
                # only the LATEST page snapshot matters (element numbers change after every action): shrink older ones
                snaps = [i for i, mm in enumerate(msgs) if mm.get("role") == "tool" and "Interactive elements (use the [number]" in str(mm.get("content", ""))]
                for i in snaps[:-1]:
                    first = str(msgs[i]["content"]).split("\n", 1)[0]
                    msgs[i] = {**msgs[i], "content": first + "\n(older page view removed – its element numbers are no longer valid)"}
                # browser work → make sure all browser tools are available for the next step
                if any(n.startswith("browser_") for n in used):
                    names |= BROWSER_TOOLS
                    tools = _tool_list(names)
                t0 = time.time()
        self._recent_tools = used



def _merge_text_parts(parts, types):
    """Streaming splits text into many parts; merge adjacent plain text parts (keep signatures/calls intact)."""
    out = []
    for p in parts:
        plain = p.text is not None and not p.function_call and not getattr(p, "thought", False) and not getattr(p, "thought_signature", None)
        if plain and out and out[-1].text is not None and not out[-1].function_call and not getattr(out[-1], "thought", False) \
                and not getattr(out[-1], "thought_signature", None):
            out[-1] = types.Part.from_text(text=out[-1].text + p.text)
        else:
            out.append(p)
    return out or [types.Part.from_text(text="")]


class _ThinkFilter:
    """Removes <think>…</think> blocks from a streamed reply (Qwen3/DeepSeek style), even when tags are split across chunks."""

    OPEN, CLOSE = "<think>", "</think>"

    def __init__(self):
        self.inside = False
        self.buf = ""
        self.started = False

    @staticmethod
    def _hold(buf: str, tag: str) -> int:
        """Index from which buf's tail could be the start of `tag` (keep it buffered)."""
        for k in range(min(len(tag) - 1, len(buf)), 0, -1):
            if tag.startswith(buf[-k:]):
                return len(buf) - k
        return len(buf)

    def feed(self, chunk: str) -> str:
        self.buf += chunk
        out = ""
        while True:
            if self.inside:
                end = self.buf.find(self.CLOSE)
                if end < 0:
                    self.buf = self.buf[self._hold(self.buf, self.CLOSE):]
                    break
                self.buf = self.buf[end + len(self.CLOSE):]
                self.inside = False
                continue
            start = self.buf.find(self.OPEN)
            if start >= 0:
                out += self.buf[:start]
                self.buf = self.buf[start + len(self.OPEN):]
                self.inside = True
                continue
            cut = self._hold(self.buf, self.OPEN)
            out += self.buf[:cut]
            self.buf = self.buf[cut:]
            break
        if not self.started:
            out = out.lstrip()
            self.started = bool(out)
        return out


def _retry_delay(msg: str, default: float) -> float:
    import re as _re

    m = _re.search(r"retry(?:Delay)?[^0-9]{0,20}(\d+(?:\.\d+)?)\s*s", msg, _re.I)
    return float(m.group(1)) + 1 if m else default


def _why(e: Exception) -> str:
    m = str(e)
    if "PerDay" in m or "per day" in m.lower():
        return "Gemini's free daily limit is used up."
    if "429" in m or "RESOURCE_EXHAUSTED" in m:
        return "Gemini's per-minute limit was hit."
    if any(k in m for k in ("503", "UNAVAILABLE", "overloaded", "high demand")):
        return "Gemini is overloaded right now."
    if any(k in m.lower() for k in ("connect", "timeout", "network", "resolve")):
        return "I can't reach Gemini (offline?)."
    return "Gemini failed."


# ── tool selection for small local models ────────────────────────────────────
CORE_TOOLS = {"open_app", "close_app", "open_website", "play_youtube", "web_lookup", "get_weather", "media_control",
              "set_volume", "set_timer", "set_reminder", "remember", "create_note", "system_status", "find_files",
              "open_path", "open_folder", "take_screenshot", "get_datetime"}
BROWSER_TOOLS = {"browser_open", "browser_read", "browser_click", "browser_type", "browser_select", "browser_press",
                 "browser_scroll", "browser_nav", "browser_tabs", "browser_close", "browser_video", "browser_window", "browser_look"}
KEYWORD_TOOLS = [
    (r"\b(video|full ?screen|youtube|maximi[sz]e|minimi[sz]e|browser|website|web ?site|site|page|tab|amazon|flipkart|github|gmail|calendar|form|log ?in|sign ?in|fill|click|"
     r"scroll|order|cart|book|dashboard|portal|online|on the web|in chrome|in edge|google)\b", BROWSER_TOOLS),
    (r"\b(shut ?down|restart|reboot|sleep|hibernate)\b", {"power"}),
    (r"\b(clipboard|copy|paste|copied)\b", {"clipboard"}),
    (r"\b(type|write|dictate|enter the text)\b", {"type_text"}),
    (r"\b(write|code|notepad|file|letter|document|essay|html|css|javascript|python|script|page|draft|save|proposal|quotation|caption|blog|article|reel script|landing)\b", {"write_file", "improve_file"}),
    (r"\b(improve|better|polish|fix|redo|update|bolder|change|redesign|revamp)\b.*\b(page|file|code|site|website|landing|letter|html|design|layout)\b"
     r"|\b(page|site|website|design|layout)\b.*\b(basic|plain|boring|ugly|improve|better|polish|redo|redesign|revamp)\b", {"improve_file"}),
    (r"\b(news|headlines)\b", {"news_headlines"}),
    (r"\b(notes?)\b", {"read_notes"}),
    (r"\b(timers?|reminders?|alarms?)\b", {"list_timers", "cancel_timer"}),
    (r"\b(forget|delete that|remove that)\b", {"forget"}),
    (r"\b(spotify)\b", {"play_spotify"}),
    (r"\b(search|google)\b", {"web_search"}),
    (r"\b(lock)\b", {"lock_pc"}),
    (r"\b(admin|cms|dashboard|our website|our site|work tab|work items?|testimonials?|announcement|"
     r"popup|pop-up|enquir\w*|inquir\w*|leads?|repl(?:y|ies)|respond|email|mail|archive|analytics|visitors|traffic|undo|what did you change)\b",
     {"site_read", "site_enquiries", "site_analytics", "site_propose", "site_undo", "site_changes",
      "site_enquiry_reply", "site_enquiry_status"}),
]


def select_tools(text: str, history, recent: set) -> set:
    import re as _re

    names = set(CORE_TOOLS)
    blob = text.lower() + " " + " ".join(h["text"].lower() for h in history[-2:] if h["role"] == "user")
    for rx, group in KEYWORD_TOOLS:
        if _re.search(rx, blob):
            names |= group
    if any(n.startswith("browser_") for n in recent) or _browser_is_open():
        names |= BROWSER_TOOLS  # her browser is open (or was just used): "turn off captions" etc. refer to it
    names |= set(recent)
    # "make / build / redesign / improve a website or page for <business>" is FILE work – never website-plugin changes
    build = _re.search(r"\b(make|build|create|design|generate|write|code|redesign|improve|improvise|polish|basic|better|"
                       r"change|update|fix)\b.*\b(website|site|landing page|web ?page|page|html|design)\b", text.lower())
    if build and not _re.search(r"\b(admin|cms|work tab|work items?|our website|our site)\b", text.lower()):
        names = {n for n in names if not n.startswith("site_")} | {"write_file", "improve_file", "find_files"}
    if T.CTX.vision is None:
        names.discard("browser_look")
    return {n for n in names if n in T.REGISTRY}


def _browser_is_open() -> bool:
    if T.CTX.browser_open_hint is not None:  # set by tests / the stress runner
        return bool(T.CTX.browser_open_hint)
    try:
        from .browser import _BROWSER

        return _BROWSER is not None and _BROWSER.is_open()
    except Exception:
        return False


def _tool_list(names) -> list:
    """Offered tools in a FIXED order (core tools first), so consecutive requests share as long a prompt prefix as possible."""
    order = {n: i for i, n in enumerate(sorted(CORE_TOOLS))}
    schemas = [t for t in T.schemas() if t["name"] in names]
    schemas.sort(key=lambda t: (0, order[t["name"]], "") if t["name"] in order else (1, 0, t["name"]))
    return [{"type": "function", "function": {**t, "description": t["description"] if t["name"] == "site_propose" else _short(t["description"])}}
            for t in schemas]


def _short(desc: str) -> str:
    """First sentence of a tool description (keeps the prompt small for local models)."""
    import re as _re

    first = _re.split(r"(?<=[.!?])\s", desc, maxsplit=1)[0]
    return first[:220]


async def _empty():
    if False:
        yield ""


ACTION_RX = __import__("re").compile(
    r"\b(pause|stop|resume|unpause|play|skip|next|previous|open|close|quit|launch|start|turn (on|off|up|down)|set|mute|unmute|"
    r"full ?screen|maximi[sz]e|minimi[sz]e|make|put|seek|forward|rewind|reload|refresh|zoom|press|select|choose|"
    r"volume|screenshot|lock|remind|timer|alarm|search|google|find|type|copy|note|remember|forget|shut ?down|restart|"
    r"browse|go to|navigate|click|fill|scroll|weather)\b", __import__("re").I)
CLAIM_RX = __import__("re").compile(
    r"\b(done|paused|stopped|resumed|playing|opened|opening|closed|closing|launched|started|set|muted|unmuted|skipped|"
    r"saved|noted|searched|searching|locked|has been|have been|is now|now (playing|paused|stopped|open|in)|i'?ve|i have|"
    r"full ?screen|maximi[sz]ed|clicked|selected|typed|let me|i'?ll|i will|"
    r"pausing|stopping|launching|let me (pause|stop|open|close|play))\b", __import__("re").I)


def _looks_like_call(text: str) -> bool:
    import re as _re

    t = text.lstrip()
    if t.startswith(("<tool_call>", "```", '{"name"', "{'name'", '{"function"')):
        return True
    m = _re.match(r"([a-z_]+)\s*\(", t)
    return bool(m and m.group(1) in T.REGISTRY)


def parse_text_calls(text: str) -> List[Dict[str, Any]]:
    """Recover tool calls a model wrote as plain text: <tool_call>{json}</tool_call>, {"name":…,"arguments":…},
    tool_name({...}) or tool_name(key=value, …)."""
    import ast
    import re as _re

    calls: List[Dict[str, Any]] = []

    def add(name, args):
        if name in T.REGISTRY:
            calls.append({"name": name, "args": args if isinstance(args, dict) else {}})

    def loads(blob):
        for f in (json.loads, ast.literal_eval):
            try:
                return f(blob)
            except Exception:
                continue
        return None

    for blob in _re.findall(r"<tool_call>\s*(\{.*?\})\s*</tool_call>", text, _re.S) or \
            _re.findall(r'(\{\s*["\']name["\']\s*:.*?\}\s*\})', text, _re.S):
        obj = loads(blob)
        if isinstance(obj, dict):
            add(obj.get("name"), obj.get("arguments") or obj.get("parameters") or {})
    if calls:
        return calls
    for name, inner in _re.findall(r"\b([a-z_]+)\s*\((.*?)\)\s*(?:$|\n|;|`)", text, _re.S | _re.M):
        if name not in T.REGISTRY:
            continue
        inner = inner.strip()
        if inner.startswith("{"):
            add(name, loads(inner) or {})
        elif "=" in inner:
            try:
                node = ast.parse(f"f({inner})", mode="eval").body
                add(name, {kw.arg: ast.literal_eval(kw.value) for kw in node.keywords})
            except Exception:
                pass
        elif not inner:
            add(name, {})
    return calls


# A reply that says something WAS done on the PC (only believable if a tool actually ran)
DONE_RX = __import__("re").compile(r"\b(done|all set|opened|closed|played|paused|muted|saved|typed|skipped|switched|scrolled|clicked)\b", __import__("re").I)
ACT_CLAIM_RX = __import__("re").compile(
    r"\b(skipped|paused|stopped|resumed|muted|unmuted|opened|closed|launched|started playing|now playing|is (?:now )?playing|"
    r"playing (?:\"|'|it|the|this|that|[A-Z])|set (?:the |your )?(?:system )?volume|volume (?:is )?(?:now |set )|"
    r"(?:turned|cranked) (?:it |the volume )?(?:up|down|on|off)|saved|noted|locked|screenshot (?:saved|taken)|took a screenshot|"
    r"timer (?:is )?set|reminder (?:is )?set|is now (?:open|closed|paused|stopped|full ?screen|muted|maximi[sz]ed|minimi[sz]ed)|"
    r"has been (?:paused|stopped|opened|closed|skipped|set|saved|muted|locked|added|scheduled|created)|done[.!—-]|"
    r"(?:both |all |now |is |are )?set (?:for|to|at)\b|(?:timer|reminder|alarm)s?(?: \w+){0,3} (?:set|added|scheduled|created|active|running)\b|"
    r"(?:added|scheduled|created|cancell?ed|deleted|removed|typed|copied|clicked|searched|switched)\b|"
    r"(?:it'?s|is|are) now (?:active|set|running|playing|open|on|off)|"
    r"i(?:'m| am) (?:now )?(?:setting|adding|opening|playing|skipping|pausing|turning|closing|creating|scheduling)|"
    r"i(?:'ll| will) (?:now |go ahead and |just )?(?:set|add|open|play|skip|pause|turn|close|create|schedule|remind|remember|note|save|"
    r"lock|mute|unmute|launch|start|stop|cancel|delete|forget|copy|type|search|switch|restart|shut)\b|"
    r"^\W*(?:ok(?:ay)?|sure|alright|got it)?[,!. ]*done\b|\bdone\s*[—–-]|\ball set\b|"
    r"i(?:'ve| have) (?:now )?(?:set|added|opened|played|skipped|paused|turned|closed|created|scheduled|fixed))", __import__("re").I)
REFUSAL_RX = __import__("re").compile(r"\b(can'?t|cannot|unable to|not able to|don'?t have (?:the )?(?:ability|access)|outside my)\b",
                                      __import__("re").I)
DESTRUCTIVE = {"browser_close": r"\b(close|quit|exit|shut)\b", "close_app": r"\b(close|quit|exit|kill|shut)\b",
               "power": r"\b(shut ?down|restart|reboot|sleep|power)\b", "lock_pc": r"\block\b",
               "cancel_timer": r"\b(cancel|stop|delete|remove|clear)\b", "forget": r"\bforget\b"}
_EMOJI = __import__("re").compile("[\U0001F000-\U0001FAFF\u2600-\u27BF\uFE0F\u200d]+")


def _no_emoji(t: str) -> str:
    return _EMOJI.sub("", t).replace("  ", " ")
