"""Builds the two DPO notebooks (edit this file, then run it, rather than editing the notebook JSON by hand):

  notebooks/dpo_sample.ipynb  samples several answers per prompt from the SFT adapter (on-policy rejected/chosen candidates)
  notebooks/dpo_train.ipynb   DPO on the preference pairs, on top of the SFT adapter

Inputs on Kaggle: dataset astro-dpo (prompts.jsonl for sampling, pairs.jsonl for training) and the SFT adapter dataset.
DPO needs a reference model that is the SFT model. With one adapter that is awkward, so the SFT adapter is merged into
the fp16 base and a fresh LoRA is trained on top; the reference is then "adapter off" = the merged SFT model.
"""
import json
import pathlib

HERE = pathlib.Path(__file__).parent


def build(name: str, cells: list, title: str) -> None:
    for c in cells:
        if c["cell_type"] == "code":
            compile("\n".join(l for l in c["source"].splitlines() if not l.startswith("!")), "cell", "exec")
    nb = {"cells": cells, "metadata": {"kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
                                       "language_info": {"name": "python"}}, "nbformat": 4, "nbformat_minor": 5}
    (HERE / name).write_text(json.dumps(nb, indent=1, ensure_ascii=False), encoding="utf-8")
    print("wrote", name, title)


def cell(kind, s):
    base = {"cell_type": kind, "metadata": {}, "source": s.strip("\n")}
    return base if kind == "markdown" else {**base, "execution_count": None, "outputs": []}


# ---------------------------------------------------------------- sampling
S = []
S.append(cell("markdown", "# Jyotish LoRA: DPO step 2, sample the model's own answers\n\nSamples several answers per prompt from the SFT model (adapter on, temperature sampling). Scoring happens on the laptop."))
S.append(cell("code", """
import os
os.environ["CUDA_VISIBLE_DEVICES"] = "0"
os.environ["PYTORCH_CUDA_ALLOC_CONF"] = "expandable_segments:True"
"""))
S.append(cell("code", """
!pip install -q -U transformers peft accelerate bitsandbytes
!pip uninstall -y -q torchao
"""))
S.append(cell("code", """
import contextlib, glob, json, re, time
import torch
from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig
from peft import PeftModel

# ---------- settings ----------
BASE_MODEL = "Qwen/Qwen3-4B-Instruct-2507"
QLORA = False
ADAPTER_HINT = ""             # substring of the adapter path to pick when several inputs carry adapters
N_SAMPLES = 3
GREEDY = False               # True: one greedy answer per prompt (as the evaluation does) and N_SAMPLES is ignored
TEMPERATURE, TOP_P = 0.8, 0.95
BATCH = 6                     # prompts per generate call (x N_SAMPLES sequences)
MAX_NEW = 600
LIMIT = 0                     # >0: only the first LIMIT prompts (smoke test)
OUT = "/kaggle/working/samples.jsonl"

def find(name):
    hits = glob.glob("/kaggle/input/**/" + name, recursive=True)
    assert hits, name + " not found"
    return hits[0]

adapters = sorted(glob.glob("/kaggle/input/**/adapter_config.json", recursive=True))
adapters = [a for a in adapters if ADAPTER_HINT in a] or adapters
ADAPTER = os.path.dirname(adapters[-1])
prompts = [json.loads(l) for l in open(find("prompts.jsonl"), encoding="utf-8") if l.strip()]
if LIMIT:
    prompts = prompts[:LIMIT]
print("adapter:", ADAPTER, "| prompts:", len(prompts))
"""))
S.append(cell("code", """
tokenizer = AutoTokenizer.from_pretrained(BASE_MODEL)
tokenizer.padding_side = "left"
if tokenizer.pad_token is None:
    tokenizer.pad_token = tokenizer.eos_token
if QLORA:
    bnb = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type="nf4", bnb_4bit_use_double_quant=True,
                             bnb_4bit_compute_dtype=torch.float16)
    model = AutoModelForCausalLM.from_pretrained(BASE_MODEL, quantization_config=bnb, dtype=torch.float16, device_map={"": 0})
else:
    model = AutoModelForCausalLM.from_pretrained(BASE_MODEL, dtype=torch.float16, device_map={"": 0})
model = PeftModel.from_pretrained(model, ADAPTER)
model.eval()
"""))
S.append(cell("code", """
done = set()
if os.path.exists(OUT):
    done = {r["id"] for r in map(json.loads, open(OUT, encoding="utf-8"))}
todo = sorted([p for p in prompts if p["id"] not in done], key=lambda p: len(str(p["messages"])))
clean = lambda s: re.sub(r"<think>.*?</think>", "", s, flags=re.S).strip()
t0 = time.time()
torch.manual_seed(0)
for i in range(0, len(todo), BATCH):
    batch = todo[i:i + BATCH]
    texts = [tokenizer.apply_chat_template(b["messages"], tokenize=False, add_generation_prompt=True,
                                           enable_thinking=False) for b in batch]
    enc = tokenizer(texts, return_tensors="pt", padding=True).to("cuda")
    n_ret = 1 if GREEDY else N_SAMPLES
    with torch.no_grad():
        out = model.generate(**enc, max_new_tokens=MAX_NEW, repetition_penalty=1.05, pad_token_id=tokenizer.pad_token_id,
                             num_return_sequences=n_ret,
                             **({"do_sample": False} if GREEDY else {"do_sample": True, "temperature": TEMPERATURE, "top_p": TOP_P}))
    n = enc["input_ids"].shape[1]
    with open(OUT, "a", encoding="utf-8") as f:
        for j, b in enumerate(batch):
            answers = [clean(tokenizer.decode(o[n:], skip_special_tokens=True)) for o in out[j * n_ret:(j + 1) * n_ret]]
            f.write(json.dumps({"id": b["id"], "answers": answers}, ensure_ascii=False) + "\\n")
    torch.cuda.empty_cache()
    if (i // BATCH) % 10 == 0:
        print("%d/%d prompts, %.1f min" % (min(i + BATCH, len(todo)), len(todo), (time.time() - t0) / 60), flush=True)
print("ALL DONE in %.2f h" % ((time.time() - t0) / 3600))
"""))
build("dpo_sample.ipynb", S, "(sampling)")

# ---------------------------------------------------------------- DPO training
T = []
T.append(cell("markdown", "# Jyotish LoRA: DPO training\n\nMerges the SFT adapter into the fp16 base (that merged model is the reference), then trains a fresh LoRA with DPO on the preference pairs."))
T.append(cell("code", """
!pip install -q -U transformers peft trl datasets accelerate bitsandbytes
!pip uninstall -y -q torchao
"""))
T.append(cell("code", """
import os
os.environ["CUDA_VISIBLE_DEVICES"] = "0"
os.environ["PYTORCH_CUDA_ALLOC_CONF"] = "expandable_segments:True"

# ---------- settings ----------
SMOKE_TEST = True          # True: 6 steps on a handful of pairs, to check that it runs and fits
RUN_NAME = "astro-dpo-v2-4b"
BASE_MODEL = "Qwen/Qwen3-4B-Instruct-2507"
SFT_HINT = ""              # substring of the SFT adapter path to pick when several inputs carry adapters
MAX_LENGTH = 2048          # pairs longer than this (prompt + answer) are dropped
LORA_R, LORA_ALPHA, LORA_DROPOUT = 16, 32, 0.05
TARGET_MODULES = ["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"]
BETA, LR, EPOCHS, SEED = 0.1, 2e-5, 2, 42
OUT_DIR = "/kaggle/working/" + RUN_NAME + ("-smoke" if SMOKE_TEST else "")
"""))
T.append(cell("code", """
import dataclasses, glob, json, math, time
import torch, transformers, peft, trl, datasets
from datasets import load_dataset
from transformers import AutoModelForCausalLM, AutoTokenizer
from peft import LoraConfig, PeftModel, get_peft_model
from trl import DPOConfig, DPOTrainer

VERSIONS = {m.__name__: m.__version__ for m in (torch, transformers, peft, trl, datasets)}
print(VERSIONS)

def find(name):
    hits = glob.glob("/kaggle/input/**/" + name, recursive=True)
    assert hits, name + " not found"
    return hits[0]

adapters = sorted(glob.glob("/kaggle/input/**/adapter_config.json", recursive=True))
adapters = [a for a in adapters if SFT_HINT in a] or adapters
SFT_ADAPTER = os.path.dirname(adapters[-1])
print("SFT adapter:", SFT_ADAPTER)
"""))
T.append(cell("code", """
used = torch.cuda.memory_allocated(0) / 2**30
assert used < 1, "GPU already in use: stop the session and run again"
tokenizer = AutoTokenizer.from_pretrained(BASE_MODEL)
model = AutoModelForCausalLM.from_pretrained(BASE_MODEL, dtype=torch.float16, device_map={"": 0})
model = PeftModel.from_pretrained(model, SFT_ADAPTER).merge_and_unload()   # reference = this merged SFT model
model.config.use_cache = False
lora = LoraConfig(r=LORA_R, lora_alpha=LORA_ALPHA, lora_dropout=LORA_DROPOUT, bias="none",
                  target_modules=TARGET_MODULES, task_type="CAUSAL_LM")
model = get_peft_model(model, lora)
for _p in model.parameters():
    if _p.requires_grad:
        _p.data = _p.data.float()
model.print_trainable_parameters()
"""))
T.append(cell("code", """
ds = load_dataset("json", data_files={"train": find("pairs.jsonl")})["train"]
ds = ds.map(lambda ex: {"prompt": ex["prompt"], "chosen": [{"role": "assistant", "content": ex["chosen"]}],
                        "rejected": [{"role": "assistant", "content": ex["rejected"]}]},
            remove_columns=ds.column_names)
def too_long(ex):
    n = max(len(tokenizer.apply_chat_template(ex["prompt"] + ex[k], tokenize=True, return_dict=True)["input_ids"])
            for k in ("chosen", "rejected"))
    return n > MAX_LENGTH
keep = [i for i, ex in enumerate(ds) if not too_long(ex)]
print(len(ds), "pairs;", len(ds) - len(keep), "dropped as longer than", MAX_LENGTH)
ds = ds.select(keep)
if SMOKE_TEST:
    ds = ds.select(range(min(48, len(ds))))
"""))
T.append(cell("code", """
total_steps = 6 if SMOKE_TEST else math.ceil(len(ds) / 8) * EPOCHS
config = dict(
    output_dir=OUT_DIR, beta=BETA, max_length=MAX_LENGTH, per_device_train_batch_size=1, gradient_accumulation_steps=8,
    gradient_checkpointing=True, num_train_epochs=EPOCHS, max_steps=6 if SMOKE_TEST else -1, learning_rate=LR,
    lr_scheduler_type="cosine", warmup_steps=max(1, round(0.1 * total_steps)), fp16=True, bf16=False,
    logging_steps=2 if SMOKE_TEST else 5, save_strategy="no", seed=SEED, report_to="none",
    loss_type="sigmoid", precompute_ref_log_probs=False,
)
known = {f.name for f in dataclasses.fields(DPOConfig)}
print("NOTE: skipping settings this version does not accept:", sorted(set(config) - known))
args = DPOConfig(**{k: v for k, v in config.items() if k in known})
trainer = DPOTrainer(model=model, args=args, train_dataset=ds, processing_class=tokenizer)
from collections import Counter as _C
for _p in trainer.model.parameters():
    if _p.requires_grad and _p.dtype != torch.float32:
        _p.data = _p.data.float()
print("trainable dtypes:", dict(_C(str(_p.dtype) for _p in trainer.model.parameters() if _p.requires_grad)))
"""))
T.append(cell("code", """
t0 = time.time()
result = trainer.train()
hours = (time.time() - t0) / 3600
peak = torch.cuda.max_memory_reserved() / 2**30
print("done in %.2f h | peak GPU %.1f GiB of %.1f" % (hours, peak, torch.cuda.get_device_properties(0).total_memory / 2**30))
log = [h for h in trainer.state.log_history]
print([ {k: round(v, 4) for k, v in h.items() if k in ("loss", "rewards/accuracies", "rewards/margins")} for h in log if "loss" in h][-6:])
adapter_dir = OUT_DIR + "/adapter"
trainer.model.save_pretrained(adapter_dir)
tokenizer.save_pretrained(adapter_dir)
json.dump({"run": RUN_NAME, "smoke_test": SMOKE_TEST, "base_model": BASE_MODEL, "sft_adapter": SFT_ADAPTER,
           "dpo": {"beta": BETA, "lr": LR, "epochs": EPOCHS, "max_length": MAX_LENGTH, "pairs": len(ds),
                   "steps": result.global_step, "hours": round(hours, 2)},
           "lora": {"r": LORA_R, "alpha": LORA_ALPHA}, "peak_gpu_gib": round(peak, 1), "versions": VERSIONS,
           "log_history": log}, open(OUT_DIR + "/run_manifest.json", "w"), indent=2, default=str)
"""))
build("dpo_train.ipynb", T, "(training)")
