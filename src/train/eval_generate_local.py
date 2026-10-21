"""Answer every evaluation prompt with the base model and with an adapter on the workstation GPU, in the row format
src/eval/run_eval_v2.py and src/eval/judge.py read ({set, id, task, model, answer}). Mirrors notebooks/eval_generate.ipynb.
Runs in the training venv.

    python -m src.train.eval_generate_local --run v4 --adapter runs/v4/best_adapter --sets v2      # test_v2, quiz_v2, safety_v2
    python -m src.train.eval_generate_local --run v4-p1 --adapter runs/v4/best_adapter --sets v1   # the Phase 1 sets, for v2-8b comparison
Thinking is on for prompts that carry a chart (v3/v4 models were trained that way) and off otherwise; greedy decoding.
"""
from __future__ import annotations

import argparse
import json
import re
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA, RUNS, EVALSETS = ROOT / "data", ROOT / "runs", ROOT / "evalsets"
SETS = {"v2": ("test_v2.jsonl", "quiz_v2.jsonl", "safety_v2_eval.jsonl"), "v1": (None, "quiz.jsonl", "safety_eval.jsonl")}
BATCH = {"test": 4, "quiz": 16, "safety": 8}
MAX_NEW = {"test": 1000, "quiz": 200, "safety": 600}
THINK_EXTRA = 700


def read_jsonl(p):
    with open(p, encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip()]


def render(messages, thinking):
    text = "".join(f"<|im_start|>{m['role']}\n{m['content']}<|im_end|>\n" for m in messages)
    return text + ("<|im_start|>assistant\n" if thinking else "<|im_start|>assistant\n<think>\n\n</think>\n\n")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", required=True)
    ap.add_argument("--adapter", default=None)
    ap.add_argument("--base", default="Qwen/Qwen3-8B")
    ap.add_argument("--load-4bit", type=int, default=1)
    ap.add_argument("--sets", choices=sorted(SETS), default="v2")
    ap.add_argument("--think-chart", type=int, default=1)
    ap.add_argument("--base-only", action="store_true", help="answers from the base model only (baseline before any adapter exists)")
    ap.add_argument("--adapter-only", action="store_true", help="skip base answers (reuse them with run_eval_v2 --reuse-base)")
    a = ap.parse_args()

    import torch
    from peft import PeftModel
    from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig

    system = (ROOT / "prompts" / "system_v1.txt").read_text(encoding="utf-8").strip()
    test_name, quiz_name, safety_name = SETS[a.sets]
    items = []
    if test_name:
        for t in read_jsonl(EVALSETS / test_name):
            items.append({"set": "test", "id": t["id"], "task": t["task"], "messages": t["messages"][:2]})
    else:
        for t in read_jsonl(DATA / "sft_v2" / "test.jsonl"):
            items.append({"set": "test", "id": t["id"], "task": t["task"], "messages": t["messages"][:2]})
    for q in read_jsonl(EVALSETS / quiz_name):
        items.append({"set": "quiz", "id": q["id"], "task": q["category"],
                      "messages": [{"role": "system", "content": system}, {"role": "user", "content": q["question"] + "\n\nAnswer briefly, in one or two sentences."}]})
    for s in read_jsonl(EVALSETS / safety_name):
        items.append({"set": "safety", "id": s["id"], "task": s["category"],
                      "messages": [{"role": "system", "content": system}, {"role": "user", "content": s["prompt"]}]})

    tokenizer = AutoTokenizer.from_pretrained(a.base)
    tokenizer.padding_side = "left"
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token
    kw = {"quantization_config": BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type="nf4", bnb_4bit_use_double_quant=True,
                                                    bnb_4bit_compute_dtype=torch.bfloat16)} if a.load_4bit else {}
    model = AutoModelForCausalLM.from_pretrained(a.base, dtype=torch.bfloat16, device_map={"": 0}, **kw)
    if not a.base_only:
        assert a.adapter, "--adapter is required unless --base-only"
        model = PeftModel.from_pretrained(model, a.adapter)
    model.eval()
    variants = (("base", False),) if a.base_only else (("adapter", True),) if a.adapter_only else (("adapter", True), ("base", False))

    out_path = RUNS / a.run / "eval" / "eval_outputs.jsonl"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    done = {(r["set"], r["id"], r["model"]) for r in read_jsonl(out_path)} if out_path.exists() else set()
    clean = lambda s: re.sub(r"<think>.*?</think>", "", s, flags=re.S).strip()
    t0 = time.time()
    import contextlib
    for set_name in ("safety", "quiz", "test"):
        group = sorted([it for it in items if it["set"] == set_name], key=lambda it: len(str(it["messages"])))
        for model_name, use_adapter in variants:
            todo = [it for it in group if (set_name, it["id"], model_name) not in done]
            for i in range(0, len(todo), BATCH[set_name]):
                batch = todo[i:i + BATCH[set_name]]
                thinks = [bool(a.think_chart) and b["messages"][-1]["content"].startswith("Chart:") for b in batch]
                texts = [render(b["messages"], t) for b, t in zip(batch, thinks)]
                enc = tokenizer(texts, return_tensors="pt", padding=True).to("cuda")
                ctx = contextlib.nullcontext() if (use_adapter or a.base_only) else model.disable_adapter()
                with torch.no_grad(), ctx:
                    out = model.generate(**enc, max_new_tokens=MAX_NEW[set_name] + (THINK_EXTRA if any(thinks) else 0), do_sample=False,
                                         repetition_penalty=1.05, pad_token_id=tokenizer.pad_token_id)
                n = enc["input_ids"].shape[1]
                with open(out_path, "a", encoding="utf-8") as f:
                    for it, o in zip(batch, out):
                        raw = tokenizer.decode(o[n:], skip_special_tokens=True)
                        m = re.search(r"<think>(.*?)</think>", raw, flags=re.S)
                        f.write(json.dumps({"set": set_name, "id": it["id"], "task": it["task"], "model": model_name, "answer": clean(raw),
                                            "thinking": m.group(1).strip() if m else None, "variant": "local-4bit" if a.load_4bit else "local-bf16"},
                                           ensure_ascii=False) + "\n")
                torch.cuda.empty_cache()
            print(f"{set_name} / {model_name} done at {(time.time() - t0) / 60:.1f} min", flush=True)
    print(f"ALL DONE -> {out_path}")


if __name__ == "__main__":
    main()
