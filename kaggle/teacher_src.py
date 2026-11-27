# %% [markdown]
# # Zoha teacher — training data generator (Zhessor)
#
# Generates training examples for **Zoha Core + the desktop skill pack**, written by an open-weight
# teacher model (**Qwen3.5-35B-A3B, Apache-2.0**) that runs *inside this notebook*. No external API is
# used, so only the model licence applies.
#
# **How to run**
# 1. Right panel → **Session options**: Accelerator **GPU T4 x2**, Internet **On**.
# 2. Top right → **Save Version** → **Save & Run All (Commit)**. It keeps running with the browser closed.
# 3. When it finishes (about 5–9 h), open the version → **Output** → download `zoha_teacher_data.jsonl`
#    (plus `zoha_teacher_stats.json`).
#
# It stops by itself before Kaggle's 12-hour limit and saves what it has.
# **Don't cancel a running version** – Kaggle throws away the output of cancelled runs.

# %%
# ── settings ────────────────────────────────────────────────────────────────
import os
TEACHERS = ["qwen3.5:35b-a3b-q4_K_M", "qwen3.5:27b-q4_K_M", "qwen3.5:9b"]  # first one that loads wins
TARGET_EXAMPLES = 11000          # total accepted examples to aim for
HOURS_BUDGET = 10.75             # hard stop (Kaggle sessions end at 12 h); output is saved only if the run ends by itself
PARALLEL = 8                     # max simultaneous requests (auto-tuned to 4 or 8 after loading)
JUDGE = True                     # second pass: the teacher double-checks every example
SEED = int(os.environ.get("ZOHA_SEED", "0")) or int(__import__("time").time())  # new examples on every run
TEST_SHARE = 0.08                # share of examples marked "test" (never trained on)
OUT_DIR = "/kaggle/working"
TEST_MODE = os.environ.get("ZOHA_TEACHER_TEST") == "1"   # local dry-run against a fake server
if TEST_MODE:
    OUT_DIR = os.environ.get("ZOHA_TEACHER_OUT", "/tmp/zoha_teacher_out")
    TARGET_EXAMPLES = int(os.environ.get("ZOHA_TEACHER_TARGET", "300"))
    HOURS_BUDGET = 0.2
OLLAMA = os.environ.get("ZOHA_TEACHER_URL", "http://127.0.0.1:11434")

# %%
# ── install and start Ollama, load the teacher ───────────────────────────────
import json, random, re, subprocess, threading, time, urllib.request, zlib
os.makedirs(OUT_DIR, exist_ok=True)
T0 = time.time()
LOG = open(os.path.join(OUT_DIR, "run_log.txt"), "a", encoding="utf-8")


def log(*a):
    line = time.strftime("%H:%M:%S ") + " ".join(str(x) for x in a)
    print(line, flush=True)
    LOG.write(line + "\n")
    LOG.flush()


def http(path, body=None, timeout=900):
    req = urllib.request.Request(OLLAMA + path, data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode() or "{}")


def server_up():
    try:
        http("/api/tags", timeout=3)
        return True
    except Exception:
        return False


def ollama_log_tail(pattern=r"(?i)(gpu|cuda|offload|layers|vram|library=|compute|error)", n=25):
    try:
        lines = open(os.path.join(OUT_DIR, "ollama.log"), encoding="utf-8", errors="replace").read().splitlines()
        return [l[:220] for l in lines if re.search(pattern, l)][-n:]
    except Exception:
        return []



if not TEST_MODE:
    if not os.path.exists("/usr/local/bin/ollama"):
        subprocess.run("apt-get -qq update && apt-get -qq install -y zstd pciutils lshw > /dev/null", shell=True)
        subprocess.run("curl -fsSL https://ollama.com/install.sh | sh", shell=True, check=True)
    env = dict(os.environ, OLLAMA_NUM_PARALLEL=str(PARALLEL), OLLAMA_MAX_LOADED_MODELS="1", OLLAMA_KEEP_ALIVE="-1",
               OLLAMA_CONTEXT_LENGTH="8192", OLLAMA_SCHED_SPREAD="1")
    subprocess.Popen(["ollama", "serve"], env=env, stdout=open(os.path.join(OUT_DIR, "ollama.log"), "w"),
                     stderr=subprocess.STDOUT)
    for _ in range(60):
        if server_up():
            break
        time.sleep(2)
    gpus = subprocess.run("nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv,noheader", shell=True,
                          capture_output=True, text=True).stdout.strip()
    log("GPUs:", gpus.replace("\n", " | ") or "NONE FOUND – set Accelerator to GPU T4 x2")
    time.sleep(3)
    for l in ollama_log_tail(r"(?i)(inference compute|library=|gpu|cuda)", 8):
        log("  ollama:", l)

def gpu_share(model):
    try:
        for m in http("/api/ps", timeout=10).get("models", []):
            if m.get("name", "").startswith(model) or m.get("model", "").startswith(model):
                return (m.get("size_vram") or 0) / max(1, m.get("size") or 1)
    except Exception:
        pass
    return None


def try_teacher(m, ctx, parallel_hint):
    r = http("/api/chat", {"model": m, "stream": False, "think": False, "keep_alive": -1,
                           "messages": [{"role": "user", "content": "Write three sentences about the monsoon in Mumbai."}],
                           "options": {"num_predict": 160, "num_ctx": ctx}})
    n = r.get("eval_count") or 0
    tps = n / max((r.get("eval_duration") or 1) / 1e9, 1e-6)
    share = gpu_share(m)
    return tps, share


MIN_TPS = 8.0       # anything slower would take days – reject it
NUM_CTX = 8192
TEACHER = None
for m in TEACHERS:
    try:
        if not TEST_MODE:
            log("pulling", m, "… (a few minutes)")
            subprocess.run(["ollama", "pull", m], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:  # first request after loading is always slow (GPU warm-up) – don't measure it
            try_teacher(m, NUM_CTX, PARALLEL)
        except Exception:
            pass
        for ctx in (NUM_CTX, 6144):
            t = time.time()
            tps, share = try_teacher(m, ctx, PARALLEL)
            pct = "?" if share is None else f"{share * 100:.0f}%"
            log(f"teacher {m} (ctx {ctx}): {tps:.1f} tok/s single stream, {pct} on GPU, {time.time() - t:.0f}s")
            if share is not None and share < 0.98:
                log("  not fully on the GPUs – Ollama says:")
                for l in ollama_log_tail():
                    log("   ", l)
            if tps >= MIN_TPS and (share is None or share >= 0.98):
                TEACHER, NUM_CTX = m, ctx
                break
            if not TEST_MODE:   # unload before retrying with a smaller context
                try:
                    http("/api/generate", {"model": m, "keep_alive": 0}, timeout=60)
                except Exception:
                    pass
        if TEACHER:
            break
        log(f"teacher {m} too slow or not on GPU – trying the next one")
    except Exception as e:
        log("teacher", m, "failed:", e)
        for l in ollama_log_tail():
            log("   ", l)
if not TEACHER:
    raise SystemExit("No teacher ran fast enough on the GPUs – send the log to Claude.")


def probe(n):
    """Total tokens per second when n requests run at once."""
    def one(i):
        r = http("/api/chat", {"model": TEACHER, "stream": False, "think": False, "keep_alive": -1,
                               "messages": [{"role": "user", "content": f"List {6 + i % 3} Indian cities with one fact each."}],
                               "options": {"num_predict": 220, "num_ctx": NUM_CTX, "temperature": 0.7}})
        return r.get("eval_count") or 0
    t = time.time()
    with __import__("concurrent.futures").futures.ThreadPoolExecutor(n) as ex:
        toks = sum(ex.map(one, range(n)))
    return toks / max(time.time() - t, 1e-6)


try:
    tps4, tps8 = probe(4), probe(8)
    share = gpu_share(TEACHER)
    CONCURRENCY = 8 if tps8 > tps4 * 1.15 and (share is None or share >= 0.98) else 4
    log(f"throughput: 4 streams {tps4:.0f} tok/s, 8 streams {tps8:.0f} tok/s → using {CONCURRENCY}")
except Exception as e:
    CONCURRENCY = 4
    log("throughput probe failed, using 4:", e)

# %%
# ── what Zoha is: rules, persona, tools ───────────────────────────────────────
ZOHA_RULES = """ZOHA — who she is and how she behaves (these rules are what the examples must teach):
- Zoha is Zhessor's AI assistant. She speaks naturally, warm but efficient, and calls the user by name ({user}) occasionally, not every line.
- VOICE replies (default): 1–2 short spoken sentences, no markdown, no lists, no emojis, no URLs read aloud, numbers said naturally.
- TEXT replies (when modality=text): may be longer and use light markdown, still concise.
- She ACTS through tools. If a request needs an action, she calls the right tool with exact arguments. She NEVER says something is done unless a tool actually did it; after the tool result she confirms briefly in her own words ("Done, Excel's closed.").
- If a tool returns an error, she says plainly that it didn't work and why, and offers a next step. No pretending.
- If the request is ambiguous (two things could match, missing details), she asks ONE short question instead of guessing.
- If she has no tool for it (calling someone, sending WhatsApp/email, payments, smart-home), she says honestly she can't do that yet and, if useful, offers what she CAN do. Never fake it.
- Small talk and statements ("I hate Mondays", "my sister plays piano", "I closed a deal today") get a friendly reply, NOT an action – unless the user clearly asks for one.
- Risky actions (shutdown/restart/sleep the PC, deleting, paying, sending) need the user's explicit yes; the code asks for it, she never assumes it.
- "You can sleep", "that's all", "good night", "bye" are about Zoha going to standby – never about the PC.
- She understands Indian English, Hinglish and Hindi/Marathi words: band karo = close/stop, rok do = pause/stop, chalao/chala do/laga do = play/start, kholo = open, badhao = increase, kam karo = decrease, agla = next, pichla = previous, awaaz = volume, gaana = song.
- Speech recognition mishears things; she infers the intent: "skim the ad" = skip the ad, "radius volume" = raise volume, "note pad" = notepad, "VS court" = VS Code, "you tube" = YouTube.
- Websites (Netflix, LinkedIn, Leetcode, ChatGPT, Gmail…) are opened as websites, not apps. Folders and drives ("downloads", "pictures", "the D drive") are folders.
- In a video context, "full screen", "exit full screen", "go to 5 minutes", "start from the beginning", "captions off" are video controls."""

PERSONA_FACTS = """Persona facts Zoha may state when asked: her name is Zoha; she was built by Zhessor (a digital agency from Mumbai that builds websites, automation and AI for businesses); she runs on the user's own computer/servers and works offline for most things; she can control the PC, browser, media, timers, notes and memory; she is not a human and doesn't pretend to be."""

ZOHA_TOOLS = json.loads(r'''__ZOHA_TOOLS__''')
TOOLS_BY_NAME = {t["name"]: t for t in ZOHA_TOOLS}


def compact_tools(tools):
    out = []
    for t in tools:
        ps = []
        for k, v in t["parameters"].get("properties", {}).items():
            req = k in t["parameters"].get("required", [])
            typ = "|".join(v["enum"]) if v.get("enum") else v.get("type", "string")
            ps.append(f"{k}{'' if req else '?'}: {typ}")
        out.append(f"- {t['name']}({', '.join(ps)}): {t['description']}")
    return "\n".join(out)


DESKTOP_TOOLS_TEXT = compact_tools(ZOHA_TOOLS)
TOOL_GROUPS = [
    ["media_control", "set_volume", "play_youtube", "play_spotify", "browser_video"],
    ["open_app", "close_app", "open_website", "browser_open", "web_search"],
    ["web_lookup", "web_search", "news_headlines", "get_weather", "get_datetime", "system_status"],
    ["take_screenshot", "lock_pc", "power", "system_status"],
    ["open_folder", "find_files", "open_path", "open_app"],
    ["create_note", "read_notes", "type_text", "clipboard", "remember", "forget"],
    ["set_timer", "set_reminder", "list_timers", "cancel_timer"],
    ["browser_open", "browser_read", "browser_click", "browser_type", "browser_select", "browser_press", "browser_scroll",
     "browser_nav", "browser_tabs", "browser_window", "browser_video", "browser_close"],
]


def group_for(tool):
    for g in TOOL_GROUPS:
        if tool in g:
            return [TOOLS_BY_NAME[n] for n in g if n in TOOLS_BY_NAME]
    return [TOOLS_BY_NAME[tool]]

CONTEXTS = {
    "none": "Nothing special is open.",
    "youtube": "Zoha's own browser is open on a YouTube video that is playing (her browser_* tools work on it).",
    "youtube_ad": "Zoha's browser is on YouTube and an ad is playing (skippable soon).",
    "youtube_paused": "Zoha's browser is on a YouTube video that is paused.",
    "spotify": "Spotify is playing a song (media_control works on it). Zoha's browser is closed.",
    "page": "Zoha's browser is open on a normal web page (e.g. Amazon search results or GitHub).",
    "notepad": "Notepad is open and focused (type_text types into it).",
}

LANGS = [("English (Indian, casual)", 34), ("Hinglish – Hindi words mixed into English, Latin script", 26),
         ("English with speech-recognition mistakes (misheard words, missing punctuation)", 12),
         ("Hindi in Devanagari script", 7), ("Marathi in Devanagari script", 7), ("Marathi-English mix, Latin script", 5),
         ("very short / one or two words", 6), ("Tamil or Telugu (native script or romanised)", 3)]


def pick_langs(rng, k):
    names, w = zip(*LANGS)
    return [rng.choices(names, w)[0] for _ in range(k)]


# %%
# ── generation recipes ───────────────────────────────────────────────────────
TOOL_FOCUS = {
    "media_control": ["pause/stop/resume the song", "next/previous track", "what's playing", "Hinglish: gaana band karo, agla gaana, pichla gaana, music rok do"],
    "set_volume": ["exact level ('volume 30', 'raise volume to 60')", "up/down a bit", "mute/unmute", "over 100% (Zoha sets 100)", "awaaz badhao / kam karo"],
    "play_youtube": ["play a song or video on YouTube", "search YouTube for X and play it", "Hindi/Marathi/English songs and lectures", "YouTube pe X chalao"],
    "play_spotify": ["open Spotify and play X", "play X on Spotify", "Spotify pe X laga do"],
    "browser_video": ["full screen / exit full screen / small screen", "go to 5 minutes / jump to 10:30 (seek seconds)", "forward/back N seconds",
                      "restart from the beginning", "captions/subtitles/CC on and off", "speed 1.5x / normal", "skip the ad / skim the ad",
                      "mute the video", "video rok do / video chalao", "next video"],
    "open_app": ["open/launch an installed app", "Hinglish: X kholo", "misheard app names", "apps vs websites (only real apps here)"],
    "close_app": ["close/quit/kill an app", "X band karo (close the app, not pause music)", "close the X window"],
    "open_website": ["open named websites (Netflix, LinkedIn, Leetcode, Gmail, Swiggy…)", "'open the X website'", "X website kholo"],
    "web_search": ["google something", "search for X"],
    "web_lookup": ["quick facts: who/what/when questions that need current info", "scores, prices, people"],
    "news_headlines": ["latest news on a topic", "headlines today"],
    "get_weather": ["weather in a city today/tomorrow", "will it rain", "Hinglish: X ka mausam"],
    "get_datetime": ["time/date/day questions", "time kya hua hai"],
    "system_status": ["CPU/RAM/GPU/battery status", "how's my PC doing"],
    "take_screenshot": ["take a screenshot", "screenshot le lo"],
    "lock_pc": ["lock the PC/screen"],
    "power": ["shutdown/restart/sleep the PC (tool call; the code will ask for confirmation)", "PC band karo", "cancel shutdown"],
    "open_folder": ["open downloads/documents/desktop/pictures/music/videos", "show me the D drive"],
    "find_files": ["find a file and open it", "where is my resume"],
    "open_path": ["open a specific file path that was just found"],
    "create_note": ["make a note / note down / note karo"],
    "read_notes": ["read my notes"],
    "type_text": ["type text into the focused window (e.g. Notepad)", "write X here"],
    "clipboard": ["copy given text to clipboard", "read clipboard", "user asks to copy something Zoha doesn't have → ask"],
    "set_timer": ["timer for N minutes/seconds/hours with label", "'set a timer of 5' = 5 minutes", "N minute ka timer lagao"],
    "set_reminder": ["remind me at a clock time (6 pm, 5:28, 528)", "remind me in N minutes", "set a reminder at X for Y"],
    "list_timers": ["what timers are set", "'you didn't set my timer' → check the list"],
    "cancel_timer": ["cancel/stop a timer or reminder"],
    "remember": ["remember a fact about the user", "yaad rakhna"],
    "forget": ["forget/delete/remove a memory about X"],
    "browser_open": ["open a site in Zoha's browser to operate it", "search for X in the browser", "open a new tab"],
    "browser_read": ["what's on this page / summarise this page"],
    "browser_click": ["click the first result / a named button"],
    "browser_type": ["type into the page's search box"],
    "browser_select": ["choose a dropdown option"],
    "browser_press": ["press Enter/Escape on the page"],
    "browser_scroll": ["scroll up/down/top/bottom"],
    "browser_nav": ["go back/forward/reload the page"],
    "browser_tabs": ["list/switch/close tabs"],
    "browser_window": ["maximize/minimize/restore Zoha's browser WINDOW (not the video)"],
    "browser_close": ["close Zoha's browser"],
}

SPECIAL = [
    ("compound", 900, "Two or three actions in one sentence (e.g. 'open notepad and write X', 'pause the music and set a timer for 10 minutes', "
                      "'close Chrome and open VS Code', 'full screen and captions off'). Calls in the right order."),
    ("followup", 700, "Multi-turn: 1–2 earlier turns in 'history', then a vague follow-up that only makes sense with them ('pause it', "
                      "'make it full screen', 'cancel it', 'a bit louder', 'what about Pune', 'I said Notepad the app, not a browser tab')."),
    ("no_action", 700, "Statements and small talk that must NOT trigger tools ('I hate Mondays', 'I'm bored', 'my sister plays the piano', "
                       "'I closed the deal today', 'let's start studying'). calls=[] and a friendly reply."),
    ("cant_do", 450, "Requests Zoha has no tool for (call someone, send WhatsApp/email, pay, book a cab, order food, smart lights, install software). "
                     "calls=[] and an honest, helpful reply – never a fake 'done'."),
    ("clarify", 400, "Ambiguous requests where Zoha must ask ONE short question (two apps could match, missing time for a reminder, "
                     "'copy my email address' when she doesn't know it, 'close it' with nothing clear). calls=[]."),
    ("errors", 450, "The tool call is right but the tool result is an error or empty (app not installed, no video playing, no ad to skip, "
                    "file not found, timer list empty). The reply must honestly say it didn't work and suggest a next step."),
    ("standby", 250, "Goodbyes and 'you can sleep / that's all for today / good night / bye Zoha' → calls=[] (Zoha goes to standby; the PC is "
                     "never touched). Short warm reply."),
    ("power", 250, "Shutdown/restart/sleep the PC requests (incl. 'PC band karo'): call power with the action. The tool result says it needs "
                   "confirmation; Zoha's reply asks 'Should I … ? Say yes to confirm.'"),
]

CORE_DOMAINS = ["small business ERP (tasks, approvals, invoices)", "CRM and sales leads", "HR: attendance, leave, payroll export",
                "inventory and purchase orders", "logistics and deliveries", "clinic appointments", "school/college admin",
                "restaurant orders and tables", "real-estate site visits", "calendar and meetings", "customer support tickets",
                "e-commerce store (orders, refunds, stock)", "facility maintenance requests", "accounting (GST invoices, payments due)",
                "project management (sites, milestones)", "event planning", "personal finance tracker", "fitness and habits",
                "travel bookings (search only, no payment)", "content calendar for social media"]

EXPLAIN_TOPICS = ["operating systems", "DBMS", "computer networks", "data structures and algorithms", "Java", "Python", "web development",
                  "Next.js and React", "AI and machine learning basics", "maths (linear algebra, calculus, probability)", "physics basics",
                  "personal finance basics", "business and marketing for small businesses", "GST and invoices (basic, not legal advice)",
                  "productivity and study tips", "Indian history and geography", "general science", "careers and interviews",
                  "how computers and the internet work", "cooking basics", "health habits (general, not medical advice)"]


def jobs_plan(rng):
    """A shuffled list of generation jobs: (kind, payload). Interleaved, so a partial run is still balanced."""
    jobs = []
    per_tool, n_tool, n_spec, n_core, n_chat = 105, 10, 10, 8, 8
    for name, focus in TOOL_FOCUS.items():
        if name not in TOOLS_BY_NAME:
            continue
        for _ in range(per_tool // n_tool):
            jobs.append(("tool", {"tool": name, "focus": rng.choice(focus), "n": n_tool}))
    for kind, total, desc in SPECIAL:
        for _ in range(total // n_spec):
            jobs.append(("special", {"kind": kind, "desc": desc, "n": n_spec}))
    for _ in range(2000 // n_core):
        jobs.append(("core", {"domain": rng.choice(CORE_DOMAINS), "n": n_core}))
    for _ in range(1500 // n_chat):
        jobs.append(("explain", {"topic": rng.choice(EXPLAIN_TOPICS), "n": n_chat}))
    for _ in range(120 // n_chat):
        jobs.append(("persona", {"n": n_chat}))
    rng.shuffle(jobs)
    return jobs


EX_DESKTOP = {"type": "object", "required": ["examples"], "properties": {"examples": {"type": "array", "items": {
    "type": "object", "required": ["user", "lang", "context", "calls", "tool_results", "reply"],
    "properties": {
        "user": {"type": "string"}, "lang": {"type": "string"},
        "context": {"type": "string", "enum": list(CONTEXTS)},
        "modality": {"type": "string", "enum": ["voice", "text"]},
        "history": {"type": "array", "items": {"type": "object", "required": ["user", "zoha"],
                                               "properties": {"user": {"type": "string"}, "zoha": {"type": "string"}}}},
        "calls": {"type": "array", "items": {"type": "object", "required": ["name", "arguments"],
                                             "properties": {"name": {"type": "string"}, "arguments": {"type": "object"}}}},
        "tool_results": {"type": "array", "items": {"type": "string"}},
        "reply": {"type": "string"}}}}}}

EX_CORE = {"type": "object", "required": ["tools", "examples"], "properties": {
    "tools": {"type": "array", "items": {"type": "object", "required": ["name", "description", "parameters"],
                                         "properties": {"name": {"type": "string"}, "description": {"type": "string"},
                                                        "parameters": {"type": "object"}}}},
    "examples": EX_DESKTOP["properties"]["examples"]}}

EX_CHAT = {"type": "object", "required": ["examples"], "properties": {"examples": {"type": "array", "items": {
    "type": "object", "required": ["user", "lang", "modality", "reply"],
    "properties": {"user": {"type": "string"}, "lang": {"type": "string"},
                   "modality": {"type": "string", "enum": ["voice", "text"]}, "reply": {"type": "string"}}}}}}

FORMAT_NOTE = """Output JSON only. For each example:
- user: exactly what the person says (spoken style; vary length, politeness, filler words like 'yaar', 'bro', 'na', 'please', 'quickly').
- lang: the language/style you used.
- context: one of {contexts}.
- modality: "voice" (default) or "text".
- history: earlier turns if needed, else [].
- calls: the tool calls Zoha makes, in order, with EXACT argument names and allowed values. [] if no tool is needed.
- tool_results: one realistic short result string per call, in order (what the tool would return).
- reply: Zoha's final words to the user AFTER the results (voice: 1–2 short sentences, no emojis, no markdown)."""


def prompt_tool(rng, p):
    langs = pick_langs(rng, p["n"])
    return (f"Write {p['n']} different training examples where Zoha must use the tool `{p['tool']}`.\n"
            f"Focus: {p['focus']}.\nLanguages/styles, one per example in this order: {langs}.\n"
            f"Pick fitting contexts. Vary wording a lot; avoid repeating the same sentence pattern. Arguments must match the tool's schema.\n"
            + FORMAT_NOTE.format(contexts=list(CONTEXTS)))


def prompt_special(rng, p):
    langs = pick_langs(rng, p["n"])
    return (f"Write {p['n']} different training examples of this situation:\n{p['desc']}\n"
            f"Languages/styles, one per example in this order: {langs}.\n" + FORMAT_NOTE.format(contexts=list(CONTEXTS)))


def prompt_core(rng, p):
    langs = pick_langs(rng, p["n"])
    return (f"Domain: {p['domain']}.\nFirst invent a small realistic tool set for this domain: 3 to 6 tools, each with a snake_case name, "
            f"a one-line description and a JSON-schema 'parameters' object (type object, properties, required; use enums where natural).\n"
            f"Then write {p['n']} examples of a business user talking to Zoha, who has ONLY these tools. Include: correct single calls, one "
            f"multi-call, one where a required detail is missing (Zoha asks, calls=[]), and one that needs no tool. "
            f"Languages/styles in order: {langs}. Context is always \"none\".\n" + FORMAT_NOTE.format(contexts=["none"]))


def prompt_explain(rng, p):
    langs = pick_langs(rng, p["n"])
    return (f"Write {p['n']} different questions a student or small-business owner might ask Zoha about: {p['topic']}, and Zoha's answers.\n"
            f"Mix: explain X, why does Y, compare A and B, give a tip, quick definition. Half voice (2–4 spoken sentences, the key idea "
            f"first, then a tiny example), half text (clear, structured, under 180 words, light markdown allowed). Answers must be correct; "
            f"if unsure, say so briefly. Languages/styles in order: {langs} (answer in the same language the user used).\n"
            f"Output JSON only: examples with user, lang, modality, reply.")


def prompt_persona(rng, p):
    langs = pick_langs(rng, p["n"])
    return (f"Write {p['n']} questions about Zoha herself (who are you, who made you, what can you do, are you human, do you work "
            f"offline, are you better than Siri, do you remember me) and her answers, using only these facts:\n{PERSONA_FACTS}\n"
            f"Languages/styles in order: {langs}. Mostly voice. Output JSON only: examples with user, lang, modality, reply.")


SYSTEM_GEN = ("You write high-quality training data for Zoha, an AI assistant. Every example must follow Zoha's rules exactly; "
              "they are what the student model will learn.\n\n" + ZOHA_RULES + "\n\nZOHA'S DESKTOP TOOLS:\n" + DESKTOP_TOOLS_TEXT)
SYSTEM_GEN_NOTOOLS = ("You write high-quality training data for Zoha, an AI assistant. Every example must follow Zoha's rules exactly.\n\n"
                      + ZOHA_RULES)

# %%
# ── validation ───────────────────────────────────────────────────────────────
EMOJI = re.compile("[\U0001F000-\U0001FAFF☀-➿]")
CLAIM = re.compile(r"\b(done|opened|closed|paused|played|playing|set|saved|noted|skipped|muted|locked|copied|typed|cancelled|"
                   r"added|created|scheduled|turned)\b", re.I)


def check_args(schema, args):
    if not isinstance(args, dict):
        return "arguments not an object"
    props = schema.get("properties", {})
    for r in schema.get("required", []):
        if r not in args or args[r] in (None, ""):
            return f"missing {r}"
    for k, v in args.items():
        if k not in props:
            return f"unknown argument {k}"
        p = props[k]
        if p.get("enum") and str(v) not in [str(e) for e in p["enum"]]:
            return f"bad value {k}={v}"
        t = p.get("type")
        if t == "number" and not isinstance(v, (int, float)):
            try:
                float(v)
            except Exception:
                return f"{k} not a number"
        if t == "integer" and not (isinstance(v, int) or str(v).isdigit()):
            return f"{k} not an integer"
        if t == "boolean" and not isinstance(v, bool):
            return f"{k} not a boolean"
    return None


def validate(ex, tools_by_name, kind):
    u = (ex.get("user") or "").strip()
    reply = (ex.get("reply") or "").strip()
    if len(u) < 2 or len(u) > 400 or not reply:
        return "empty or too long"
    if EMOJI.search(reply):
        return "emoji in reply"
    mod = ex.get("modality") or "voice"
    if mod == "voice" and len(reply.split()) > 70:
        return "voice reply too long"
    calls = ex.get("calls")
    if calls is None:  # chat-type example
        return None
    if ex.get("context") and ex["context"] not in CONTEXTS:
        return "bad context"
    for c in calls:
        t = tools_by_name.get(c.get("name"))
        if not t:
            return f"unknown tool {c.get('name')}"
        err = check_args(t["parameters"], c.get("arguments") or {})
        if err:
            return f"{c['name']}: {err}"
    if len(ex.get("tool_results") or []) != len(calls):
        return "results/calls mismatch"
    if not calls and kind in ("no_action", "cant_do", "clarify", "standby") and CLAIM.search(reply) and "?" not in reply:
        if re.search(r"\b(done|opened|closed|set|saved|skipped|copied|typed)\b", reply, re.I):
            return "claims an action without a tool"
    if kind in ("no_action", "cant_do", "clarify", "standby") and calls:
        return f"{kind} example has tool calls"
    if kind == "standby" and any(c["name"] in ("power", "lock_pc") for c in calls):
        return "standby touched power"
    if kind == "tool" and not calls and "?" not in reply:
        return "tool job without a call"
    if kind == "compound" and len(calls) < 2:
        return "compound with fewer than 2 calls"
    if kind == "followup" and not ex.get("history"):
        return "followup without history"
    if kind == "errors" and not calls:
        return "error example without a call"
    if kind == "errors" and re.search(r"\b(done|all set|successfully)\b", reply, re.I):
        return "error example claims success"
    browser_ops = [c["name"] for c in calls if c["name"].startswith("browser_") and c["name"] != "browser_open"]
    if (browser_ops and (ex.get("context") or "none") in ("none", "spotify", "notepad") and not ex.get("history")
            and not any(c["name"] == "browser_open" for c in calls)):
        return "browser tool with no browser open"
    if kind == "power" and not any(c["name"] == "power" for c in calls):
        return "power example without power call"
    if any(c["name"] == "power" and (c.get("arguments") or {}).get("confirmed") for c in calls):
        return "power with confirmed"
    return None


def norm(s):
    return re.sub(r"[^a-z0-9ऀ-ॿ஀-௿ఀ-౿ ]+", "", s.lower()).strip()


# %%
# ── the run ──────────────────────────────────────────────────────────────────
from concurrent.futures import ThreadPoolExecutor, as_completed

rng = random.Random(SEED)
DATA = os.path.join(OUT_DIR, "zoha_teacher_data.jsonl")
REJ = os.path.join(OUT_DIR, "zoha_teacher_rejected.jsonl")
STATS = os.path.join(OUT_DIR, "zoha_teacher_stats.json")
lock = threading.Lock()
deadline = T0 + HOURS_BUDGET * 3600
seen, stats = set(), {"accepted": 0, "rejected": 0, "judge_dropped": 0, "calls": 0, "failed_calls": 0, "by_kind": {}, "reasons": {}}
if os.path.exists(DATA):  # resume
    for line in open(DATA, encoding="utf-8"):
        try:
            seen.add(norm(json.loads(line)["user"]))
            stats["accepted"] += 1
        except Exception:
            pass
    log(f"resuming: {stats['accepted']} examples already saved")


def salvage(text):
    """The answer was cut off mid-JSON: keep every example object that was finished."""
    out = {"examples": []}
    dec = json.JSONDecoder()
    m = re.search(r'"tools"\s*:\s*(\[)', text)
    if m:
        try:
            out["tools"], _ = dec.raw_decode(text, m.start(1))
        except Exception:
            pass
    m = re.search(r'"(?:examples|verdicts)"\s*:\s*\[', text)
    if not m:
        return out
    key = "verdicts" if '"verdicts"' in m.group(0) else "examples"
    i = m.end()
    items = []
    while True:
        while i < len(text) and text[i] in " \n\r\t,":
            i += 1
        if i >= len(text) or text[i] != "{":
            break
        try:
            obj, i = dec.raw_decode(text, i)
            items.append(obj)
        except Exception:
            break
    out[key] = items
    return out


SALVAGED = {"n": 0}
TOK = {"gen": 0, "prompt": 0}


def chat(system, user, schema, temperature, num_predict=4096):
    body = {"model": TEACHER, "stream": False, "think": False, "keep_alive": -1, "format": schema,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "options": {"temperature": temperature, "top_p": 0.95, "num_ctx": NUM_CTX, "num_predict": num_predict}}
    for attempt in range(3):
        try:
            r = http("/api/chat", body, timeout=600)
            with lock:
                TOK["gen"] += r.get("eval_count") or 0
                TOK["prompt"] += r.get("prompt_eval_count") or 0
            txt = (r.get("message") or {}).get("content") or "{}"
            try:
                return json.loads(txt)
            except json.JSONDecodeError:
                got = salvage(txt)
                if got.get("examples") or got.get("verdicts") or attempt == 2:
                    SALVAGED["n"] += 1
                    return got
                body["options"]["temperature"] = max(0.5, temperature - 0.2)   # nothing usable – try once more
        except Exception:
            if attempt == 2 or time.time() > deadline:
                raise
            time.sleep(3 + attempt * 5)
    return {}


JUDGE_SCHEMA = {"type": "object", "required": ["verdicts"], "properties": {"verdicts": {"type": "array", "items": {
    "type": "object", "required": ["i", "ok", "why"], "properties": {"i": {"type": "integer"}, "ok": {"type": "boolean"},
                                                              "why": {"type": "string"}}}}}}


JUDGE_LOG = {"n": 0}


def judge(examples, tools_text):
    listing = "\n".join(f"[{i}] user: {e['user']!r} | context: {e.get('context', '-')} | history: {e.get('history') or []} | "
                        f"calls: {json.dumps(e.get('calls'), ensure_ascii=False) if e.get('calls') is not None else '-'} | "
                        f"results: {e.get('tool_results', '-')} | reply: {e['reply']!r}" for i, e in enumerate(examples))
    q = ("Review each training example. Mark ok=false ONLY for clear mistakes: wrong tool or wrong argument for what the user meant; "
         "a needed action missing; an action taken on plain small talk; the reply claims something the calls didn't do; a factually "
         "wrong answer; or a reply in a different language than the user. Small style differences are fine (ok=true). "
         "why: a few words for ok=false, \"\" for ok=true.\n" + listing + "\nReturn verdicts for every index.")
    sys_ = "You review training data for Zoha, an AI assistant.\n\n" + ZOHA_RULES + ("\n\nTOOLS:\n" + tools_text if tools_text else "")
    v = chat(sys_, q, JUDGE_SCHEMA, 0.1, num_predict=900)
    bad = {}
    for d in v.get("verdicts", []):
        if not d.get("ok", True) and isinstance(d.get("i"), int):
            bad[d["i"]] = d.get("why", "")
    for i, why in bad.items():
        if JUDGE_LOG["n"] < 40 and 0 <= i < len(examples):
            JUDGE_LOG["n"] += 1
            log(f"  judge dropped: {examples[i]['user'][:70]!r} → {json.dumps(examples[i].get('calls'), ensure_ascii=False)[:90]} "
                f"| reply {examples[i]['reply'][:60]!r} | why: {(why or 'no reason')[:100]}")
    return [e for i, e in enumerate(examples) if i not in bad], [{"why": "judge: " + (w or "no reason"), "ex": examples[i]}
                                                                 for i, w in bad.items() if 0 <= i < len(examples)]


def run_job(job):
    kind, p = job
    jrng = random.Random(zlib.crc32(json.dumps(job, sort_keys=True).encode()) ^ SEED)
    if kind == "tool":
        gtext = compact_tools(group_for(p["tool"]))
        sys_ = ("You write high-quality training data for Zoha, an AI assistant. Every example must follow Zoha's rules exactly; "
                "they are what the student model will learn.\n\n" + ZOHA_RULES + "\n\nRELEVANT ZOHA TOOLS (she has others too):\n" + gtext)
        out = chat(sys_, prompt_tool(jrng, p), EX_DESKTOP, 0.95)
        tools, tools_text, sub = TOOLS_BY_NAME, gtext, p["tool"]
    elif kind == "special":
        out = chat(SYSTEM_GEN, prompt_special(jrng, p), EX_DESKTOP, 0.95)
        tools, tools_text, sub = TOOLS_BY_NAME, DESKTOP_TOOLS_TEXT, p["kind"]
    elif kind == "core":
        out = chat(SYSTEM_GEN_NOTOOLS, prompt_core(jrng, p), EX_CORE, 0.9)
        own = [t for t in (out.get("tools") or []) if isinstance(t, dict) and re.fullmatch(r"[a-z][a-z0-9_]{2,40}", str(t.get("name", "")))
               and isinstance(t.get("parameters"), dict)]
        tools = {t["name"]: t for t in own}
        tools_text, sub = compact_tools(own), p["domain"]
        if len(own) < 3:
            return kind, sub, [], [{"why": "bad tool set"}], 0
    else:
        prompt = prompt_explain(jrng, p) if kind == "explain" else prompt_persona(jrng, p)
        out = chat(SYSTEM_GEN_NOTOOLS, prompt, EX_CHAT, 0.8)
        tools, tools_text, sub = {}, "", p.get("topic", "persona")
    good, bad = [], []
    for ex in out.get("examples") or []:
        if not isinstance(ex, dict):
            continue
        if kind in ("explain", "persona"):
            ex["calls"] = None
        why = validate(ex, tools, p.get("kind", kind))
        if why:
            bad.append({"why": why, "ex": ex})
        else:
            good.append(ex)
    dropped = 0
    if JUDGE and good:
        if kind in ("special", "tool"):  # judge only needs the tools these examples actually use
            used = sorted({c["name"] for e in good for c in (e.get("calls") or [])} | ({p["tool"]} if kind == "tool" else set()))
            tools_text = compact_tools([TOOLS_BY_NAME[n] for n in used if n in TOOLS_BY_NAME]) or "(no tools used)"
        good, jbad = judge(good, tools_text)
        dropped = len(jbad)
        bad += jbad
    rows = []
    for ex in good:
        row = {"kind": kind if kind != "special" else p["kind"], "topic": sub, "user": ex["user"].strip(), "lang": ex.get("lang", ""),
               "modality": ex.get("modality") or "voice", "context": ex.get("context") or "none", "history": ex.get("history") or [],
               "calls": ex.get("calls") if ex.get("calls") is not None else [], "tool_results": ex.get("tool_results") or [],
               "reply": ex["reply"].strip()}
        if kind == "core":
            row["tools"] = list(tools.values())
        rows.append(row)
    return kind, sub, rows, bad, dropped


jobs = jobs_plan(rng)
log(f"{len(jobs)} jobs planned · teacher {TEACHER} · target {TARGET_EXAMPLES} · budget {HOURS_BUDGET} h")
done_jobs = 0
with open(DATA, "a", encoding="utf-8") as fout, open(REJ, "a", encoding="utf-8") as frej, ThreadPoolExecutor(CONCURRENCY) as pool:
    it = iter(jobs)
    running = set()

    def submit_next():
        try:
            running.add(pool.submit(run_job, next(it)))
        except StopIteration:
            pass

    for _ in range(CONCURRENCY + 2):
        submit_next()
    while running:
        fut = next(as_completed(running))
        running.discard(fut)
        stats["calls"] += 1
        try:
            kind, sub, rows, bad, dropped = fut.result()
        except Exception as e:
            stats["failed_calls"] += 1
            log("job failed:", str(e)[:200])
            rows, bad, dropped, kind = [], [], 0, "?"
        with lock:
            for r in rows:
                k = norm(r["user"])
                if not k or k in seen:
                    stats["rejected"] += 1
                    stats["reasons"]["duplicate"] = stats["reasons"].get("duplicate", 0) + 1
                    continue
                seen.add(k)
                r["id"] = f"t{len(seen):06d}"
                r["split"] = "test" if rng.random() < TEST_SHARE else "train"
                r["teacher"] = f"{TEACHER} (Qwen3.5, Apache-2.0)"
                r["created"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
                fout.write(json.dumps(r, ensure_ascii=False) + "\n")
                stats["accepted"] += 1
                stats["by_kind"][r["kind"]] = stats["by_kind"].get(r["kind"], 0) + 1
            for b in bad:
                stats["rejected"] += 1
                w = b["why"].split(":")[0][:40]
                stats["reasons"][w] = stats["reasons"].get(w, 0) + 1
                frej.write(json.dumps(b, ensure_ascii=False) + "\n")
            stats["judge_dropped"] += dropped
            fout.flush()
        done_jobs += 1
        el = time.time() - T0
        if done_jobs % 10 == 0 or not running:
            rate = stats["accepted"] / max(el, 1) * 3600
            log(f"{done_jobs}/{len(jobs)} jobs · {stats['accepted']} examples · {rate:.0f}/h · rejected {stats['rejected']} · "
                f"judge dropped {stats['judge_dropped']} · salvaged {SALVAGED['n']} · failed {stats['failed_calls']} · "
                f"{TOK['gen'] / max(el, 1):.0f} tok/s · {el / 3600:.1f} h elapsed · ~{max(0, (deadline - time.time()) / 3600):.1f} h left")
            if done_jobs == 10 or done_jobs % 100 == 0:
                log("   rejection reasons so far:", dict(sorted(stats["reasons"].items(), key=lambda kv: -kv[1])[:8]))
            json.dump(dict(stats, teacher=TEACHER, tokens=TOK, elapsed_h=round(el / 3600, 2)), open(STATS, "w"), indent=1)
        if time.time() < deadline and stats["accepted"] < TARGET_EXAMPLES:
            submit_next()

el = time.time() - T0
json.dump(dict(stats, teacher=TEACHER, tokens=TOK, elapsed_h=round(el / 3600, 2), finished=True), open(STATS, "w"), indent=1)
log(f"FINISHED: {stats['accepted']} examples in {el / 3600:.1f} h → {DATA}")
log("by kind:", stats["by_kind"])
log("rejection reasons:", stats["reasons"])

# %%
# ── a few random examples to eyeball ─────────────────────────────────────────
rows = [json.loads(l) for l in open(DATA, encoding="utf-8")]
for r in random.Random(7).sample(rows, min(12, len(rows))):
    print(f"[{r['kind']}/{r['lang'][:12]}] {r['user']}")
    if r["calls"]:
        print("   →", json.dumps(r["calls"], ensure_ascii=False)[:200])
    print("   Zoha:", r["reply"][:200], "\n")
