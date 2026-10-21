"""Stage 2C: train a v4 adapter on the workstation GPU (RTX 5070 Ti, 16 GB) with Unsloth.

Runs in the training venv (C:\\Users\\mobirizer\\.venvs\\train: torch cu128, unsloth, triton-windows), not the project venv.
Data: data/sft_v4/train.jsonl rows with exact "prompt" / "completion" strings (Qwen3 chat format, thinking on for chart rows),
loss on the completion only. Settings follow the implementation plan (stage 2C.4): r=32, alpha=64, rsLoRA, dropout 0,
weight decay 0.01, all seven projections, 2 epochs, effective batch 8, max length 4,096, bf16 (Blackwell supports it).
A callback greedy-decodes the 100-item Phase 1 quiz every QUIZ_EVERY steps and keeps the checkpoint with the best accuracy,
so the model is chosen on the metric that matters rather than validation loss.

    python -m src.train.train_local --run v4-smoke --smoke                       # 30 steps on 200 rows
    python -m src.train.train_local --run v4-lr5e-4 --lr 5e-4 --max-steps 300    # sweep point
    python -m src.train.train_local --run v4 --lr 5e-4                            # full run (2 epochs)
Outputs: runs/<run>/adapter/ (final), runs/<run>/best_adapter/ (best quiz), runs/<run>/run_manifest.json, runs/<run>/train.log
"""
from __future__ import annotations

import argparse
import json
import math
import re
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA, RUNS, EVALSETS = ROOT / "data", ROOT / "runs", ROOT / "evalsets"
TARGETS = ["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"]


def read_jsonl(p):
    with open(p, encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip()]


def quiz_correct(item: dict, answer: str) -> bool:
    a = " " + re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]+", " ", answer.lower())) + " "
    return any((" " + re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]+", " ", x.lower())).strip() + " ") in a for x in item["answers"])


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", required=True)
    ap.add_argument("--base", default="Qwen/Qwen3-8B")
    ap.add_argument("--load-4bit", type=int, default=1, help="1 for 8B-class bases on 16 GB; 0 for 4B-class in bf16")
    ap.add_argument("--r", type=int, default=32)
    ap.add_argument("--alpha", type=int, default=64)
    ap.add_argument("--lr", type=float, default=5e-4)
    ap.add_argument("--epochs", type=float, default=2.0)
    ap.add_argument("--max-steps", type=int, default=-1)
    ap.add_argument("--max-len", type=int, default=4096)
    ap.add_argument("--batch", type=int, default=2)
    ap.add_argument("--grad-accum", type=int, default=4)
    ap.add_argument("--quiz-every", type=int, default=200)
    ap.add_argument("--smoke", action="store_true")
    ap.add_argument("--resume", action="store_true", help="continue from the newest checkpoint in runs/<run>/ckpt (after a crash)")
    ap.add_argument("--resume-mode", choices=["full", "weights"], default="full",
                    help="full: restore optimizer state too (diverged once under Unsloth 4-bit, 2026-10-20); "
                         "weights: restore adapter, scheduler and data position, fresh optimizer state")
    ap.add_argument("--save-steps", type=int, default=150, help="checkpoint interval; at ~2.7 s/step, 150 steps is about 7 minutes")
    ap.add_argument("--keep-ckpts", type=int, default=3, help="checkpoints kept on disk (oldest deleted first; the best by eval loss is always kept)")
    ap.add_argument("--diverge-ratio", type=float, default=1.3, help="stop if eval loss exceeds this multiple of the best eval loss")
    ap.add_argument("--max-grad-norm", type=float, default=1.0, help="gradient clipping; v4 had two loss spikes at 1.0")
    ap.add_argument("--data", default="sft_v4", help="dataset folder under data/ (train.jsonl, val.jsonl, manifest.json)")
    ap.add_argument("--seed", type=int, default=42)
    a = ap.parse_args()

    from unsloth import FastLanguageModel  # noqa: E402  (must be imported before transformers/trl)
    import torch
    from datasets import Dataset
    from transformers import TrainerCallback
    from trl import SFTConfig, SFTTrainer

    out_dir = RUNS / a.run
    out_dir.mkdir(parents=True, exist_ok=True)
    log = open(out_dir / "train.log", "a", encoding="utf-8")

    def say(*parts):
        msg = " ".join(str(p) for p in parts)
        print(msg, flush=True)
        log.write(msg + "\n")
        log.flush()

    model, tokenizer = FastLanguageModel.from_pretrained(a.base, max_seq_length=a.max_len, dtype=None, load_in_4bit=bool(a.load_4bit))
    model = FastLanguageModel.get_peft_model(model, r=a.r, lora_alpha=a.alpha, lora_dropout=0.0, bias="none", target_modules=TARGETS,
                                             use_rslora=True, use_gradient_checkpointing="unsloth", random_state=a.seed)
    say("base", a.base, "| 4-bit", bool(a.load_4bit), "| r", a.r, "alpha", a.alpha, "rsLoRA | GPU", torch.cuda.get_device_name(0))

    train_rows = read_jsonl(DATA / a.data / "train.jsonl")
    val_rows = read_jsonl(DATA / a.data / "val.jsonl")
    if a.smoke:
        train_rows, val_rows = train_rows[::max(1, len(train_rows) // 200)][:200], val_rows[:20]
    keep = lambda r: len(tokenizer(r["prompt"] + r["completion"])["input_ids"]) <= a.max_len
    n0 = len(train_rows)
    train_rows = [r for r in train_rows if keep(r)]
    say(f"rows: {len(train_rows)} train (dropped {n0 - len(train_rows)} over {a.max_len} tokens), {len(val_rows)} val")
    ds = Dataset.from_list([{"prompt": r["prompt"], "completion": r["completion"]} for r in train_rows])
    val = Dataset.from_list([{"prompt": r["prompt"], "completion": r["completion"]} for r in val_rows])

    quiz = read_jsonl(EVALSETS / "quiz.jsonl")
    system = (ROOT / "prompts" / "system_v1.txt").read_text(encoding="utf-8").strip()
    quiz_prompts = [f"<|im_start|>system\n{system}<|im_end|>\n<|im_start|>user\n{q['question']}\n\nAnswer briefly, in one or two sentences."
                    f"<|im_end|>\n<|im_start|>assistant\n<think>\n\n</think>\n\n" for q in quiz]

    def quiz_accuracy() -> float:
        FastLanguageModel.for_inference(model)
        tokenizer.padding_side = "left"
        correct = 0
        for i in range(0, len(quiz), 16):
            enc = tokenizer(quiz_prompts[i:i + 16], return_tensors="pt", padding=True).to("cuda")
            with torch.no_grad():
                out = model.generate(**enc, max_new_tokens=60, do_sample=False, pad_token_id=tokenizer.pad_token_id or tokenizer.eos_token_id)
            for q, o in zip(quiz[i:i + 16], out):
                correct += quiz_correct(q, tokenizer.decode(o[enc["input_ids"].shape[1]:], skip_special_tokens=True))
        FastLanguageModel.for_training(model)
        return correct / len(quiz)

    best = {"quiz": -1.0, "step": 0}

    class QuizCallback(TrainerCallback):
        def on_step_end(self, args, state, control, **kw):
            if state.global_step % a.quiz_every == 0 and state.global_step > 0:
                acc = quiz_accuracy()
                say(f"step {state.global_step}: quiz {acc:.0%}")
                if acc > best["quiz"]:
                    best.update(quiz=acc, step=state.global_step)
                    model.save_pretrained(str(out_dir / "best_adapter"))
                    tokenizer.save_pretrained(str(out_dir / "best_adapter"))
            return control

    class DivergenceGuard(TrainerCallback):
        """Stops training (and leaves runs/<run>/DIVERGED) if validation loss rises well above its best so far, e.g. after a
        bad resume: on 2026-10-20 a resume took validation loss from 1.77 to 7.9 and five hours were lost before anyone saw it."""
        def on_evaluate(self, args, state, control, metrics=None, **kw):
            loss = (metrics or {}).get("eval_loss")
            best = state.best_metric
            if loss is not None and best is not None and loss > best * a.diverge_ratio:
                say(f"DIVERGED at step {state.global_step}: eval loss {loss:.3f} > {a.diverge_ratio} x best {best:.3f}; stopping")
                (out_dir / "DIVERGED").write_text(json.dumps({"step": state.global_step, "eval_loss": loss, "best": best,
                                                               "best_checkpoint": state.best_model_checkpoint}), encoding="utf-8")
                control.should_training_stop = True
            return control

    total_steps = a.max_steps if a.max_steps > 0 else math.ceil(len(ds) / (a.batch * a.grad_accum)) * a.epochs
    cfg = SFTConfig(output_dir=str(out_dir / "ckpt"), max_length=a.max_len, completion_only_loss=True,
                    per_device_train_batch_size=a.batch, gradient_accumulation_steps=a.grad_accum,
                    num_train_epochs=a.epochs, max_steps=30 if a.smoke else a.max_steps, learning_rate=a.lr,
                    lr_scheduler_type="cosine", warmup_steps=max(1, round(0.03 * total_steps)), weight_decay=0.01, max_grad_norm=a.max_grad_norm,
                    optim="adamw_8bit", bf16=True, fp16=False, logging_steps=10, eval_strategy="steps", eval_steps=a.save_steps,   # evaluate at every checkpoint so the best one is marked
                   
                    save_strategy="steps", save_steps=a.save_steps, save_total_limit=a.keep_ckpts, per_device_eval_batch_size=2,
                    metric_for_best_model="eval_loss", greater_is_better=False,   # the best checkpoint is never rotated away
                    seed=a.seed, report_to="none", dataset_num_proc=1)
    trainer = SFTTrainer(model=model, tokenizer=tokenizer, train_dataset=ds, eval_dataset=val, args=cfg, callbacks=[QuizCallback(), DivergenceGuard()])
    resume_from = None
    if a.resume:
        ckpts = sorted((out_dir / "ckpt").glob("checkpoint-*"), key=lambda p: int(p.name.split("-")[1]))
        if ckpts:
            src = ckpts[-1]
            staged = out_dir / "resume_staging" / src.name      # a prepared copy; the checkpoint itself stays untouched
            shutil.rmtree(staged.parent, ignore_errors=True)
            shutil.copytree(src, staged, ignore=(shutil.ignore_patterns("optimizer.pt") if a.resume_mode == "weights" else None))
            st = json.loads((staged / "trainer_state.json").read_text(encoding="utf-8"))
            st["save_steps"], st["eval_steps"] = a.save_steps, cfg.eval_steps       # otherwise the old intervals stick
            (staged / "trainer_state.json").write_text(json.dumps(st, indent=2), encoding="utf-8")
            resume_from = str(staged)
        say(f"resuming ({a.resume_mode}) from {ckpts[-1] if ckpts else None}")
    prev = out_dir / "run_manifest.partial.json"
    if a.resume and prev.exists():
        base_quiz = json.loads(prev.read_text(encoding="utf-8"))["base_quiz"]
    else:
        base_quiz = quiz_accuracy()
        prev.write_text(json.dumps({"base_quiz": base_quiz}), encoding="utf-8")
    say(f"base quiz accuracy before training: {base_quiz:.0%}")
    t0 = time.time()
    result = trainer.train(resume_from_checkpoint=resume_from)
    if (out_dir / "DIVERGED").exists():
        say("stopped by the divergence guard; no final adapter written. See runs/<run>/DIVERGED for the best checkpoint.")
        sys.exit(3)
    hours = (time.time() - t0) / 3600
    final_eval = trainer.evaluate()
    final_quiz = quiz_accuracy()
    model.save_pretrained(str(out_dir / "adapter"))
    tokenizer.save_pretrained(str(out_dir / "adapter"))
    if best["quiz"] < final_quiz:
        best.update(quiz=final_quiz, step=result.global_step)
        shutil.rmtree(out_dir / "best_adapter", ignore_errors=True)
        shutil.copytree(out_dir / "adapter", out_dir / "best_adapter")
    manifest = {"run": a.run, "base_model": a.base, "load_4bit": bool(a.load_4bit), "smoke": a.smoke,
                "lora": {"r": a.r, "alpha": a.alpha, "rslora": True, "dropout": 0.0, "target_modules": TARGETS},
                "training": {"max_grad_norm": a.max_grad_norm, "data": a.data, "max_length": a.max_len, "batch": a.batch, "grad_accum": a.grad_accum, "epochs": a.epochs, "lr": a.lr,
                             "weight_decay": 0.01, "seed": a.seed, "steps": result.global_step, "hours": round(hours, 2), "bf16": True},
                "data": {"train": len(ds), "val": len(val), "manifest": json.loads((DATA / a.data / "manifest.json").read_text(encoding="utf-8"))},
                "val_loss": final_eval.get("eval_loss"), "quiz": {"base": base_quiz, "final": final_quiz, "best": best},
                "peak_gpu_gib": round(torch.cuda.max_memory_allocated() / 2**30, 1), "gpu": torch.cuda.get_device_name(0)}
    (out_dir / "run_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    say(f"done in {hours:.2f} h | val loss {final_eval.get('eval_loss'):.3f} | quiz base {base_quiz:.0%} -> final {final_quiz:.0%} (best {best['quiz']:.0%} at step {best['step']})")


if __name__ == "__main__":
    main()
