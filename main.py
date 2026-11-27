#!/usr/bin/env python3
"""
Zoha — headless / terminal mode.

    python main.py            # voice + type commands in the terminal
    python main.py --text     # keyboard only (no microphone)

Say "Zoha, ..." or just type and press Enter. Ctrl+C to quit.
"""

from __future__ import annotations

import argparse
import sys
import threading
import time

from zoha.config import load_settings
from zoha.logsetup import setup_logging

TEAL, MINT, DIM, CORAL, RESET = "\033[38;2;92;211;195m", "\033[38;2;110;245;238m", "\033[38;2;94;113;108m", "\033[38;2;229;139;123m", "\033[0m"


def main():
    ap = argparse.ArgumentParser(description="Zoha voice assistant (terminal)")
    ap.add_argument("--text", action="store_true", help="keyboard only, no microphone")
    ap.add_argument("--debug", action="store_true")
    args = ap.parse_args()

    import logging

    setup_logging(logging.DEBUG if args.debug else logging.WARNING)
    if sys.platform == "win32":
        import os

        os.system("")  # enable ANSI colours in Windows terminals

    import pathlib
    if not (pathlib.Path(__file__).resolve().parent / ".env").exists():
        print("No .env yet – run  python setup_wizard.py  first to pick Zoha's brain.")
        return
    s = load_settings()
    done = threading.Event()
    replying = {"open": False}

    def emit(ev, **d):
        if ev == "state":
            st = d["state"]
            label = {"STANDBY": f"say “{s.wake_word.title()}”", "LISTENING": "listening…", "THINKING": "thinking…",
                     "SPEAKING": "speaking (Ctrl+C to quit)", "MUTED": "mic off"}.get(st, st.lower())
            print(f"\r{DIM}· {label}{RESET}          ", flush=True)
        elif ev == "user":
            print(f"\n{TEAL}you{RESET}  {d['text']}")
        elif ev == "reply_start":
            replying["open"] = False
        elif ev == "reply_delta":
            if not replying["open"]:
                print(f"{MINT}zoha{RESET}  ", end="")
                replying["open"] = True
            print(d["text"], end="", flush=True)
        elif ev == "reply_end":
            if replying["open"]:
                print()
            replying["open"] = False
        elif ev == "tool_start":
            print(f"{DIM}     {d.get('icon', '⚡')} {d.get('label')} {d.get('args') or ''}{RESET}")
        elif ev == "tool_end":
            res = (d.get("result") or "").splitlines()[0][:120] if d.get("result") else ""
            print(f"{(TEAL if d.get('ok') else CORAL)}       {res}{RESET}")
        elif ev in ("info",):
            print(f"{DIM}{d['text']}{RESET}")
        elif ev == "error":
            print(f"{CORAL}{d['text']}{RESET}")
        elif ev == "ready":
            print(f"\n{MINT}Zoha is ready.{RESET} {DIM}speech: {d['stt']} (wake: {d['wake']}, {d.get('gpu', '')}) | brain: {d['brain']} | voice: {d['voice']}{RESET}")
            print(f"{DIM}Say “{s.wake_word.title()}, …” or type below. 'stop' interrupts, 'exit' quits.{RESET}\n")
        elif ev == "exit":
            done.set()

    from zoha.engine import ZohaEngine

    eng = ZohaEngine(s, emit)
    eng.start()
    eng.ready.wait(600)
    if args.text:
        eng.set_muted(True)

    def reader():
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            if line.lower() in ("stop", "/stop"):
                eng.interrupt()
            elif line.lower() in ("exit", "quit", "/q"):
                done.set()
                return
            else:
                eng.send_text(line)
        done.set()

    threading.Thread(target=reader, daemon=True).start()
    try:
        while not done.is_set():
            time.sleep(0.2)
    except KeyboardInterrupt:
        pass
    eng.shutdown()
    time.sleep(0.5)
    print(f"{DIM}bye{RESET}")


if __name__ == "__main__":
    main()
