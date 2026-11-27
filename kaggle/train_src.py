# %% [markdown]
# # Zoha — fine-tune qwen3.5:4b on Zoha's own data (Zhessor)
#
# LoRA fine-tune of **Qwen3.5-4B** with Unsloth on Kaggle's free GPU, so your PC stays cool.
# Output: a GGUF file you import into Ollama on your PC (`train\install_model.py`).
#
# **How to run**
# 1. Add the dataset: right panel → **Add Input** → your **zoha-sft** dataset
#    (the files from `train\out\`: zoha_sft_train.jsonl, zoha_sft_val.jsonl).
# 2. Session options: Accelerator **GPU T4 x2**, Internet **On**.
# 3. First run with `MODE = "test"` (~25 min) to check everything works end to end.
#    Then set `MODE = "full"` and **Save Version → Save & Run All**.
# 4. When it finishes, open the version → **Output** → download the `zoha_gguf` folder files
#    (and `zoha_lora.zip` as a backup).
#
# It stops by itself before Kaggle's 12-hour limit. Don't cancel a running version – the output would be lost.

# %%
# ── settings ────────────────────────────────────────────────────────────────
MODE = "full"            # "test" = quick end-to-end check (small slice, ~25 min) · "full" = real training
BASE = "unsloth/Qwen3.5-4B"
MAX_SEQ = 6656           # Zoha examples ≤ ~4.3k tokens; web pages up to ~6.5k
LORA_R = 16
LR = 1e-4
EPOCHS = 1
TRAIN_HOURS = 9.0 if MODE == "full" else 0.25   # training stops here; export needs ~1 h more
SEC_PER_STEP = 80        # measured on T4 x2: ~75 s per step of 8 examples → 9 h ≈ 400 steps ≈ 3,200 examples
# One 9-hour run covers about half of the data. To train on the rest later, run this notebook again with the
# previous version's Output added as an Input: it finds zoha_lora.zip + zoha_progress.json and continues from there.
QUANT = "q4_k_m"         # same size class as Ollama's qwen3.5:4b
OUT = "/kaggle/working"

# %%
# ── install ─────────────────────────────────────────────────────────────────
import subprocess, sys, time, os, glob, json
os.environ["PYTORCH_CUDA_ALLOC_CONF"] = "expandable_segments:True"   # less memory lost to fragmentation
T0 = time.time()
if sys.version_info < (3, 11):   # Kaggle's old 2023 image (Python 3.10) can't run current Unsloth – stop in seconds, not 11 minutes
    raise SystemExit(f"Old Kaggle environment (Python {sys.version.split()[0]}). Right panel → Session options → "
                     "Environment → 'Always use latest environment', then Save Version again.")
subprocess.run([sys.executable, "-m", "pip", "install", "-q", "-U", "unsloth", "unsloth_zoo"], check=True)
import torch
print("GPU:", torch.cuda.get_device_name(0), "| bf16:", torch.cuda.is_bf16_supported(), "| torch", torch.__version__)

# %%
# ── data ────────────────────────────────────────────────────────────────────
def find(name):
    hits = glob.glob(f"/kaggle/input/**/{name}", recursive=True)
    if not hits:
        raise SystemExit(f"{name} not found – add your zoha-sft dataset as Input (right panel → Add Input).")
    return hits[0]

def load_jsonl(p):
    with open(p, encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip()]

train_rows = load_jsonl(find("zoha_sft_train.jsonl"))
val_rows = load_jsonl(find("zoha_sft_val.jsonl"))

# continuing an earlier run? (its Output added as Input)
RESUME_ZIP = next(iter(glob.glob("/kaggle/input/**/zoha_lora.zip", recursive=True)), None)
DONE_BEFORE = 0
ROUND2 = next(iter(glob.glob("/kaggle/input/**/zoha_sft_round2.jsonl", recursive=True)), None)
if ROUND2:   # round 2 file = only what wasn't learned yet + web pages → nothing to skip
    train_rows = load_jsonl(ROUND2)
    wv = glob.glob("/kaggle/input/**/zoha_web_val.jsonl", recursive=True)
    val_rows = val_rows + (load_jsonl(wv[0]) if wv else [])
    print(f"round 2: {len(train_rows):,} examples (incl. web pages)")
if RESUME_ZIP:
    import zipfile
    zipfile.ZipFile(RESUME_ZIP).extractall("/kaggle/tmp_resume_lora")
    print("continuing from the earlier LoRA")
if RESUME_ZIP and not ROUND2:
    prog = glob.glob("/kaggle/input/**/zoha_progress.json", recursive=True)
    DONE_BEFORE = json.load(open(prog[0]))["examples_done"] if prog else 0
    print(f"skipping the {DONE_BEFORE:,} examples it already learned")
    train_rows = train_rows[DONE_BEFORE:]

if MODE == "test":
    train_rows, val_rows = train_rows[:400], val_rows[:12]
else:
    val_rows = val_rows[:120]   # each evaluation pass costs GPU time; 120 is plenty to watch for overfitting
print(f"train {len(train_rows):,} · val {len(val_rows):,}")

# %%
# ── model ───────────────────────────────────────────────────────────────────
from unsloth import FastLanguageModel
# A T4 has no bfloat16 and Qwen3.5 can't train in float16, so Unsloth trains in float32.
# That doesn't fit on one 15 GB T4 (first test ran out of memory), so the model is split across BOTH T4s.
# If splitting isn't available, fall back to a 4-bit base (QLoRA) on one GPU.
N_GPU = torch.cuda.device_count()
try:
    model, tokenizer = FastLanguageModel.from_pretrained(
        model_name="/kaggle/tmp_resume_lora" if RESUME_ZIP else BASE, max_seq_length=MAX_SEQ,
        load_in_4bit=False, load_in_16bit=True,
        device_map="unsloth_balanced" if N_GPU > 1 else None,
        full_finetuning=False)
    LOAD = f"16-bit, split over {N_GPU} GPUs"
except Exception as e:
    print("split load failed (", type(e).__name__, str(e)[:200], ") – using 4-bit base instead")
    import gc; gc.collect(); torch.cuda.empty_cache()
    model, tokenizer = FastLanguageModel.from_pretrained(
        model_name=BASE, max_seq_length=MAX_SEQ, load_in_4bit=True, full_finetuning=False)
    LOAD = "4-bit base (QLoRA)"
print("loaded:", LOAD, "|", getattr(model, "hf_device_map", None) and sorted(set(map(str, model.hf_device_map.values()))))
tok = getattr(tokenizer, "tokenizer", tokenizer)   # vision-language checkpoints wrap the text tokenizer
if not RESUME_ZIP:   # a resumed LoRA is already attached (and stays trainable)
  model = FastLanguageModel.get_peft_model(
    model, r=LORA_R, lora_alpha=LORA_R, lora_dropout=0, bias="none",
    target_modules=["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"],
    use_gradient_checkpointing="unsloth", random_state=1611)

# %%
# ── render with Qwen3.5's own chat template (the one Ollama uses too) ───────
from datasets import Dataset

def render(rows):
    out, dropped = [], 0
    for r in rows:
        text = tok.apply_chat_template(r["messages"], tools=r.get("tools") or None, tokenize=False)
        if len(tok(text)["input_ids"]) > MAX_SEQ:
            dropped += 1
            continue
        out.append({"text": text})
    return out, dropped

tr, d1 = render(train_rows)
va, d2 = render(val_rows)
print(f"rendered: train {len(tr):,} (dropped {d1} too long) · val {len(va):,}")
print(tr[0]["text"][-600:])
train_ds, val_ds = Dataset.from_list(tr), Dataset.from_list(va)

# %%
# ── train (only Zoha's replies and tool calls are learned, not the prompt) ────
from trl import SFTTrainer, SFTConfig
from transformers import TrainerCallback
from unsloth.chat_templates import train_on_responses_only


class Guard(TrainerCallback):
    """Stops at the time budget, and stops at once if the loss breaks (NaN) so no GPU time is wasted.
    Also prints the speed, so we know how much of the data the full run can cover."""
    t_first = None

    def on_step_end(self, args, state, control, **kw):
        now = time.time()
        if state.global_step == 1:
            Guard.t_first = now
            print(f"step 1 done ({now - T0:.0f}s since start) | GPU mem:",
                  ", ".join(f"{torch.cuda.max_memory_allocated(i)/2**30:.1f} GB" for i in range(torch.cuda.device_count())))
        elif Guard.t_first and state.global_step % 2 == 0:
            per = (now - Guard.t_first) / (state.global_step - 1)
            fits = int((9.0 * 3600 - (Guard.t_first - T0)) / per) * 8
            print(f"step {state.global_step}: {per:.0f}s/step → a 9-hour full run covers ~{fits:,} examples")
        if time.time() - T0 > TRAIN_HOURS * 3600:
            print(f"⏱ time budget reached at step {state.global_step} – stopping and saving")
            control.should_training_stop = True

    def on_log(self, args, state, control, logs=None, **kw):
        loss = (logs or {}).get("loss")
        if loss is not None and (loss != loss or loss > 50):
            print("✗ loss broke (", loss, ") – stopping. Send the log to Claude.")
            control.should_training_stop = True


bf16 = torch.cuda.is_bf16_supported()
cfg = dict(dataset_text_field="text", max_seq_length=MAX_SEQ, packing=False,
           per_device_train_batch_size=1, gradient_accumulation_steps=8,
           num_train_epochs=EPOCHS, learning_rate=LR, lr_scheduler_type="cosine", warmup_steps=2 if MODE == "test" else 30,
           optim="adamw_8bit", weight_decay=0.01, fp16=not bf16, bf16=bf16,
           logging_steps=1 if MODE == "test" else 5, eval_strategy="steps", eval_steps=8 if MODE == "test" else 200, per_device_eval_batch_size=1,
           max_steps=8 if MODE == "test" else int((TRAIN_HOURS * 3600 - 600) / SEC_PER_STEP),  # cosine LR ends exactly when time does
           save_strategy="no", seed=1611, output_dir=f"{OUT}/checkpoints", report_to="none")
try:
    args = SFTConfig(**cfg)
except TypeError:  # newer TRL renamed it
    cfg["max_length"] = cfg.pop("max_seq_length")
    args = SFTConfig(**cfg)
try:
    trainer = SFTTrainer(model=model, tokenizer=tokenizer, train_dataset=train_ds, eval_dataset=val_ds, args=args, callbacks=[Guard()])
except TypeError:
    trainer = SFTTrainer(model=model, processing_class=tokenizer, train_dataset=train_ds, eval_dataset=val_ds, args=args, callbacks=[Guard()])
trainer = train_on_responses_only(trainer, instruction_part="<|im_start|>user\n", response_part="<|im_start|>assistant\n")
stats = trainer.train()
print(stats)
EXAMPLES_DONE = DONE_BEFORE + trainer.state.global_step * 8
json.dump({"examples_done": EXAMPLES_DONE, "of": DONE_BEFORE + len(train_rows)}, open(f"{OUT}/zoha_progress.json", "w"))
print(f"learned {EXAMPLES_DONE:,} of {DONE_BEFORE + len(train_rows):,} training examples so far")
print("final eval:", trainer.evaluate())

# %%
# ── quick check: does it call tools the Zoha way? ─────────────────────────────
FastLanguageModel.for_inference(model)
probe = [r for r in val_rows if any(m.get("tool_calls") for m in r["messages"])][:3] + \
        [r for r in val_rows if not any(m.get("tool_calls") for m in r["messages"])][:2]
for r in probe:
    msgs = [m for m in r["messages"] if m["role"] in ("system", "user")][:2]
    try:   # Zoha runs with thinking OFF (Ollama think=false) – probe the same way
        prompt = tok.apply_chat_template(msgs, tools=r.get("tools") or None, tokenize=False, add_generation_prompt=True, enable_thinking=False)
    except TypeError:
        prompt = tok.apply_chat_template(msgs, tools=r.get("tools") or None, tokenize=False, add_generation_prompt=True)
    if not prompt.rstrip().endswith("</think>"):
        prompt += "<think>\n\n</think>\n\n"
    ids = tok(prompt, return_tensors="pt").to("cuda")
    out = model.generate(**ids, max_new_tokens=120, do_sample=False)
    said = tok.decode(out[0][ids["input_ids"].shape[1]:], skip_special_tokens=False)
    print("USER:", msgs[-1]["content"].split("</context>")[-1].strip()[:100])
    print("ZOHA :", said.replace("\n", " ")[:220], "\n")

# %%
# ── save: LoRA backup + GGUF for Ollama ─────────────────────────────────────
import shutil
model.save_pretrained(f"{OUT}/zoha_lora")
tokenizer.save_pretrained(f"{OUT}/zoha_lora")
shutil.make_archive(f"{OUT}/zoha_lora", "zip", f"{OUT}/zoha_lora")
shutil.rmtree(f"{OUT}/zoha_lora", ignore_errors=True)
model.save_pretrained_gguf(f"{OUT}/zoha_gguf", tokenizer, quantization_method=QUANT)
# Unsloth writes the .gguf files to zoha_gguf_gguf/ and the merged weights to zoha_gguf/ – keep only the GGUFs
for f in glob.glob(f"{OUT}/zoha_gguf/*"):
    if not f.endswith(".gguf"):
        shutil.rmtree(f, ignore_errors=True) if os.path.isdir(f) else os.remove(f)
for f in glob.glob(f"{OUT}/zoha_gguf_gguf/*.gguf"):
    shutil.move(f, f"{OUT}/zoha_gguf/{os.path.basename(f)}")
shutil.rmtree(f"{OUT}/zoha_gguf_gguf", ignore_errors=True)
for f in sorted(glob.glob(f"{OUT}/zoha_gguf/**/*", recursive=True)):
    if os.path.isfile(f):
        print(f"{os.path.getsize(f) / 1e9:6.2f} GB  {f}")
# keep only what Ollama needs (the big unquantised GGUF just eats Kaggle's 20 GB output limit)
for f in glob.glob(f"{OUT}/zoha_gguf/**/*.gguf", recursive=True):
    if "mmproj" not in f.lower() and QUANT.lower() not in f.lower():
        os.remove(f)
# vision: training only changed the language part, so Qwen3.5-4B's original vision file still fits.
# If the export didn't write one, fetch it – then Zoha keeps "looking at the page" (browser_look).
if not glob.glob(f"{OUT}/zoha_gguf/**/*mmproj*.gguf", recursive=True):
    from huggingface_hub import hf_hub_download
    hf_hub_download("unsloth/Qwen3.5-4B-GGUF", "mmproj-F16.gguf", local_dir=f"{OUT}/zoha_gguf")
    print("added the original vision file: mmproj-F16.gguf")
shutil.rmtree(f"{OUT}/checkpoints", ignore_errors=True)
print(f"DONE in {(time.time() - T0) / 3600:.1f} h – download the zoha_gguf files from Output.")
