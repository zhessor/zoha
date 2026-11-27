"""
Zoha stress-test cases: ~10,000 things a user might say, each with the correct answer.

    python -m stress.cases            # writes data/stress/cases.jsonl (same seed → same cases)

Expectations ("expect"):
  any      – at least one tool call must match one of these specs
  all      – every spec must be matched by some call (compound commands)
  none     – no tool should run (chat); "allow" lists harmless tools that are also fine
  honest   – Zoha can't do this: no fake "done", no destructive tool
  confirm  – power action: must go through the confirmation step, never confirmed=true on its own
  nopower  – sounds like "sleep"/"bye": must NOT touch power
A spec is {"tools": [...], "args": {key: {"in": [...]} | {"has": [...]} | {"num": n} | {"any": true}}}.
"""
from __future__ import annotations

import json
import random
from pathlib import Path

SEED = 1611
TARGET = 10000

# ── vocabulary ───────────────────────────────────────────────────────────────
SONGS = ["Perfect by Ed Sheeran", "Shape of You", "Believer by Imagine Dragons", "Blinding Lights", "Kesariya", "Tum Hi Ho",
         "Apna Bana Le", "Heeriye", "Chaleya", "Satranga", "Pasoori", "Kun Faya Kun", "Channa Mereya", "Raataan Lambiyan",
         "Middle of the Night", "Night Changes", "Let Her Go", "Faded by Alan Walker", "Senorita", "Despacito", "Levitating",
         "Stay by Justin Bieber", "Calm Down by Rema", "As It Was", "Heat Waves", "Starboy", "Lover by Taylor Swift",
         "Shake It Off", "Bohemian Rhapsody", "Numb by Linkin Park", "In the End", "Hotel California", "Yellow by Coldplay",
         "Viva La Vida", "Fix You", "See You Again", "Lose Yourself", "Mockingbird", "Rap God", "Without Me",
         "Arijit Singh songs", "AP Dhillon", "Diljit Dosanjh songs", "Prateek Kuhad", "lofi hip hop", "lofi beats to study to",
         "rain sounds", "white noise", "piano music for studying", "Interstellar soundtrack", "Hans Zimmer", "Marathi songs",
         "Zingaat", "Lag Ja Gale", "Kishore Kumar songs", "old Bollywood songs", "Sufi songs", "Coke Studio", "KK songs",
         "Atif Aslam", "Mohit Chauhan", "Sid Sriram", "Anirudh songs", "Naatu Naatu", "Jhoome Jo Pathaan", "Kesariya slowed reverb",
         "workout music", "motivational songs", "Eminem", "The Weeknd", "Arctic Monkeys", "505", "Sweater Weather",
         "Daylight by David Kushner", "Until I Found You", "Die With A Smile", "Espresso by Sabrina Carpenter", "APT",
         "Tere Vaaste", "Ve Kamleya", "O Maahi", "Husn by Anuv Jain", "Baarishein", "Alag Aasmaan", "Gul by Anuv Jain"]
VIDEOS = ["linear algebra one shot", "DSA in one video", "Java full course", "Python tutorial for beginners", "operating systems one shot",
          "DBMS full course", "computer networks lecture", "discrete mathematics one shot", "how to make a voice assistant in Python",
          "Next.js 16 tutorial", "Tailwind CSS crash course", "React hooks explained", "system design basics", "CAT preparation strategy",
          "quantitative aptitude tricks", "Mumbai street food vlog", "MKBHD latest review", "iPhone review", "RTX 5060 review",
          "how transformers work", "neural networks explained", "Fireship 100 seconds", "Dhruv Rathee latest video", "stand up comedy",
          "Zakir Khan", "Samay Raina", "cricket highlights", "India vs Australia highlights", "IPL highlights", "F1 highlights",
          "Valorant tips", "BGMI gameplay", "chess openings for beginners", "how to study for exams", "Pomodoro study with me",
          "engineering mathematics 3 one shot", "data structures stacks and queues", "Gate Smashers DBMS", "Apna College DSA",
          "Kunal Kushwaha Java", "Striver DSA sheet", "Love Babbar", "CodeWithHarry Python", "Abdul Bari algorithms", "3Blue1Brown"]
APPS = [("notepad", ["notepad"]), ("calculator", ["calc"]), ("VS Code", ["code", "vs"]), ("Visual Studio Code", ["code"]),
        ("Chrome", ["chrome"]), ("Google Chrome", ["chrome"]), ("Edge", ["edge"]), ("Spotify", ["spotify"]), ("Discord", ["discord"]),
        ("WhatsApp", ["whatsapp"]), ("Word", ["word"]), ("Microsoft Word", ["word"]), ("Excel", ["excel"]), ("PowerPoint", ["powerpoint", "ppt"]),
        ("File Explorer", ["explorer", "file"]), ("Settings", ["setting"]), ("Task Manager", ["task"]), ("Paint", ["paint"]),
        ("Steam", ["steam"]), ("OBS", ["obs"]), ("Zoom", ["zoom"]), ("Teams", ["teams"]), ("Windsurf", ["windsurf"]),
        ("Telegram", ["telegram"]), ("Command Prompt", ["cmd", "command"]), ("PowerShell", ["powershell"]), ("Terminal", ["terminal"]),
        ("Snipping Tool", ["snip"]), ("Camera", ["camera"]), ("Photos", ["photo"]), ("Clock", ["clock"]), ("Calendar app", ["calendar"]),
        ("Microsoft Store", ["store"]), ("Postman", ["postman"]), ("Figma", ["figma"]), ("Canva", ["canva"]), ("Blender", ["blender"]),
        ("Unity Hub", ["unity"]), ("IntelliJ", ["intellij"]), ("Eclipse", ["eclipse"]), ("Android Studio", ["android"]),
        ("Notion", ["notion"]), ("Obsidian", ["obsidian"]), ("VLC", ["vlc"]), ("Outlook", ["outlook"]), ("OneNote", ["onenote"]),
        ("GitHub Desktop", ["github"]), ("Docker Desktop", ["docker"]), ("MongoDB Compass", ["mongo", "compass"]), ("Slack", ["slack"])]
SITES = [("GitHub", "github"), ("Gmail", "mail"), ("YouTube", "youtube"), ("Amazon", "amazon"), ("Flipkart", "flipkart"),
         ("LinkedIn", "linkedin"), ("Instagram", "instagram"), ("Twitter", "twitter|x.com"), ("Reddit", "reddit"),
         ("Stack Overflow", "stackoverflow|stack overflow"), ("ChatGPT", "chatgpt|openai"), ("Claude", "claude"), ("Netflix", "netflix"),
         ("Hotstar", "hotstar"), ("Google Drive", "drive"), ("Google Docs", "docs"), ("Vercel", "vercel"), ("Leetcode", "leetcode"),
         ("Codeforces", "codeforces"), ("GeeksforGeeks", "geeksforgeeks|gfg"), ("Wikipedia", "wikipedia"), ("Swiggy", "swiggy"),
         ("Zomato", "zomato"), ("Google Maps", "maps"), ("Google Calendar", "calendar"), ("Notion", "notion"), ("Figma", "figma"),
         ("Cricbuzz", "cricbuzz"), ("Times of India", "timesofindia|times")]
CITIES = ["Mumbai", "Thane", "Pune", "Navi Mumbai", "Delhi", "Bangalore", "Hyderabad", "Chennai", "Kolkata", "Nashik", "Nagpur",
          "Goa", "Lonavala", "Kharghar", "Panvel", "Dubai", "London", "New York", "Tokyo", "Singapore", "Shimla", "Manali", "Jaipur"]
NEWS = ["AI", "tech", "India", "cricket", "the stock market", "startups", "Mumbai", "politics", "space", "gaming", "Nvidia", "OpenAI",
        "Google", "Apple", "electric cars", "the economy", "football", "F1", "Bollywood", "science"]
LOOKUPS = ["who is the CEO of Nvidia", "what is the population of Mumbai", "who won the last IPL", "what is the price of Bitcoin today",
           "when is the next solar eclipse", "who is the prime minister of Japan", "what is the capital of Australia",
           "how tall is the Burj Khalifa", "who invented the telephone", "what is the latest iPhone", "how far is the moon",
           "what is the GDP of India", "who won the Ballon d'Or this year", "what's the Sensex at", "when does the CAT exam happen",
           "what is the boiling point of water", "who is the richest person in the world", "who directed Interstellar",
           "what is the speed of light", "when was ISRO founded", "what's the score in the India match", "dollar to rupee rate"]
NOTES = ["follow up with Harshil about the website launch", "buy milk and bread", "study OS chapter 4 tonight", "call the Sharma Interiors client",
         "submit the BillWise synopsis by Friday", "ask sir about the mini project marks", "renew the domain for zhessor", "pay the electricity bill",
         "revise DBMS normalisation", "send the proposal to Lotus Interiors", "practice two Leetcode problems", "charge the robot battery",
         "check the Neon usage", "buy a birthday gift for Riya", "the wifi password is on the router"]
FACTS = [("my sister's birthday is on 12 March", "12 march"), ("I like my coffee without sugar", "coffee"), ("my exam is on Monday", "exam"),
         ("my roll number is 67", "67"), ("I prefer lofi while studying", "lofi"), ("my best friend is Harshil", "harshil"),
         ("my college is IIT Bombay", "iit"), ("I wake up at 7 am", "7"), ("my favourite colour is teal", "teal"),
         ("Zhessor is my agency", "zhessor"), ("I use Windsurf for coding", "windsurf"), ("my GPU is an RTX 5060", "5060")]
FOLDERS = [("downloads", "download"), ("documents", "document"), ("desktop", "desktop"), ("pictures", "picture"), ("music", "music"),
           ("videos", "video"), ("my projects folder", "project"), ("the D drive", "d")]
FILES = ["resume", "BillWise synopsis", "Zhessor proposal", "OS notes", "the invoice", "my photo", "the robot code", "SIH presentation",
         "the Java project", "marksheet"]
CHAT_Q = ["Explain what a webhook is in two sentences.", "What is recursion?", "Explain normalization in DBMS simply.",
          "What's the difference between a process and a thread?", "Give me a quick tip to focus while studying.",
          "Tell me a joke.", "Write a two-line poem about Mumbai rain.", "What is the time complexity of binary search?",
          "Explain Big O notation like I'm five.", "What's a good name for a coffee shop?", "How do I stay calm before an exam?",
          "What is a deadlock?", "Explain TCP vs UDP.", "Summarise what an operating system does.", "What's 15 percent of 2400?",
          "Translate good morning into Marathi.", "What does API stand for?", "Give me three ideas for a college mini project.",
          "Explain what a LoRA fine-tune is.", "What is the difference between RAM and ROM?", "How many days are there until Diwali?",
          "What's a good way to revise a whole subject in one night?", "Explain paging in operating systems.",
          "What is a primary key?", "Motivate me, I have an exam tomorrow.", "Explain eigenvalues simply.", "What is a matrix inverse?",
          "Who are you?", "What can you do?", "What's your name?", "Are you better than Siri?", "Do you remember what I told you?"]
CHAT_SMALL = ["How are you doing today?", "Good morning Zoha", "Thank you so much", "You're awesome", "That was quick, nice",
              "I'm tired", "I'm bored", "Haha that's funny", "Okay cool", "Never mind", "Nothing, forget it", "Hmm let me think",
              "I closed the deal with the client today", "I watched a great video yesterday", "My sister plays the piano",
              "The volume of a cylinder is pi r squared h right", "I need to stop procrastinating", "I opened a new bank account",
              "The next exam is maths", "I paused my gym membership", "Play time is over, back to studies", "My friend set a new record",
              "I'm going to sleep early today", "Let's start studying", "I hate Mondays", "The weather is so nice today"]
GAPS = ["call Harshal and ask him about the data", "send a WhatsApp message to mom saying I'll be late", "order a pizza for me",
        "book an Uber to college", "transfer 500 rupees to Riya", "turn on the bedroom lights", "read my latest emails",
        "reply to the client's email", "post this on Instagram", "make a phone call to dad", "set the AC to 24 degrees",
        "print this document", "scan my handwritten notes", "join my Google Meet now", "record this lecture",
        "send the proposal to the client on email", "check my bank balance", "pay my electricity bill", "text Harshil happy birthday",
        "install Photoshop for me", "update Windows", "delete all my downloads", "format the D drive", "unsubscribe me from all newsletters"]
TIMER_UNITS = [("minute", 1), ("minutes", 1), ("min", 1), ("mins", 1), ("second", 1 / 60), ("seconds", 1 / 60), ("hour", 60), ("hours", 60)]
LABELS = ["", "", "", "for tea", "for focus", "for my break", "for the maggi", "for the laundry", "for revision", "for pomodoro", "for the meeting"]
WORDNUM = {1: "one", 2: "two", 3: "three", 4: "four", 5: "five", 10: "ten", 15: "fifteen", 20: "twenty", 25: "twenty five", 30: "thirty",
           45: "forty five", 50: "fifty", 60: "sixty", 90: "ninety"}
CLOCKS = [("6 pm", None), ("6:30 pm", None), ("7 am", None), ("9:15", None), ("10 pm", None), ("noon", None), ("5:28", None),
          ("528", None), ("8 in the evening", None), ("11:45 pm", None), ("4 o'clock", None), ("half past 3", None)]

# ── helpers ──────────────────────────────────────────────────────────────────
def S(tools, **args):
    return {"tools": tools if isinstance(tools, list) else [tools], "args": args}


def IN(*v):
    return {"in": [str(x).lower() for x in v]}


def HAS(*v):
    return {"has": [str(x).lower() for x in v]}


def NUM(v):
    return {"num": v}


YT = {"browser_open": True, "browser_url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
      "page": "Linear Algebra | Matrices One Shot - YouTube", "video": "playing at 12:41 of 1:58:03"}
YT_AD = {**YT, "video": "an ad is playing (skippable in 3s)"}
YT_PAUSED = {**YT, "video": "paused at 12:41 of 1:58:03"}
AMAZON = {"browser_open": True, "browser_url": "https://www.amazon.in/s?k=laptop+stand", "page": "Amazon.in : laptop stand"}
GITHUB = {"browser_open": True, "browser_url": "https://github.com/AK-0017/dev-portfolio", "page": "AK-0017/dev-portfolio"}
SPOTIFY = {"media": "Spotify: Kesariya – Arijit Singh (playing)"}
SPOTIFY_P = {"media": "Spotify: Kesariya – Arijit Singh (paused)"}
NOTHING = {}

LEADS = ["", "", "", "", "Zoha, ", "Zoha ", "Hey Zoha, ", "Hey Zoha ", "Okay Zoha, ", "Can you ", "Could you ", "Please ", "Zoha can you ",
         "Zoha please ", "Yo Zoha, ", "Hey, ", "Uh, ", "Um ", "Okay so ", "Quickly ", "I want you to ", "Do one thing, ", "Listen, "]
TAILS = ["", "", "", "", ".", ".", ".", " please", " please.", " for me", " right now", " now", " quickly", "?", ", thanks.",
         " yaar", " bro", ", okay?", " na"]
ASR = [("Zoha", "Sia"), ("Zoha", "Zea"), ("Zoha", "Gia"), ("skip", "skim"), ("volume", "value"), ("raise", "radius"), ("pause", "pose"),
       ("notepad", "note pad"), ("VS Code", "VS court"), ("YouTube", "you tube"), ("captions", "caption"), ("full screen", "fullscreen"),
       ("the", "da"), ("Spotify", "spotty fy"), ("timer", "time"), ("remind", "remained"), ("screenshot", "screen shot"),
       ("calculator", "calculated"), ("browser", "browsers"), ("subtitles", "subtitle"), ("next", "necks"), ("mute", "mood")]


SOFT_LEADS = ["", "", "", "Zoha, ", "Hey Zoha, ", "Okay, ", "Hmm, "]
SOFT_TAILS = ["", "", ".", "!", "?"]
COMMON = set("""what what's whats how how's who when where which is are do does can could will would tell give explain write translate
summarise summarize motivate turn set open close play pause stop make take put show go start launch resume skip next previous mute unmute
lock remind cancel search find type copy remember forget read check list delete add note jump seek restart replay hide disable enable
remove get speed slow increase decrease lower raise volume full exit come leave rewind back forward scroll reload refresh click maximise
minimise maximize minimize shut switch power reboot sleep send order book transfer post record install update format pay scan join
print reply text call unsubscribe let i'm i the that my thank thanks good you okay hmm haha never nothing""".split())


def dress(rng, core: str, lead=True, tail=True, soft=False) -> str:
    """Make a core command sound spoken: lead-ins, tails, casing, sometimes a mishearing."""
    t = core
    if lead:
        l = rng.choice(SOFT_LEADS if soft else LEADS)
        first = t.split()[0].lower().strip(",.?") if t.split() else ""
        if l and first in COMMON and first not in ("i", "i'm"):
            t = t[0].lower() + t[1:]
        t = l + t
    if tail:
        t = t.rstrip(".?!") + (rng.choice(SOFT_TAILS) if soft else rng.choice(TAILS))
        if soft and t[-1:] not in ".?!" and core.rstrip()[-1:] in "?":
            t += "?"
    if rng.random() < 0.12:
        a, b = rng.choice(ASR)
        if a.lower() in t.lower():
            i = t.lower().index(a.lower())
            t = t[:i] + b + t[i + len(a):]
    r = rng.random()
    if r < 0.45:
        t = t[:1].upper() + t[1:]
        if t[-1:] not in ".?!":
            t += "."
    elif r < 0.55:
        t = t.lower()
    return t.strip()


def pick(rng, seq):
    return rng.choice(seq)


# ── generators: each returns (category, text_core, ctx, history, expect) ─────
def g_media(rng):
    ctx = pick(rng, [SPOTIFY, SPOTIFY, SPOTIFY_P, NOTHING])
    acts = [("pause", ["pause the music", "pause the song", "pause it", "stop the music", "stop the song", "pause Spotify",
                       "hold the music", "pause", "stop playing", "can you stop this song", "mute the song for now, pause it",
                       "gaana band karo", "music band kar"], ["pause", "stop", "toggle"]),
            ("play", ["resume the music", "play the song again", "resume", "continue the song", "unpause", "play music",
                      "start the music again", "gaana chalu karo"], ["play", "toggle"]),
            ("next", ["next song", "skip this song", "play the next track", "next track", "skip", "change the song",
                      "agla gaana", "I don't like this song, next"], ["next"]),
            ("previous", ["previous song", "go back to the last song", "play the previous track", "last song again"], ["previous"]),
            ("status", ["what song is this", "what's playing right now", "which song is playing", "who sings this song",
                        "what's the name of this song"], ["status"])]
    kind, phr, ok = pick(rng, acts)
    tools = ["media_control"] + (["play_spotify"] if kind == "play" else [])
    return "media", pick(rng, phr), ctx, [], {"any": [S(tools, action=IN(*ok))] + ([S("play_spotify")] if kind == "play" else [])}


def g_volume(rng):
    r = rng.random()
    if r < 0.45:
        n = rng.choice([10, 20, 25, 30, 35, 40, 45, 50, 60, 65, 70, 75, 80, 90, 100, 5, 15])
        w = str(n) if rng.random() < 0.7 else WORDNUM.get(n, str(n))
        core = pick(rng, [f"set the volume to {w}", f"set volume to {w} percent", f"volume {w}", f"make the volume {w}%",
                          f"change the volume to {w}", f"put the volume at {w}", f"turn the volume to {w} percent",
                          f"raise the volume to {w}", f"lower the volume to {w}", f"volume {w} karo"])
        return "volume", core, NOTHING, [], {"any": [S("set_volume", level=NUM(n))]}
    if r < 0.8:
        up = rng.random() < 0.5
        core = pick(rng, ["turn the volume up", "increase the volume", "louder", "make it louder", "raise the volume", "volume up",
                          "turn it up a bit", "awaaz badhao", "I can't hear, increase the sound"] if up else
                    ["turn the volume down", "decrease the volume", "lower the volume", "quieter", "volume down", "too loud, reduce it",
                     "turn it down a little", "awaaz kam karo", "make it softer"])
        return "volume", core, pick(rng, [SPOTIFY, NOTHING]), [], {"any": [S(["set_volume"], change=IN("up" if up else "down")),
                                                                             S(["browser_video"], action=IN("volume"))]}
    if r < 0.93:
        mute = rng.random() < 0.6
        core = pick(rng, ["mute the PC", "mute the sound", "mute everything", "mute", "silence the computer"] if mute else
                    ["unmute", "unmute the sound", "turn the sound back on", "unmute the PC"])
        return "volume", core, NOTHING, [], {"any": [S("set_volume", change=IN("mute" if mute else "unmute")),
                                                     S("set_volume", level=NUM(0)) if mute else S("set_volume", change=IN("unmute"))]}
    n = rng.choice([150, 200, 250, 120, 300])
    return "volume", f"set the volume to {n} percent", NOTHING, [], {"any": [S("set_volume", level={"range": [100, n]})]}


def g_youtube(rng):
    q = pick(rng, SONGS + VIDEOS)
    key = q.lower().split(" by ")[0].split()[0]
    core = pick(rng, [f"play {q} on YouTube", f"play {q}", f"put on {q}", f"can you play {q}", f"search YouTube for {q} and play it",
                      f"I want to listen to {q}", f"play {q} in the browser", f"YouTube pe {q} chalao", f"play the video {q}",
                      f"open YouTube and play {q}", f"{q} on YouTube please", f"start {q} on YouTube", f"play some {q}"])
    exp = {"any": [S(["play_youtube"], query=HAS(key))]}
    if "spotify" in core.lower():
        exp = {"any": [S(["play_spotify"], query=HAS(key))]}
    if core.startswith("play some") or core.startswith("put on") or core.startswith("I want"):
        exp["any"].append(S(["play_spotify"], query=HAS(key)))
    return "youtube", core, pick(rng, [NOTHING, NOTHING, YT]), [], exp


def g_spotify(rng):
    q = pick(rng, SONGS)
    key = q.lower().split(" by ")[0].split()[0]
    core = pick(rng, [f"play {q} on Spotify", f"open Spotify and play {q}", f"Spotify pe {q} lagao", f"play {q} using Spotify",
                      f"put {q} on Spotify"])
    return "spotify", core, NOTHING, [], {"any": [S(["play_spotify"], query=HAS(key))]}


def g_video(rng):
    ctx = YT
    items = [
        (["make the video full screen", "full screen", "go full screen", "fullscreen the video", "maximise the video", "make it bigger",
          "video ko full screen karo", "put this in full screen"], S("browser_video", action=IN("fullscreen")), YT),
        (["exit full screen", "come out of full screen", "minimise the video", "leave full screen", "small screen please"],
         S("browser_video", action=IN("exit_fullscreen")), YT),
        (["pause the video", "pause the lecture", "stop the video", "pause it", "hold on, pause", "video rok do"],
         S(["browser_video", "media_control"], action=IN("pause", "stop", "toggle")), YT),
        (["play the video", "resume the video", "continue the lecture", "play it", "unpause the video"],
         S(["browser_video", "media_control"], action=IN("play", "toggle")), YT_PAUSED),
        (["mute the video", "mute this video", "mute the tab"], S("browser_video", action=IN("mute")), YT),
        (["skip 10 seconds", "forward 10 seconds", "go forward 30 seconds", "skip ahead a minute", "fast forward 15 seconds"],
         S("browser_video", action=IN("forward", "seek")), YT),
        (["go back 10 seconds", "rewind 10 seconds", "back 30 seconds", "I missed that, go back a bit"], S("browser_video", action=IN("back", "seek")), YT),
        (["go to 5 minutes", "jump to 10:30", "seek to 2 minutes in", "go to the 45 minute mark"], S("browser_video", action=IN("seek")), YT),
        (["start the video from the beginning", "restart the video", "play it from the start", "start learning from zero, play from the beginning",
          "replay this video", "go back to the start of the video"], S("browser_video", action=IN("restart", "seek")), YT),
        (["turn off the captions", "captions off", "hide the subtitles", "disable subtitles", "remove the CC",
          "captions are still on, can you please close them", "close the subtitles, I mean CC", "no subtitles please"],
         S("browser_video", action=IN("captions_off", "captions")), YT),
        (["turn on captions", "show subtitles", "enable CC", "put subtitles on", "I need captions for this"],
         S("browser_video", action=IN("captions_on", "captions")), YT),
        (["play it at 1.5x", "speed up the video", "set speed to 2x", "play at double speed", "slow down the video", "normal speed"],
         S("browser_video", action=IN("speed")), YT),
        (["skip the ad", "skip this ad", "skip ad", "get rid of this ad", "close the advertisement", "skim the ad"],
         S("browser_video", action=IN("skip_ad", "skip")), YT_AD),
        (["next video", "play the next video", "skip this video", "next one"], S(["browser_video", "media_control"], action=IN("next", "skip")), YT),
        (["what video is this", "how much of the video is left", "where am I in the video", "is the video paused"],
         S(["browser_video", "browser_read", "media_control"], action={"any": True}), YT),
        (["set the video volume to 50", "video volume 30"], S("browser_video", action=IN("volume")), YT),
    ]
    phr, spec, ctx = pick(rng, items)
    text = pick(rng, phr)
    specs = [spec]
    if text == "make it bigger":
        specs.append(S("browser_window", state=IN("maximize", "fullscreen")))
    return "video", text, ctx, [], {"any": specs}


def g_apps(rng):
    name, keys = pick(rng, APPS)
    if rng.random() < 0.72:
        core = pick(rng, [f"open {name}", f"launch {name}", f"start {name}", f"open up {name}", f"can you open {name} for me",
                          f"{name} kholo", f"bring up {name}", f"run {name}", f"I need {name}, open it"])
        return "apps", core, NOTHING, [], {"any": [S("open_app", name=HAS(*keys))]}
    core = pick(rng, [f"close {name}", f"quit {name}", f"exit {name}", f"kill {name}", f"shut {name}", f"{name} band karo",
                      f"close the {name} window"])
    return "apps", core, NOTHING, [], {"any": [S("close_app", name=HAS(*keys))]}


def g_sites(rng):
    name, key = pick(rng, SITES)
    core = pick(rng, [f"open {name}", f"go to {name}", f"open {name} in the browser", f"take me to {name}", f"load {name}",
                      f"open the {name} website", f"{name} kholo"])
    if name.lower() in ("notion", "figma", "claude") and "website" not in core and "browser" not in core:
        return "sites", core, NOTHING, [], {"any": [S(["open_website", "browser_open", "open_app"], **{"*": HAS(*key.split("|"))})]}
    return "sites", core, pick(rng, [NOTHING, NOTHING, GITHUB]), [], {"any": [S(["open_website", "browser_open", "play_youtube"], **{"*": HAS(*key.split("|"))})]}


def g_search(rng):
    q = pick(rng, ["laptop stands under 1500", "best mechanical keyboard", "how to fix CUDA out of memory", "Next.js middleware docs",
                   "RTX 5060 drivers", "cheap flights to Goa", "IIT Bombay results", "LoRA fine tuning guide",
                   "playwright python docs", "how to make cold coffee", "nearest pharmacy", "Ollama models list", "Zhessor"])
    core = pick(rng, [f"search for {q}", f"google {q}", f"search {q} on Google", f"look up {q} in the browser", f"find {q} online"])
    return "search", core, NOTHING, [], {"any": [S(["web_search", "browser_open", "web_lookup", "open_website"], **{"*": HAS(q.split()[0].lower())})]}


def g_info(rng):
    r = rng.random()
    if r < 0.3:
        c = pick(rng, CITIES)
        tm = rng.random() < 0.3
        core = pick(rng, [f"what's the weather in {c}{' tomorrow' if tm else ''}", f"how's the weather in {c}{' tomorrow' if tm else ''}",
                          f"will it rain in {c}{' tomorrow' if tm else ' today'}", f"{c} weather{' tomorrow' if tm else ''}",
                          f"is it hot in {c} right now", f"{c} ka mausam kaisa hai"])
        return "info", core, NOTHING, [], {"any": [S("get_weather", city=HAS(c.lower().split()[0]))]}
    if r < 0.4:
        core = pick(rng, ["what's the weather", "will it rain today", "how hot is it outside", "do I need an umbrella today"])
        return "info", core, NOTHING, [], {"any": [S("get_weather")]}
    if r < 0.55:
        core = pick(rng, ["what time is it", "what's the date today", "what day is it", "time kya hua hai", "tell me the time",
                          "what's today's date", "which day is today"])
        return "info", core, NOTHING, [], {"any": [S("get_datetime")], "none_ok": True}
    if r < 0.75:
        t = pick(rng, NEWS)
        core = pick(rng, [f"what's the latest news in {t}", f"any news about {t}", f"give me {t} headlines", f"what's happening in {t}",
                          "what's the news today", "read me the headlines"])
        return "info", core, NOTHING, [], {"any": [S(["news_headlines", "web_lookup", "web_search"])]}
    q = pick(rng, LOOKUPS)
    return "info", q, NOTHING, [], {"any": [S(["web_lookup", "web_search", "news_headlines", "browser_open"])]}


def g_pc(rng):
    items = [(["how's my PC doing", "check my system", "what's my CPU usage", "how much RAM is free", "is my GPU busy",
               "battery percentage", "system status", "how hot is my GPU"], S("system_status")),
             (["take a screenshot", "screenshot", "capture my screen", "grab a screenshot", "screenshot le lo"], S("take_screenshot")),
             (["lock my computer", "lock the PC", "lock the screen", "lock it"], S("lock_pc")),
             (["open my downloads folder", "show me my documents", "open the desktop folder", "open pictures"], S("open_folder")),
             ]
    phr, spec = pick(rng, items)
    return "pc", pick(rng, phr), NOTHING, [], {"any": [spec]}


def g_files(rng):
    if rng.random() < 0.5:
        f, key = pick(rng, FOLDERS)
        core = pick(rng, [f"open {f}", f"open my {f} folder", f"show me {f}", f"take me to {f}"])
        tools = ["open_folder", "open_path"] + (["find_files"] if key == "project" else [])  # Zoha can't know where "projects" is → search
        return "files", core, NOTHING, [], {"any": [S(tools, **{"*": HAS(key)})]}
    f = pick(rng, FILES)
    key = f.lower().replace("the ", "").replace("my ", "").split()[0]
    core = pick(rng, [f"find {f}", f"find {f} and open it", f"where is {f}", f"open {f}", f"search my files for {f}"])
    return "files", core, NOTHING, [], {"any": [S(["find_files", "open_path"], **{"*": HAS(key)})]}


def g_timer(rng):
    r = rng.random()
    if r < 0.45:
        unit, mult = pick(rng, TIMER_UNITS)
        n = rng.choice([1, 2, 3, 5, 10, 15, 20, 25, 30, 45]) if "hour" not in unit else rng.choice([1, 2])
        if "second" in unit:
            n = rng.choice([10, 20, 30, 45, 90])
        if n == 1:
            unit = unit.rstrip("s")
        w = str(n) if rng.random() < 0.7 else WORDNUM.get(n, str(n))
        lab = pick(rng, LABELS)
        core = pick(rng, [f"set a timer for {w} {unit} {lab}", f"timer {w} {unit} {lab}", f"start a {w} {unit} timer {lab}",
                          f"set the timer of {w} {unit}", f"remind me in {w} {unit}", f"{w} {unit} ka timer lagao"]).strip()
        mins = round(n * mult, 3)
        spec = {"tools": ["set_timer", "set_reminder"], "args": {"#minutes": NUM(mins)}}
        return "timer", core, NOTHING, [], {"any": [spec]}
    if r < 0.55:
        n = rng.choice([5, 10, 20, 25])
        return "timer", f"set a timer of {n}", NOTHING, [], {"any": [{"tools": ["set_timer"], "args": {"#minutes": NUM(n)}}]}
    if r < 0.85:
        msg = pick(rng, ["call Harshil", "drink water", "take my medicine", "start studying", "submit the assignment", "check the oven",
                         "join the meeting", "wake up and drink water", "pay the bill", "message the client"])
        if rng.random() < 0.5:
            c, _ = pick(rng, CLOCKS)
            core = pick(rng, [f"remind me to {msg} at {c}", f"set a reminder at {c} to {msg}", f"at {c} remind me to {msg}",
                              f"add a reminder for {c} to {msg}"])
            return "timer", core, NOTHING, [], {"any": [S("set_reminder", message=HAS(msg.split()[-1]), at_time={"any": True})]}
        n = rng.choice([1, 5, 10, 15, 30, 45])
        core = pick(rng, [f"remind me to {msg} in {n} minutes", f"in {n} minutes remind me to {msg}",
                          f"set a reminder to {msg} in {n} minutes"])
        return "timer", core, NOTHING, [], {"any": [{"tools": ["set_reminder", "set_timer"], "args": {"#minutes": NUM(n)}}]}
    if r < 0.93:
        core = pick(rng, ["what timers do I have", "how much time is left on my timer", "list my reminders", "any reminders set",
                          "you didn't set my timer", "where is my reminder", "the timer didn't go off"])
        return "timer", core, NOTHING, [], {"any": [S("list_timers")]}
    core = pick(rng, ["cancel the timer", "stop the timer", "cancel all reminders", "delete my reminder", "cancel the tea timer"])
    return "timer", core, NOTHING, [], {"any": [S("cancel_timer")]}


def g_notes(rng):
    r = rng.random()
    if r < 0.45:
        n = pick(rng, NOTES)
        core = pick(rng, [f"make a note: {n}", f"note down {n}", f"take a note that I need to {n}", f"write a note: {n}",
                          f"add to my notes: {n}", f"note karo: {n}"])
        return "notes", core, NOTHING, [], {"any": [S("create_note", text=HAS(n.split()[-1].lower()))]}
    if r < 0.6:
        return "notes", pick(rng, ["read my notes", "what are my notes", "show my last notes", "what did I note down"]), NOTHING, [], \
            {"any": [S("read_notes")]}
    if r < 0.75:
        t = pick(rng, ["hello world", "my email address", "the meeting link", "Zhessor"])
        core = pick(rng, [f"copy {t} to my clipboard", f"put {t} on the clipboard"])
        if t in ("my email address", "the meeting link"):  # Zoha doesn't know these → she should ask, not invent or just read
            return "notes", core, NOTHING, [], {"none": True, "allow": []}
        return "notes", core, NOTHING, [], {"any": [S("clipboard", action=IN("write"), text=HAS(t.split()[0].lower()))]}
    if r < 0.82:
        return "notes", pick(rng, ["what's on my clipboard", "read my clipboard", "what did I copy"]), NOTHING, [], \
            {"any": [S("clipboard", action=IN("read"))]}
    t = pick(rng, ["hello how are you", "AI summary call agent", "Dear sir, please find attached", "Thanks for the update"])
    core = pick(rng, [f"type {t}", f"type out {t} here", f"write {t} in this window", f"type this: {t}"])
    return "notes", core, NOTHING, [], {"any": [S("type_text", text=HAS(t.split()[0].lower()))]}


def g_memory(rng):
    if rng.random() < 0.75:
        f, key = pick(rng, FACTS)
        core = pick(rng, [f"remember that {f}", f"remember {f}", f"please remember that {f}", f"don't forget that {f}",
                          f"yaad rakhna {f}"])
        return "memory", core, NOTHING, [], {"any": [S("remember", fact=HAS(key))]}
    f, key = pick(rng, FACTS)
    return "memory", pick(rng, [f"forget what I said about {key}", f"forget that {f}", f"delete the memory about {key}"]), NOTHING, [], \
        {"any": [S("forget")]}


def g_browser(rng):
    ctx = pick(rng, [AMAZON, GITHUB, YT])
    items = [(["go back", "go back to the previous page", "back", "previous page"], S("browser_nav", action=IN("back"))),
             (["go forward", "forward a page"], S("browser_nav", action=IN("forward"))),
             (["reload the page", "refresh", "refresh this page", "page reload karo"], S("browser_nav", action=IN("reload"))),
             (["scroll down", "scroll down a bit", "go down", "scroll to the bottom"], S("browser_scroll", direction=IN("down", "bottom"))),
             (["scroll up", "go to the top", "scroll to the top"], S("browser_scroll", direction=IN("up", "top"))),
             (["open a new tab", "new tab"], S(["browser_tabs", "browser_open"], **{"*": {"any": True}})),
             (["close this tab", "close the tab"], S("browser_tabs", action=IN("close"))),
             (["what tabs are open", "list the tabs"], S("browser_tabs", action=IN("list"))),
             (["close the browser", "close your browser", "shut the browser"], S("browser_close")),
             (["maximise the browser", "make the browser window bigger", "maximize the window"], S("browser_window", state=IN("maximize", "fullscreen"))),
             (["minimise the browser", "hide the browser window"], S("browser_window", state=IN("minimize"))),
             (["what's on this page", "read this page", "summarise this page", "what does this page say"], S(["browser_read", "browser_look"])),
             (["click the first result", "open the first link", "click on the first one"], S(["browser_click", "browser_read"])),
             (["search for wireless mouse on this site", "type laptop bag in the search box and search"], S(["browser_type", "browser_open", "browser_read"]))]
    phr, spec = pick(rng, items)
    specs = [spec]
    if ctx is YT and spec["tools"] == ["browser_nav"] and spec["args"].get("action") == IN("forward"):
        specs.append(S("browser_video", action=IN("forward")))  # on a video "go forward" is fairly read as skip ahead
    if ctx is YT and spec["tools"] == ["browser_nav"] and spec["args"].get("action") == IN("back"):
        specs.append(S("browser_video", action=IN("back")))
    return "browser", pick(rng, phr), ctx, [], {"any": specs}


def g_power(rng):
    act, phr = pick(rng, [("shutdown", ["shut down the PC", "shutdown my computer", "turn off the computer", "switch off the laptop",
                                        "power off", "PC band karo"]),
                          ("restart", ["restart the PC", "reboot my computer", "restart the system"]),
                          ("sleep", ["put the PC to sleep", "sleep the computer", "make the laptop sleep"])])
    return "power", pick(rng, phr), NOTHING, [], {"confirm": act}


def g_nopower(rng):
    core = pick(rng, ["that's all for today, you can sleep", "good night Zoha", "okay bye", "you can rest now", "go to sleep Zoha",
                      "that's it for now", "see you tomorrow", "bye Zoha, I'm going to study"])
    return "standby", core, NOTHING, [], {"nopower": True}


def g_chat(rng):
    if rng.random() < 0.55:
        q = pick(rng, CHAT_Q)
        return "chat", q, NOTHING, [], {"none": True, "allow": ["web_lookup", "get_datetime", "remember", "read_notes"]}
    return "chat", pick(rng, CHAT_SMALL), pick(rng, [NOTHING, SPOTIFY, YT]), [], {"none": True, "allow": ["remember"]}


def g_gap(rng):
    return "honest", pick(rng, GAPS), NOTHING, [], {"honest": True}


def g_compound(rng):
    a_name, a_keys = pick(rng, APPS[:20])
    q = pick(rng, SONGS)
    n = rng.choice([5, 10, 25])
    t = pick(rng, ["hello how are you", "AI summary call agent", "shopping list"])
    items = [
        (f"open {a_name} and play {q}", [S("open_app", name=HAS(*a_keys)), S(["play_youtube", "play_spotify"])]),
        (f"pause the music and set a timer for {n} minutes", [S("media_control", action=IN("pause", "stop", "toggle")), S(["set_timer", "set_reminder"])]),
        (f"open notepad and write {t}", [S("open_app", name=HAS("notepad")), S("type_text", text=HAS(t.split()[0]))]),
        (f"open a new notepad and type {t}", [S("open_app", name=HAS("notepad")), S("type_text", text=HAS(t.split()[0]))]),
        (f"set volume to 40 and play {q}", [S("set_volume", level=NUM(40)), S(["play_youtube", "play_spotify"])]),
        (f"take a screenshot and then lock the PC", [S("take_screenshot"), S("lock_pc")]),
        (f"close Chrome and open VS Code", [S("close_app", name=HAS("chrome")), S("open_app", name=HAS("code", "vs"))]),
        (f"what's the weather in Mumbai and what time is it", [S("get_weather"), S("get_datetime")]),
        (f"make the video full screen and turn off captions", [S("browser_video", action=IN("fullscreen")), S("browser_video", action=IN("captions_off"))]),
    ]
    core, specs = pick(rng, items)
    ctx = YT if "video" in core else NOTHING
    if core.lower().startswith("open spotify and play"):  # playing on Spotify opens it anyway
        return "compound", core, ctx, [], {"any": [S("play_spotify")], "all_alt": specs}
    return "compound", core, ctx, [], {"all": specs}


def g_followup(rng):
    """Vague follow-ups that only make sense with the previous turn."""
    q = pick(rng, SONGS)
    items = [
        ([("play " + q + " on YouTube", f"Playing '{q}' on YouTube in my browser.")], "make it full screen", YT,
         {"any": [S("browser_video", action=IN("fullscreen"))]}),
        ([("play " + q + " on YouTube", f"Playing '{q}' on YouTube in my browser.")], "pause it", YT,
         {"any": [S(["browser_video", "media_control"], action=IN("pause", "stop", "toggle"))]}),
        ([("set a timer for 10 minutes for tea", "Timer set: 'tea' — goes off in 10 minutes.")], "cancel it", NOTHING,
         {"any": [S("cancel_timer")]}),
        ([("set the volume to 30", "Volume set to 30 percent.")], "a bit louder", NOTHING,
         {"any": [S("set_volume", change=IN("up")), S("set_volume", level={"range": [31, 60]})]}),
        ([("open notepad", "Opened Notepad.")], "close it", NOTHING, {"any": [S("close_app", name=HAS("notepad"))]}),
        ([("open a new notepad and write hello", "Opened a new tab: notepad.html")],
         "I said Notepad the app, not a browser tab", NOTHING, {"any": [S("open_app", name=HAS("notepad"))]}),
        ([("what's the weather in Pune", "Pune: 27°C, light rain.")], "and tomorrow?", NOTHING,
         {"any": [S("get_weather", day=IN("tomorrow"))]}),
        ([("what's the weather in Pune", "Pune: 27°C, light rain.")], "what about Mumbai", NOTHING,
         {"any": [S("get_weather", city=HAS("mumbai"))]}),
        ([("play lofi on YouTube", "Playing 'lofi' on YouTube in my browser.")], "next one", YT,
         {"any": [S(["browser_video", "media_control"], action=IN("next", "skip"))]}),
        ([("turn off captions", "Captions are already off.")], "they are still on, check again", YT,
         {"any": [S("browser_video", action=IN("captions_off", "captions", "status")), S(["browser_read", "browser_look"])]}),
        ([("open GitHub", "Opened GitHub in my browser.")], "go back", GITHUB, {"any": [S("browser_nav", action=IN("back"))]}),
        ([("remind me to call mom at 6 pm", "Reminder set: 'call mom' — goes off at 6:00 PM.")], "make it 7 instead", NOTHING,
         {"any": [S(["set_reminder", "cancel_timer"])]}),
    ]
    hist, core, ctx, exp = pick(rng, items)
    return "followup", core, ctx, hist, exp


GENERATORS = [  # (generator, weight)
    (g_media, 7), (g_volume, 6), (g_youtube, 8), (g_spotify, 3), (g_video, 12), (g_apps, 8), (g_sites, 5), (g_search, 3),
    (g_info, 7), (g_pc, 4), (g_files, 3), (g_timer, 7), (g_notes, 5), (g_memory, 3), (g_browser, 6), (g_power, 2),
    (g_nopower, 2), (g_chat, 10), (g_gap, 4), (g_compound, 4), (g_followup, 5),
]


def build(n: int = TARGET, seed: int = SEED):
    rng = random.Random(seed)
    gens, weights = zip(*GENERATORS)
    seen, out = set(), []
    tries = 0
    while len(out) < n and tries < n * 30:
        tries += 1
        cat, core, ctx, hist, exp = rng.choices(gens, weights)[0](rng)
        soft = cat in ("chat", "standby", "honest", "followup")
        dressed = dress(rng, core, lead=cat != "followup" or rng.random() < 0.3, soft=soft)
        key = dressed.lower().strip(" .?!")
        if key in seen:
            continue
        seen.add(key)
        out.append({"id": f"c{len(out) + 1:05d}", "cat": cat, "text": dressed, "ctx": ctx, "hist": hist, "expect": exp,
                    "split": "test" if rng.random() < 0.1 else "train"})
    return out


def write(path: Path, n: int = TARGET):
    path.parent.mkdir(parents=True, exist_ok=True)
    cases = build(n)
    with path.open("w", encoding="utf-8") as f:
        for c in cases:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")
    return cases


if __name__ == "__main__":
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from zoha.config import DATA_DIR

    cs = write(DATA_DIR / "stress" / "cases.jsonl")
    from collections import Counter

    print(f"{len(cs)} cases →", DATA_DIR / "stress" / "cases.jsonl")
    print(dict(Counter(c["cat"] for c in cs)))
