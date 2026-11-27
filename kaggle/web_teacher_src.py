# %% [markdown]
# # Zoha web teacher — tested web pages for training (Zhessor)
#
# The UICoder recipe: an open-weight teacher (**Qwen3.5-35B-A3B, Apache-2.0**, running inside this notebook)
# writes hundreds of landing pages for Mumbai businesses from Zoha's starter. Every page is repaired, checked by
# code and **opened in a real headless browser (desktop + phone)**. Only clean pages are kept and
# near-duplicates are dropped. The result teaches Zoha's own model to write pages like that in one go.
#
# **How to run**
# 1. Right panel → **Session options**: Accelerator **GPU T4 x2**, Internet **On**.
# 2. Top right → **Save Version** → **Save & Run All (Commit)**. It keeps running with the browser closed.
# 3. When it finishes (about 9–10 h), open the version → **Output** → download `zoha_web_pages.jsonl`
#    (plus `zoha_web_stats.json` and `web_samples.zip` to look at some pages).
#
# It stops by itself before Kaggle's 12-hour limit and saves what it has.
# **Don't cancel a running version** – Kaggle throws away the output of cancelled runs.

# %%
# ── settings ────────────────────────────────────────────────────────────────
import os
TEACHERS = ["qwen3.5:35b-a3b-q4_K_M", "qwen3.5:27b-q4_K_M", "qwen3.5:9b"]  # first one that loads wins
TARGET_EXAMPLES = 900            # clean pages to aim for (it stops earlier at the time budget)
HOURS_BUDGET = 10.75             # hard stop (Kaggle sessions end at 12 h); output is saved only if the run ends by itself
PARALLEL = 8                     # max simultaneous requests (auto-tuned to 4 or 8 after loading)
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
import json, random, re, subprocess, sys, threading, time, urllib.request, zlib
os.makedirs(OUT_DIR, exist_ok=True)
T0 = time.time()
LOG = open(os.path.join(OUT_DIR, "web_run_log.txt"), "a", encoding="utf-8")


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
NUM_CTX = 16384     # starter + skill (~6k tokens) + a full page (~5k tokens)
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
        for ctx in (NUM_CTX, 12288):
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
# ── browser for testing pages + Zoha's checker (embedded) ────────────────────
if not TEST_MODE:
    subprocess.run([sys.executable, "-m", "pip", "install", "-q", "playwright"], check=True)
    subprocess.run([sys.executable, "-m", "playwright", "install", "--with-deps", "chromium"], check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
CHECK_DIR = os.path.join(OUT_DIR, "_zoha_check")
os.makedirs(CHECK_DIR, exist_ok=True)
open(os.path.join(CHECK_DIR, "page_check.py"), "w", encoding="utf-8").write(PAGE_CHECK_SRC)
open(os.path.join(CHECK_DIR, "zoha_lint.py"), "w", encoding="utf-8").write(LINT_SRC)
open(os.path.join(CHECK_DIR, "web_kit.py"), "w", encoding="utf-8").write(WEB_KIT_SRC)
open(os.path.join(CHECK_DIR, "web3d.py"), "w", encoding="utf-8").write(WEB3D_SRC)
open(os.path.join(CHECK_DIR, "web_showroom.py"), "w", encoding="utf-8").write(WEB_SHOWROOM_SRC)
sys.path.insert(0, CHECK_DIR)
import page_check, zoha_lint, web_kit   # noqa: E402
log("checker ready")

# %%
# ── what to build: Mumbai businesses × areas × extra wishes ──────────────────
BUSINESSES = [
    ("salon", "a unisex hair and beauty salon"), ("salon", "a bridal makeup studio"), ("café", "a specialty coffee café"),
    ("café", "a home bakery that takes custom cake orders"), ("café", "a South Indian breakfast joint"),
    ("café", "a cloud kitchen selling healthy tiffins"), ("interiors", "a modular kitchen company"),
    ("interiors", "an interior design studio for 1–2 BHK flats"), ("interiors", "an architecture firm"),
    ("fitness", "a strength-training gym"), ("fitness", "a yoga and pilates studio"), ("fitness", "a dance academy"),
    ("clinic", "a dental clinic"), ("clinic", "a physiotherapy centre"), ("clinic", "a pediatric clinic"),
    ("clinic", "a diagnostic lab with home sample collection"), ("clinic", "a skin and hair clinic"),
    ("retail", "a kids' toy and stationery store"), ("retail", "a women's ethnic wear boutique"),
    ("retail", "a mobile phone repair shop"), ("retail", "an eyewear store"), ("retail", "a jewellery showroom"),
    ("retail", "a pet grooming and supplies shop"), ("retail", "an electronics and laptop service centre"),
    ("clinic", "a chartered accountant firm for small businesses"), ("retail", "a coaching institute for JEE/NEET"),
    ("retail", "a spoken-English and IELTS academy"), ("café", "a family restaurant serving Malvani food"),
    ("interiors", "a real-estate agent for rentals"), ("retail", "a photography studio for weddings and pre-weddings"),
    ("retail", "an event planner for birthdays and corporate events"), ("fitness", "a swimming academy for kids"),
    ("retail", "a car detailing and service garage"), ("retail", "a florist with same-day delivery"),
    ("clinic", "an ayurvedic wellness centre"), ("retail", "a printing and signage shop"),
]
AREAS = ["Bandra West", "Andheri East", "Andheri West", "Powai", "Thane West", "Kharghar", "Vashi", "Borivali West",
         "Malad West", "Goregaon East", "Dadar", "Chembur", "Mulund", "Ghatkopar", "Juhu", "Lower Parel", "Colaba",
         "Santacruz", "Vile Parle", "Kandivali", "Mira Road", "Panvel", "Navi Mumbai Sector 17", "Worli"]
WISHES = ["", "", "Add an FAQ section with 4 questions.", "Add a pricing table with 3 packages.",
          "Add a 'How it works' section with 3 steps.", "Add a gallery section of 6 labelled tiles.",
          "Add a team section with 3 people.", "Add opening hours and a 'Get directions' link.",
          "Make the tone premium and calm.", "Make the tone friendly and energetic.",
          "Mention home delivery across nearby areas.", "Add an offer banner for first-time customers.",
          "Add a Google reviews highlight with rating and count.", "Mention parking and wheelchair access."]

STARTER = STARTER_SRC
SKILL = SKILL_SRC.replace("{year}", "2026")
SHORT = SHORT_PROMPT_SRC


def long_prompt(name, what, seed):   # the same kind of prompt Zoha's writer sends – a different designed starter each time
    start_html, design = web_kit.build_starter(f"{what} {name}", seed=seed)
    return (f"Make the web page {name}. Request: {what}\n\n{SKILL}\n\n"
            f"START FROM THIS STARTER FILE ({design}). It was designed for this business and already has a correct nav, "
            "form, WhatsApp button, SEO tags and responsive CSS. KEEP ITS LAYOUT, class names, colours, fonts and scripts. "
            "Replace EVERY placeholder (BUSINESS, AREA, YEAR, 'Specific promise…', 'Offering name', 'Fact about them', "
            "'Short, believable review', '…', XXX numbers where you can) with real, specific content for this business. "
            "Repeat the commented items to the count shown with ₹ prices. Keep every nav link's #id matching a section id. "
            "Remove all HTML comments. Keep it compact: under 330 lines."
            "\n\nSTARTER:\n" + start_html + "\n\nOutput ONLY the complete finished file – no explanation, no markdown fences.")


def jobs(rng):
    while True:
        kind, biz = rng.choice(BUSINESSES)
        area = rng.choice(AREAS)
        wish = rng.choice(WISHES)
        slug = re.sub(r"[^a-z]+", "_", re.sub(r"^(a|an) ", "", biz).lower()).strip("_")[:28] or "page"
        what = f"a landing page for {biz} in {area}, Mumbai. {wish}".strip()
        yield {"kind": kind, "biz": biz, "area": area, "name": f"{slug}.html", "what": what}

# %%
# ── generate → repair → check → test in a browser → keep the clean ones ─────
import concurrent.futures as cf, hashlib, zipfile
DATA = os.path.join(OUT_DIR, "zoha_web_pages.jsonl")
REJ = os.path.join(OUT_DIR, "zoha_web_rejected.jsonl")
STATS = os.path.join(OUT_DIR, "zoha_web_stats.json")
deadline = T0 + HOURS_BUDGET * 3600
stats = {"kept": 0, "rejected": 0, "duplicate": 0, "too_long": 0, "reasons": {}}
browser_lock = threading.Lock()
kept_shingles = []


def visible_text(html):
    t = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", html, flags=re.S | re.I)
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", t)).lower()


def shingles(text, k=5):
    w = text.split()
    return {hashlib.md5(" ".join(w[i:i + k]).encode()).hexdigest()[:12] for i in range(max(0, len(w) - k + 1))}


def is_duplicate(sh):
    for other in kept_shingles[-400:]:
        if len(sh & other) / max(1, len(sh | other)) > 0.55:
            return True
    return False


def clean(text):
    m = re.search(r"```[\w+-]*\n(.*?)```", text, re.S)
    text = (m.group(1) if m else text).strip()
    text = re.sub(r"<!--.*?-->", "", text, flags=re.S)
    return zoha_lint.strip_layers(text) + "\n"   # train on what the model should write; Zoha adds motion/3D/guards itself


def write_page(job, temperature):
    r = http("/api/chat", {"model": TEACHER, "stream": False, "think": False, "keep_alive": -1,
                           "messages": [{"role": "user", "content": long_prompt(job["name"], job["what"], str(random.random()))}],
                           "options": {"num_predict": 7000, "num_ctx": NUM_CTX, "temperature": temperature}}, timeout=1500)
    return clean((r.get("message") or {}).get("content") or ""), r.get("eval_count") or 0


def fix_page(job, html, problems):
    r = http("/api/chat", {"model": TEACHER, "stream": False, "think": False, "keep_alive": -1,
                           "messages": [{"role": "user", "content":
                               f"Here is {job['name']}.\n\n{html}\n\nFix EXACTLY these problems and change nothing else:\n- "
                               + "\n- ".join(problems) + "\n\nOutput ONLY the complete corrected file – no notes, no fences."}],
                           "options": {"num_predict": 7000, "num_ctx": NUM_CTX, "temperature": 0.2}}, timeout=1500)
    return clean((r.get("message") or {}).get("content") or "")


def test(job, html, n):
    p = os.path.join(CHECK_DIR, f"t{n}.html")
    full = zoha_lint.final_cleanup(zoha_lint.autofix_html(html))   # test it the way Zoha ships it
    open(p, "w", encoding="utf-8").write(full)
    lint = zoha_lint.lint_html(full)
    with browser_lock:   # one browser at a time keeps Kaggle's CPU free for the teacher
        try:
            browser = page_check.check_page(__import__("pathlib").Path(p), None)
        except Exception as e:
            browser = [f"browser check crashed: {e}"]
    return lint + browser


def run_job(job, n):
    html, toks = write_page(job, random.choice([0.5, 0.7, 0.85]))
    if "</html>" not in html.lower():
        return job, None, ["cut off"]
    problems = test(job, html, n)
    if problems:   # one repair round, like Zoha does
        fixed = fix_page(job, html, problems)
        if "</html>" in fixed.lower():
            p2 = test(job, fixed, n)
            if len(p2) < len(problems):
                html, problems = fixed, p2
    return job, html, problems


rng = random.Random(SEED)
plan = jobs(rng)
samples = zipfile.ZipFile(os.path.join(OUT_DIR, "web_samples.zip"), "w", zipfile.ZIP_DEFLATED)
n = 0
log(f"web teacher {TEACHER} · {CONCURRENCY} streams · target {TARGET_EXAMPLES} · budget {HOURS_BUDGET} h")
with open(DATA, "a", encoding="utf-8") as fout, open(REJ, "a", encoding="utf-8") as frej, cf.ThreadPoolExecutor(CONCURRENCY) as pool:
    futs = {pool.submit(run_job, next(plan), i): i for i in range(CONCURRENCY + 2)}
    n = len(futs)
    while futs:
        done, _ = cf.wait(futs, return_when=cf.FIRST_COMPLETED)
        for f in done:
            futs.pop(f)
            try:
                job, html, problems = f.result()
            except Exception as e:
                stats["rejected"] += 1
                stats["reasons"]["error"] = stats["reasons"].get("error", 0) + 1
                log("job failed:", e)
                html, problems, job = None, ["error"], None
            if html and not problems:
                sh = shingles(visible_text(html))
                if len(html) > 26000:
                    stats["too_long"] += 1
                elif is_duplicate(sh):
                    stats["duplicate"] += 1
                else:
                    kept_shingles.append(sh)
                    short = SHORT.replace("{name}", job["name"]).replace("{what}", job["what"]).replace("{year}", "2026")
                    fout.write(json.dumps({"kind": job["kind"], "business": job["biz"], "area": job["area"],
                                           "prompt": short, "page": html, "teacher": f"{TEACHER} (Qwen3.5, Apache-2.0)"},
                                          ensure_ascii=False) + "\n")
                    fout.flush()
                    stats["kept"] += 1
                    if stats["kept"] <= 40:
                        samples.writestr(f"{stats['kept']:02d}_{job['name']}", html)
            elif job:
                stats["rejected"] += 1
                for p in problems[:3]:
                    key = p.split(" – ")[0].split(":")[0][:60]
                    stats["reasons"][key] = stats["reasons"].get(key, 0) + 1
                frej.write(json.dumps({"job": job, "problems": problems[:6]}, ensure_ascii=False) + "\n")
            el = time.time() - T0
            if stats["kept"] % 10 == 0 or not html:
                log(f"kept {stats['kept']} · rejected {stats['rejected']} · dup {stats['duplicate']} · {el / 3600:.1f} h")
            json.dump(dict(stats, teacher=TEACHER, elapsed_h=round(el / 3600, 2)), open(STATS, "w"), indent=1)
            if stats["kept"] < TARGET_EXAMPLES and time.time() < deadline - 1500:
                futs[pool.submit(run_job, next(plan), n)] = n
                n += 1
samples.close()
json.dump(dict(stats, teacher=TEACHER, elapsed_h=round((time.time() - T0) / 3600, 2), finished=True), open(STATS, "w"), indent=1)
log("FINISHED:", stats["kept"], "clean pages")
