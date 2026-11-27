"""
Import the fine-tuned Zoha model (GGUF from the Kaggle training run) into Ollama — WITHOUT switching Zoha to it.

    python train\\install_model.py "%USERPROFILE%\\Downloads\\zoha_gguf"
    python train\\install_model.py <folder> --name zoha-ft-4b

What it does
  1. finds the q4_k_m .gguf (and the vision projector "mmproj" .gguf if there is one) in the folder
  2. copies the chat template / renderer settings from your existing qwen3.5:4b, so the new model is
     prompted exactly like the one it was trained from (a wrong template is the #1 cause of bad fine-tunes)
  3. `ollama create <name>`, then checks: can it call tools? can it see images?
Zoha keeps using her current model until you decide to switch (after train\\compare.py).
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

BASE = "qwen3.5:4b"
URL = "http://127.0.0.1:11434"


def sh(*cmd: str) -> str:
    r = subprocess.run(list(cmd), capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode != 0:
        raise SystemExit(f"{' '.join(cmd)} failed:\n{r.stderr or r.stdout}")
    return r.stdout


def post(path: str, body: dict, timeout: float = 300) -> dict:
    req = urllib.request.Request(URL + path, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode() or "{}")
    except urllib.error.HTTPError as e:   # show Ollama's own error message instead of a bare "500"
        raise SystemExit(f"Ollama said ({e.code}): {e.read().decode(errors='replace')[:600]}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("folder", help="folder with the downloaded .gguf file(s)")
    ap.add_argument("--name", default="zoha-ft-4b")
    ap.add_argument("--no-vision", action="store_true", help="install without the vision file (to test if it is the problem)")
    a = ap.parse_args()
    folder = Path(a.folder)
    ggufs = sorted(folder.rglob("*.gguf"))
    proj = [g for g in ggufs if "mmproj" in g.name.lower()]
    if a.no_vision:
        ggufs, proj = [g for g in ggufs if g not in proj], []
    main_ = [g for g in ggufs if g not in proj]
    if not main_:
        sys.exit(f"No .gguf model file in {folder}")
    model_file = next((g for g in main_ if "q4_k_m" in g.name.lower()), main_[0])
    print(f"model:  {model_file.name} ({model_file.stat().st_size / 1e9:.2f} GB)")
    print(f"vision: {proj[0].name if proj else 'no projector file – the new model will be text-only'}")

    base_mf = sh("ollama", "show", BASE, "--modelfile")
    # Parse the base Modelfile command by command. Multi-line values are wrapped in triple quotes;
    # copy TEMPLATE/RENDERER/PARSER/PARAMETER/SYSTEM/… and drop FROM/ADAPTER/LICENSE (licence text broke the old parser).
    KEEP = ("TEMPLATE", "SYSTEM", "RENDERER", "PARSER", "PARAMETER", "MESSAGE", "REQUIRES", "CAPABILITY")
    keep, block, in_block, wanted = [], [], False, False
    for line in base_mf.splitlines():
        if not in_block:
            s = line.strip()
            if not s or s.startswith("#"):
                continue
            word = s.split(None, 1)[0].upper()
            wanted = word in KEEP
            block = [line]
            in_block = line.count('"""') % 2 == 1
        else:
            block.append(line)
            if line.count('"""') % 2 == 1:
                in_block = False
        if not in_block and wanted:
            keep.extend(block)
    mf = [f"FROM {model_file.resolve()}"] + ([f"FROM {proj[0].resolve()}"] if proj else []) + keep
    mf_path = folder / "Modelfile.zoha"
    mf_path.write_text("\n".join(mf) + "\n", encoding="utf-8")
    print(f"Modelfile written ({mf_path}); creating '{a.name}' in Ollama…")
    sh("ollama", "create", a.name, "-f", str(mf_path))

    info = post("/api/show", {"model": a.name})
    caps = info.get("capabilities") or []
    print("capabilities:", caps)

    tools = [{"type": "function", "function": {"name": "open_app", "description": "Open an installed desktop app by name.",
                                               "parameters": {"type": "object", "properties": {"name": {"type": "string"}},
                                                              "required": ["name"]}}}]
    r = post("/api/chat", {"model": a.name, "stream": False, "think": False, "tools": tools,
                           "messages": [{"role": "user", "content": "open notepad"}], "options": {"num_predict": 80}})
    calls = (r.get("message") or {}).get("tool_calls") or []
    print("tool test ('open notepad'):", json.dumps(calls)[:160] if calls else f"NO tool call – said: {(r.get('message') or {}).get('content', '')[:120]!r}")
    if "vision" not in caps:
        print("\nNote: no vision → browser_look (Zoha looking at the page) won't work with this model. Tell Claude.")
    print(f"\n✓ '{a.name}' is installed. Zoha still uses her old model. Next: python train\\compare.py --new {a.name}")


if __name__ == "__main__":
    main()
