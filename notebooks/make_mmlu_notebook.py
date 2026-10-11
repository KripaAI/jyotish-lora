"""Builds notebooks/mmlu_forgetting.ipynb: a catastrophic-forgetting check for a LoRA/QLoRA adapter.

The same MMLU questions are answered by the base model (adapter switched off) and the fine-tuned model (adapter on), with
no astrology system prompt, thinking off and identical prompts. The answer is scored by code: the next-token logit of each
option letter after the assistant prefix (letters with and without a leading space are both considered), no judge.
Output: /kaggle/working/mmlu_results.jsonl (one row per question, both predictions) and mmlu_summary.json.

Inputs on Kaggle: a dataset holding the adapter (adapter_config.json + weights); internet on (MMLU from the HF hub).
Edit this file, then run it, rather than editing the notebook JSON by hand.
"""
import json
import pathlib

cells = []


def md(s):
    cells.append({"cell_type": "markdown", "metadata": {}, "source": s.strip("\n")})


def code(s):
    cells.append({"cell_type": "code", "metadata": {}, "execution_count": None, "outputs": [], "source": s.strip("\n")})


md("# Jyotish LoRA: catastrophic-forgetting check on MMLU\n\nBase model vs fine-tuned adapter on the same MMLU questions, scored by option-letter logits.")

code("""
import os
os.environ["CUDA_VISIBLE_DEVICES"] = "0"
os.environ["PYTORCH_CUDA_ALLOC_CONF"] = "expandable_segments:True"
""")

code("""
!pip install -q -U transformers peft accelerate bitsandbytes datasets
!pip uninstall -y -q torchao
""")

code("""
import glob, json, math, random, time
from collections import Counter, defaultdict
import torch
from datasets import load_dataset
from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig
from peft import PeftModel

# ---------- settings ----------
BASE_MODEL = "Qwen/Qwen3-8B"
QLORA = True                 # load the base in 4-bit (as the adapter was trained)
ADAPTER_HINT = ""            # substring of the adapter path when several inputs carry adapters
N_QUESTIONS = 1000
SEED = 0
BATCH = 8
OUT = "/kaggle/working/mmlu_results.jsonl"

adapters = sorted(glob.glob("/kaggle/input/**/adapter_config.json", recursive=True))
adapters = [a for a in adapters if ADAPTER_HINT in a] or adapters
final = [a for a in adapters if "/adapter/" in a] or adapters
ADAPTER = os.path.dirname(final[-1])
print("adapter:", ADAPTER)

mmlu = load_dataset("cais/mmlu", "all", split="test")
idx = sorted(random.Random(SEED).sample(range(len(mmlu)), N_QUESTIONS))
items = [dict(mmlu[i], row=i) for i in idx]
print(len(mmlu), "MMLU test questions;", len(items), "sampled with seed", SEED, "| subjects:", len({it["subject"] for it in items}))
""")

code("""
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

LETTERS = "ABCD"
def single(s):
    ids = tokenizer.encode(s, add_special_tokens=False)
    assert len(ids) == 1, (s, ids)
    return ids[0]
LETTER_IDS = [(single(L), single(" " + L)) for L in LETTERS]
print("letter token ids:", LETTER_IDS)

def prompt(it):
    opts = "\\n".join(f"{L}. {c}" for L, c in zip(LETTERS, it["choices"]))
    user = (f"The following is a multiple-choice question about {it['subject'].replace('_', ' ')}.\\n\\n{it['question']}\\n\\n{opts}\\n\\n"
            "Answer with the letter of the correct option only.")
    return tokenizer.apply_chat_template([{"role": "user", "content": user}], tokenize=False, add_generation_prompt=True,
                                         enable_thinking=False)

print(prompt(items[0])[-400:])
""")

code("""
@torch.no_grad()
def score(batch, use_adapter):
    enc = tokenizer([prompt(it) for it in batch], return_tensors="pt", padding=True).to("cuda")
    ctx = model.disable_adapter() if not use_adapter else torch.no_grad()
    with ctx:
        logits = model(**enc).logits[:, -1, :].float()
    out = []
    for row in logits:
        s = [max(row[a].item(), row[b].item()) for a, b in LETTER_IDS]
        out.append((LETTERS[max(range(4), key=lambda k: s[k])], [round(v, 3) for v in s]))
    return out

rows = {it["row"]: {"row": it["row"], "subject": it["subject"], "answer": LETTERS[it["answer"]]} for it in items}
t0 = time.time()
for mode, use in (("base", False), ("adapter", True)):
    for i in range(0, len(items), BATCH):
        batch = items[i:i + BATCH]
        for it, (pred, s) in zip(batch, score(batch, use)):
            rows[it["row"]][f"pred_{mode}"] = pred
            rows[it["row"]][f"scores_{mode}"] = s
        torch.cuda.empty_cache()
    print(mode, "done at %.1f min" % ((time.time() - t0) / 60), flush=True)
with open(OUT, "w", encoding="utf-8") as f:
    for r in rows.values():
        f.write(json.dumps(r) + "\\n")
""")

code("""
R = list(rows.values())
n = len(R)
acc = {m: sum(r[f"pred_{m}"] == r["answer"] for r in R) / n for m in ("base", "adapter")}
b = sum(r["pred_base"] == r["answer"] and r["pred_adapter"] != r["answer"] for r in R)   # right -> wrong
c = sum(r["pred_base"] != r["answer"] and r["pred_adapter"] == r["answer"] for r in R)   # wrong -> right
# exact two-sided McNemar test on the discordant pairs
k, m = min(b, c), b + c
p = min(1.0, 2 * sum(math.comb(m, j) for j in range(k + 1)) / 2 ** m) if m else 1.0
summary = {"n": n, "seed": SEED, "base_model": BASE_MODEL, "adapter": ADAPTER, "qlora": QLORA,
           "acc_base": round(acc["base"], 4), "acc_adapter": round(acc["adapter"], 4),
           "change_pp": round(100 * (acc["adapter"] - acc["base"]), 2),
           "right_to_wrong": b, "wrong_to_right": c, "mcnemar_p": round(p, 4),
           "same_prediction": sum(r["pred_base"] == r["pred_adapter"] for r in R)}
by = defaultdict(lambda: [0, 0, 0])
for r in R:
    s = by[r["subject"]]; s[0] += 1; s[1] += r["pred_base"] == r["answer"]; s[2] += r["pred_adapter"] == r["answer"]
summary["largest_subject_changes"] = sorted(([k, v[0], v[1], v[2]] for k, v in by.items() if v[0] >= 10),
                                            key=lambda x: (x[3] - x[2]) / x[1])[:8]
summary["answer_letter_counts"] = {m: dict(Counter(r[f"pred_{m}"] for r in R)) for m in ("base", "adapter")}
json.dump(summary, open("/kaggle/working/mmlu_summary.json", "w"), indent=2)
print(json.dumps(summary, indent=2))
""")

nb = {"cells": cells, "metadata": {"kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
                                   "language_info": {"name": "python"}}, "nbformat": 4, "nbformat_minor": 5}
for c in cells:
    if c["cell_type"] == "code":
        compile("\n".join(l for l in c["source"].splitlines() if not l.startswith("!")), "cell", "exec")
path = pathlib.Path(__file__).with_name("mmlu_forgetting.ipynb")
path.write_text(json.dumps(nb, indent=1, ensure_ascii=False), encoding="utf-8")
print("wrote", path, "- all code cells compile")
