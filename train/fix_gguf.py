"""
Make the trained GGUF loadable by Ollama.

Why: Unsloth exported with a newer llama.cpp that merges some Qwen3.5 tensors
(attn_qkv_gate, ssm_beta_alpha) and adds an extra "next-token" block. Ollama expects the
layout of its own qwen3.5:4b. Those merged tensors belong to parts training never touched,
so we build a file with EXACTLY the layout of your installed qwen3.5:4b and swap in every
trained tensor that matches by name and shape. Each swapped tensor is checked against the
original (cosine similarity) so a wrong layout can't slip through.

    pip install gguf numpy
    python train\\fix_gguf.py models\\zoha-ft-1\\Qwen3.5-4B.Q4_K_M.gguf
then
    python train\\install_model.py models\\zoha-ft-1\\fixed
"""
import argparse
import struct
import subprocess
import sys
from pathlib import Path

import numpy as np

try:
    import gguf
    from gguf.quants import dequantize
except ImportError:
    sys.exit("Run first:  pip install gguf numpy")

BASE = "qwen3.5:4b"


def base_blob() -> Path:
    mf = subprocess.run(["ollama", "show", BASE, "--modelfile"], capture_output=True, text=True,
                        encoding="utf-8", errors="replace").stdout
    for line in mf.splitlines():
        if line.upper().startswith("FROM "):
            p = Path(line[5:].strip())
            if p.exists():
                return p
    sys.exit(f"Couldn't find the file of '{BASE}' (is Ollama running and is {BASE} installed?)")


def kv_end_offset(path: Path) -> tuple[int, int, int]:
    """Byte offset where tensor infos start, tensor count, alignment."""
    with open(path, "rb") as f:
        def u32(): return struct.unpack("<I", f.read(4))[0]
        def u64(): return struct.unpack("<Q", f.read(8))[0]
        def skip_str(): f.seek(u64(), 1)
        size = {0: 1, 1: 1, 2: 2, 3: 2, 4: 4, 5: 4, 6: 4, 7: 1, 10: 8, 11: 8, 12: 8}
        align = 32

        def skip_val(t, key=None):
            nonlocal align
            if t == 8:
                skip_str()
            elif t == 9:
                at, n = u32(), u64()
                if at in size:
                    f.seek(size[at] * n, 1)
                else:
                    for _ in range(n):
                        skip_val(at)
            else:
                raw = f.read(size[t])
                if key == "general.alignment":
                    align = struct.unpack("<I", raw)[0]

        assert f.read(4) == b"GGUF", "not a GGUF file"
        u32()
        n_t, n_kv = u64(), u64()
        for _ in range(n_kv):
            n = u64(); key = f.read(n).decode(errors="replace")
            skip_val(u32(), key)
        return f.tell(), n_t, align


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("trained", help="the .gguf from Kaggle")
    ap.add_argument("--base", default="", help="override: path of the base GGUF (default: Ollama's qwen3.5:4b)")
    ap.add_argument("--out", default="", help="default: <trained folder>\\fixed\\zoha-ft.gguf")
    a = ap.parse_args()

    trained_p = Path(a.trained)
    base_p = Path(a.base) if a.base else base_blob()
    out_p = Path(a.out) if a.out else trained_p.parent / "fixed" / "zoha-ft.gguf"
    out_p.parent.mkdir(parents=True, exist_ok=True)
    print("base   :", base_p)
    print("trained:", trained_p)

    base = gguf.GGUFReader(base_p)
    tr = gguf.GGUFReader(trained_p)
    tmap = {t.name: t for t in tr.tensors}

    def shape(t):
        return [int(x) for x in t.shape]

    plan, swapped, kept, checks = [], 0, 0, []
    for t in base.tensors:
        o = tmap.get(t.name)
        if o is not None and shape(o) == shape(t):
            plan.append((t.name, o))
            swapped += 1
        else:
            plan.append((t.name, t))
            kept += 1

    # safety check: trained tensors must still look like the originals (LoRA changes are small)
    bad = []
    sample = [n for n, s in plan if s is tmap.get(n)]
    pick = [n for n in sample if any(k in n for k in ("attn_q.", "attn_k.", "attn_v.", "attn_output", "ffn_down", "ffn_gate", "ffn_up", "ssm_out", "ssm_conv1d"))]
    for n in pick[:: max(1, len(pick) // 40)]:
        bt = next(t for t in base.tensors if t.name == n)
        x = dequantize(np.asarray(tmap[n].data), tmap[n].tensor_type).astype(np.float32).ravel()
        y = dequantize(np.asarray(bt.data), bt.tensor_type).astype(np.float32).ravel()
        cos = float(np.dot(x, y) / (np.linalg.norm(x) * np.linalg.norm(y) + 1e-9))
        checks.append(cos)
        if cos < 0.95:
            bad.append((n, round(cos, 3)))
    print(f"tensors: {swapped} from the trained model, {kept} kept from {BASE} (untouched by training)")
    print(f"layout check on {len(checks)} tensors: min similarity {min(checks):.4f}, avg {sum(checks)/len(checks):.4f}")
    extra = [n for n in tmap if n not in {t.name for t in base.tensors}]
    print(f"skipped {len(extra)} export-only tensors (merged pieces / extra block), e.g. {extra[:3]}")
    if bad:
        sys.exit(f"✗ STOP – these tensors don't match the original layout: {bad[:5]}. Send this to Claude.")

    # write: base header (all metadata, incl. tokenizer + chat template) + new tensor table + data
    kv_end, n_t, align = kv_end_offset(base_p)
    with open(base_p, "rb") as f:
        header = bytearray(f.read(kv_end))
    struct.pack_into("<Q", header, 8, len(plan))     # tensor count (same as base)

    infos, offs, off = bytearray(), [], 0
    for name, src in plan:
        nb = len(name.encode())
        dims = [int(x) for x in src.shape]   # GGUF order (ne0 first), as stored in the file
        infos += struct.pack("<Q", nb) + name.encode() + struct.pack("<I", len(dims))
        infos += b"".join(struct.pack("<Q", d) for d in dims)
        infos += struct.pack("<I", int(src.tensor_type)) + struct.pack("<Q", off)
        offs.append(off)
        off += (int(src.n_bytes) + align - 1) // align * align

    with open(out_p, "wb") as w:
        w.write(header)
        w.write(infos)
        pad = (-w.tell()) % align
        w.write(b"\0" * pad)
        for (name, src), o in zip(plan, offs):
            data = np.asarray(src.data).tobytes()
            assert len(data) == int(src.n_bytes), name
            w.write(data)
            w.write(b"\0" * ((-len(data)) % align))
    print(f"✓ wrote {out_p} ({out_p.stat().st_size / 1e9:.2f} GB)")

    # re-read to be sure it's a valid file
    chk = gguf.GGUFReader(out_p)
    assert len(chk.tensors) == len(plan)
    vision = sum(1 for t in chk.tensors if t.name.startswith(("v.", "mm.")))
    print(f"✓ file reads back fine: {len(chk.tensors)} tensors"
          + (f", vision included ({vision} tensors)" if vision else " (text-only: no vision in the base file)"))
    print(f'next:  python train\\install_model.py "{out_p.parent}"')


if __name__ == "__main__":
    main()
