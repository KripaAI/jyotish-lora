"""Builds notebooks/train_lora.ipynb (edit this file, then run it, rather than editing the notebook JSON by hand)."""
import json
import pathlib

cells = []


def md(s):
    cells.append({"cell_type": "markdown", "metadata": {}, "source": s.strip("\n")})


def code(s):
    cells.append({"cell_type": "code", "metadata": {}, "execution_count": None, "outputs": [], "source": s.strip("\n")})


md("""
# Jyotish LoRA: training (Phases 4-5)

Plain LoRA on **Qwen3-4B-Instruct-2507** (fp16 base, fp32 adapters) on one Kaggle T4. Settings follow Tech Spec 5.5.

**Before running:** Accelerator = **GPU T4 x2**, Internet **on**, and add the private dataset **astro-sft** (Add Input).

1. Run once with `SMOKE_TEST = True` (Qwen3-1.7B, 200 examples, 30 steps, about 10 minutes) to check everything works.
2. Run once with `SMOKE_TEST = False, MEMORY_TEST = True` (the real 4B model on the 16 longest examples, 2 steps, about 10 minutes): it prints the peak GPU memory; under about 13.5 GiB means the full run fits.
3. Then set both to `False` and use **Save Version -> Save & Run All (Commit)** so the full run continues in the background (about 4-6 hours).
3. If a session times out, set `RESUME = True`, add the previous version's output as an input, and run again.
""")

code("""
!pip install -q -U transformers peft trl==1.14.2 datasets accelerate bitsandbytes   # trl pinned: 1.15.0 gave a CUDA illegal memory access in the optimizer step (2026-10-09)
!pip install -q liger-kernel   # fused cross-entropy: avoids the full logits tensor (see USE_LIGER)
# Kaggle ships an old torchao that new PEFT rejects; we do not use it, so remove it
!pip uninstall -y -q torchao
""")

code("""
# Use ONE GPU: with "T4 x2" the trainer would otherwise split work across both GPUs and clash with the model,
# which sits on GPU 0. Must run before torch is imported (restart the session if torch was already loaded).
import os
os.environ["CUDA_VISIBLE_DEVICES"] = "0"
# Reduces memory fragmentation (the first full run lost 1.8 GB to it and ran out of memory)
os.environ["PYTORCH_CUDA_ALLOC_CONF"] = "expandable_segments:True"

# ---------- settings ----------
SMOKE_TEST = True          # True: quick check with Qwen3-1.7B; False: the real 4B model
MEMORY_TEST = False        # True (with SMOKE_TEST = False): 2 steps on the 16 longest examples to check the 4B run fits
RESUME = False             # True: continue from the newest checkpoint found in the inputs or outputs
RUN_NAME = "astro-lora-v1"
FULL_MODEL = "Qwen/Qwen3-4B-Instruct-2507"   # the real run's base model
QLORA = False              # True: load the base in 4-bit (QLoRA), needed for 8B on a T4
MAX_TRAIN_HOURS = 11.0     # stop and save cleanly before Kaggle's 12 h limit; then rerun with RESUME = True
USE_LIGER = False          # True: Liger fused linear cross-entropy (saves the seq x vocab logits tensor, ~2 GB at 3.4k tokens)

BASE_MODEL = "Qwen/Qwen3-1.7B" if SMOKE_TEST else FULL_MODEL
MAX_LENGTH = 3072          # pilot: chart examples are 2,100-2,800 tokens
LORA_R, LORA_ALPHA, LORA_DROPOUT = 32, 64, 0.05
TARGET_MODULES = ["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"]
EPOCHS, LR, SEED = 2, 2e-4, 42   # 2 passes: ~5 h with activation offloading (3 would be ~8 h, near the 12 h limit)
OUT_DIR = "/kaggle/working/" + RUN_NAME + ("-smoke" if SMOKE_TEST else "-memtest" if MEMORY_TEST else "")
""")

code("""
import glob, json, os, time
import torch, transformers, peft, trl, datasets
from datasets import load_dataset
from transformers import AutoModelForCausalLM, AutoTokenizer
from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training
from transformers import BitsAndBytesConfig, TrainerCallback
from trl import SFTConfig, SFTTrainer

VERSIONS = {m.__name__: m.__version__ for m in (torch, transformers, peft, trl, datasets)}
print(VERSIONS)
print("GPU:", torch.cuda.get_device_name(0), round(torch.cuda.get_device_properties(0).total_memory / 2**30, 1), "GiB")

def find(name):
    hits = glob.glob("/kaggle/input/**/" + name, recursive=True)
    assert hits, name + " not found: add the astro-sft dataset as an input"
    return hits[0]

TRAIN, VAL = find("train.jsonl"), find("val.jsonl")
print(TRAIN, VAL)
""")

code("""
# Guard: a model left over from an earlier run in the same session fills the GPU and causes a confusing OOM.
used = torch.cuda.memory_allocated(0) / 2**30
assert used < 1, ("GPU already has %.1f GiB in use from an earlier run. Stop the session (power button), start it again, then Run All." % used)

tokenizer = AutoTokenizer.from_pretrained(BASE_MODEL)
if QLORA:
    bnb = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type="nf4", bnb_4bit_use_double_quant=True,
                             bnb_4bit_compute_dtype=torch.float16)
    model = AutoModelForCausalLM.from_pretrained(BASE_MODEL, quantization_config=bnb, dtype=torch.float16, device_map={"": 0})
    model = prepare_model_for_kbit_training(model, use_gradient_checkpointing=True)
else:
    model = AutoModelForCausalLM.from_pretrained(BASE_MODEL, dtype=torch.float16, device_map={"": 0})
model.config.use_cache = False

lora = LoraConfig(r=LORA_R, lora_alpha=LORA_ALPHA, lora_dropout=LORA_DROPOUT, bias="none",
                  target_modules=TARGET_MODULES, task_type="CAUSAL_LM")
model = get_peft_model(model, lora)   # adapters are kept in fp32 (PEFT autocast_adapter_dtype)
# fp16 training (T4) needs fp32 trainable weights; some models (e.g. Qwen3-8B, stored in bf16) would otherwise give bf16 adapters
for _p in model.parameters():
    if _p.requires_grad:
        _p.data = _p.data.float()
model.print_trainable_parameters()
""")

code("""
# Each example: system + user -> prompt, assistant -> completion. Loss is computed on the completion only.
def to_prompt_completion(ex):
    return {"prompt": ex["messages"][:-1], "completion": [ex["messages"][-1]]}

ds = load_dataset("json", data_files={"train": TRAIN, "val": VAL})
RENDERED_TEXT = "prompt" in ds["train"].column_names   # v3 rows carry the exact training strings (Qwen chat format, thinking on/off)
if RENDERED_TEXT:
    ds = ds.remove_columns([c for c in ds["train"].column_names if c not in ("prompt", "completion")])
    def n_tokens(p, c):
        return len(tokenizer(p + c)["input_ids"])
    print("pre-rendered prompt/completion strings; completions end with:", {c[-10:] for c in ds["train"]["completion"][:200]})
else:
    ds = ds.map(to_prompt_completion, remove_columns=ds["train"].column_names)
    def n_tokens(p, c):
        return len(tokenizer.apply_chat_template(p + c, tokenize=True, return_dict=True)["input_ids"])

lengths = [n_tokens(p, c) for p, c in zip(ds["train"]["prompt"], ds["train"]["completion"])]
if RENDERED_TEXT:
    keep = [i for i, l in enumerate(lengths) if l <= MAX_LENGTH]
    print("dropping", len(lengths) - len(keep), "examples longer than MAX_LENGTH (truncation would cut their answers)")
    ds["train"] = ds["train"].select(keep)
    lengths = [lengths[i] for i in keep]
if SMOKE_TEST:
    ds["train"] = ds["train"].shuffle(seed=SEED).select(range(min(200, len(ds["train"]))))
    ds["val"] = ds["val"].select(range(min(20, len(ds["val"]))))
elif MEMORY_TEST:
    longest = sorted(range(len(lengths)), key=lambda i: -lengths[i])[:16]
    ds["train"] = ds["train"].select(longest)
    ds["val"] = ds["val"].select(range(min(5, len(ds["val"]))))
print(len(ds["train"]), "train /", len(ds["val"]), "val examples; tokens in full train set: max", max(lengths),
      "| median", sorted(lengths)[len(lengths) // 2], "| over MAX_LENGTH:", sum(l > MAX_LENGTH for l in lengths))
""")

code("""
import dataclasses, math

# total optimiser steps -> warmup as an explicit step count (newer versions dropped warmup_ratio)
total_steps = 30 if SMOKE_TEST else 2 if MEMORY_TEST else math.ceil(len(ds["train"]) / 8) * EPOCHS
config = dict(
    output_dir=OUT_DIR,
    max_length=MAX_LENGTH,
    per_device_train_batch_size=1,
    gradient_accumulation_steps=8,
    gradient_checkpointing=True,
    activation_offloading=True,         # park activations in CPU RAM: fits long chart examples on the T4
    num_train_epochs=EPOCHS,
    max_steps=30 if SMOKE_TEST else 2 if MEMORY_TEST else -1,
    learning_rate=LR,
    lr_scheduler_type="cosine",
    warmup_steps=max(1, round(0.03 * total_steps)),
    optim="paged_adamw_8bit" if QLORA else "adamw_torch",   # QLoRA: 8-bit paged optimizer saves memory
    use_liger_kernel=USE_LIGER,
    torch_empty_cache_steps=25,         # curbs fragmentation over a 12 h run at 14.2 GiB reserved (v3 at 3,072 tokens)
    fp16=True, bf16=False,              # T4 has no bf16
    logging_steps=5 if SMOKE_TEST else 10,
    eval_strategy="steps", eval_steps=15 if SMOKE_TEST else 100,
    save_strategy="steps", save_steps=15 if SMOKE_TEST else 50, save_total_limit=2,
    per_device_eval_batch_size=1,
    seed=SEED,
    report_to="none",
)
# Library versions change setting names; keep what this version accepts and say what was skipped.
known = {f.name for f in dataclasses.fields(SFTConfig)}
skipped = sorted(set(config) - known)
if skipped:
    print("NOTE: this TRL/transformers version does not accept, so skipping:", skipped)
args = SFTConfig(**{k: v for k, v in config.items() if k in known})
print("warmup steps:", config["warmup_steps"], "| total steps:", total_steps)
trainer = SFTTrainer(model=model, args=args, train_dataset=ds["train"], eval_dataset=ds["val"],
                     processing_class=tokenizer)
# TRL may cast adapters of a 4-bit model to bf16, which the fp16 grad scaler on a T4 cannot handle: force fp32
from collections import Counter as _C
for _p in trainer.model.parameters():
    if _p.requires_grad and _p.dtype != torch.float32:
        _p.data = _p.data.float()
print("trainable parameter dtypes:", dict(_C(str(_p.dtype) for _p in trainer.model.parameters() if _p.requires_grad)))

# LoRA's B matrices start at zero, so this is the base model's validation loss (Gate 5 compares against it).
base_eval = trainer.evaluate()
print("base model val loss:", round(base_eval["eval_loss"], 4))
""")

code("""
resume = None
if RESUME:
    ckpts = glob.glob("/kaggle/input/**/checkpoint-*", recursive=True) + glob.glob(OUT_DIR + "/checkpoint-*")
    ckpts = sorted(ckpts, key=lambda p: int(p.rsplit("-", 1)[1]))
    resume = ckpts[-1] if ckpts else None
    print("resuming from", resume)

class TimeLimit(TrainerCallback):
    # Save and stop before Kaggle's 12-hour limit; a rerun with RESUME = True continues from the checkpoint.
    stopped = False
    def on_step_end(self, args, state, control, **kwargs):
        if time.time() - t0 > MAX_TRAIN_HOURS * 3600:
            control.should_save = True
            control.should_training_stop = True
            TimeLimit.stopped = True
        return control

trainer.add_callback(TimeLimit())
t0 = time.time()
train_result = trainer.train(resume_from_checkpoint=resume)
if TimeLimit.stopped:
    print("STOPPED FOR TIME at step", train_result.global_step, "- rerun with RESUME = True to continue")
final_eval = trainer.evaluate()
hours = (time.time() - t0) / 3600
print("done in %.2f h | val loss: base %.4f -> adapter %.4f" % (hours, base_eval["eval_loss"], final_eval["eval_loss"]))
peak = torch.cuda.max_memory_reserved() / 2**30
print("peak GPU memory: %.1f GiB (reserved) of %.1f GiB" % (peak, torch.cuda.get_device_properties(0).total_memory / 2**30))
if MEMORY_TEST:
    print("MEMORY TEST:", "FITS - safe to start the full run" if peak < 13.5 else "TOO TIGHT - send this output before the full run")
""")

code("""
adapter_dir = OUT_DIR + "/adapter"
trainer.model.save_pretrained(adapter_dir)
tokenizer.save_pretrained(adapter_dir)

manifest = {
    "run": RUN_NAME, "smoke_test": SMOKE_TEST, "base_model": BASE_MODEL, "qlora": QLORA,
    "stopped_for_time": TimeLimit.stopped,
    "lora": {"r": LORA_R, "alpha": LORA_ALPHA, "dropout": LORA_DROPOUT, "target_modules": TARGET_MODULES},
    "training": {"max_length": MAX_LENGTH, "batch": 1, "grad_accum": 8, "epochs": EPOCHS, "lr": LR,
                 "seed": SEED, "steps": train_result.global_step, "hours": round(hours, 2)},
    "val_loss": {"base": base_eval["eval_loss"], "adapter": final_eval["eval_loss"]},
    "gate5_val_loss_below_base": final_eval["eval_loss"] < base_eval["eval_loss"],
    "peak_gpu_gib": round(torch.cuda.max_memory_allocated() / 2**30, 1),
    "versions": VERSIONS,
    "data": {"train": len(ds["train"]), "val": len(ds["val"])},
}
hit = glob.glob("/kaggle/input/**/manifest.json", recursive=True)
if hit:
    manifest["dataset_manifest"] = json.load(open(hit[0]))
json.dump(manifest, open(OUT_DIR + "/run_manifest.json", "w"), indent=2)
print(json.dumps({k: v for k, v in manifest.items() if k != "dataset_manifest"}, indent=2))
""")

code("""
# Quick look at a few answers from the trained adapter (same system prompt and chart format as training)
trainer.model.eval()
trainer.model.config.use_cache = True
for ex in ds["val"].select(range(3)):
    if RENDERED_TEXT:   # v3: the prompt is already the exact chat-formatted string
        enc = tokenizer(ex["prompt"], return_tensors="pt").to(trainer.model.device)
        user_tail = ex["prompt"][-400:]
    else:
        enc = tokenizer.apply_chat_template(ex["prompt"], add_generation_prompt=True,
                                            return_tensors="pt", return_dict=True).to(trainer.model.device)
        user_tail = ex["prompt"][-1]["content"][-400:]
    with torch.no_grad():
        out = trainer.model.generate(**enc, max_new_tokens=900, do_sample=False)
    print("=" * 100)
    print("USER:", user_tail)
    print("-" * 100)
    print(tokenizer.decode(out[0][enc["input_ids"].shape[1]:], skip_special_tokens=True))
""")

nb = {"cells": cells,
      "metadata": {"kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
                   "language_info": {"name": "python"}},
      "nbformat": 4, "nbformat_minor": 5}
path = pathlib.Path(__file__).with_name("train_lora.ipynb")
path.parent.mkdir(parents=True, exist_ok=True)
path.write_text(json.dumps(nb, indent=1, ensure_ascii=False), encoding="utf-8")
for c in cells:
    if c["cell_type"] == "code":
        src = "\n".join(line for line in c["source"].splitlines() if not line.startswith("!"))
        compile(src, "cell", "exec")
print("wrote", path, len(cells), "cells; all code cells compile")
