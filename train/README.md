# Training Zoha's own model — step by step

Training runs on **Kaggle's free GPU**, not your PC (Unsloth doesn't recommend 4-bit training for
Qwen3.5, and full 16-bit needs ~10 GB – more than the RTX 5060 has). Your PC only does the light steps.

| # | Where | What | Time |
|---|---|---|---|
| 1 | Kaggle | Teacher run finishes → **Output** → download `zoha_teacher_data.jsonl` into the repo's `kaggle\` folder | – |
| 2 | Your PC | `python train\build_dataset.py` | < 1 min, CPU |
| 3 | Kaggle | **Create → New Dataset** named `zoha-sft`, upload `train\out\zoha_sft_train.jsonl` and `zoha_sft_val.jsonl` | 2 min |
| 4 | Kaggle | Import `kaggle\zoha_train.ipynb`, **Add Input** → `zoha-sft`, GPU T4 x2, Internet on. Run with `MODE = "test"` first | ~25 min |
| 5 | Kaggle | If the test run ends with "DONE", set `MODE = "full"` → **Save Version → Save & Run All** | up to ~10 h |
| 6 | Your PC | Download the `zoha_gguf` files from the run's Output, then `python train\install_model.py "<that folder>"` | 5 min |
| 7 | Your PC | Quit Zoha, then `python train\compare.py --new zoha-ft-4b` | ~1–1.5 h GPU |
| 8 | You | If the report says **Switch**: set `LOCAL_LLM_MODEL=zoha-ft-4b` in `.env` and restart Zoha. To undo: set it back to `qwen3.5:4b`. | – |

Notes
- Nothing changes in Zoha until step 8. The old model stays installed, so switching back is one line.
- `build_dataset.py` leaves out anything that's in the stress test (that's the exam) and lists your
  failed real turns in `train\review_failed_turns.jsonl`. Those turns are worth fixing by hand later:
  they're the most valuable training data there is.
- If step 4 or 6 prints an error, send it to Claude before running the full version.
