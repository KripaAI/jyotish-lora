"""Stage 2C.3 + 2C.4: learning-rate sweep, then the full v4 run with the best rate, unattended. Runs in the training venv.

    python -m src.train.run_v4 [--rates 1e-4 2e-4 5e-4] [--sweep-steps 300]
Sweep runs: runs/v4-lr<rate>/ (300 steps each). The rate with the lowest validation loss (quiz accuracy breaks ties within
0.02) is used for runs/v4/ (one epoch, batch 4 x accumulation 2). Decisions are logged to runs/v4_sweep.md.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RUNS = ROOT / "runs"
COMMON = ["--batch", "4", "--grad-accum", "2"]


def train(run: str, extra: list[str]) -> dict:
    cmd = [sys.executable, "-X", "utf8", "-m", "src.train.train_local", "--run", run, *COMMON, *extra]
    with open(RUNS / f"{run}.stdout.log", "w", encoding="utf-8") as log:
        subprocess.run(cmd, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, check=False)
    m = RUNS / run / "run_manifest.json"
    return json.loads(m.read_text(encoding="utf-8")) if m.exists() else {}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rates", nargs="+", default=["1e-4", "2e-4", "5e-4"])
    ap.add_argument("--sweep-steps", type=int, default=300)
    a = ap.parse_args()
    lines = ["# v4 learning-rate sweep", "", f"Started {time.strftime('%Y-%m-%d %H:%M')}; {a.sweep_steps} steps each, batch 4 x 2.", "",
             "| LR | val loss | quiz | hours |", "|---|---|---|---|"]
    results = {}
    for lr in a.rates:
        m = train(f"v4-lr{lr}", ["--lr", lr, "--max-steps", str(a.sweep_steps), "--quiz-every", "100000"])
        if m:
            results[lr] = (m["val_loss"], m["quiz"]["final"])
            lines.append(f"| {lr} | {m['val_loss']:.4f} | {m['quiz']['final']:.0%} | {m['training']['hours']} |")
        else:
            lines.append(f"| {lr} | failed | | |")
        (RUNS / "v4_sweep.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    assert results, "every sweep run failed: see runs/v4-lr*.stdout.log"
    best_loss = min(v[0] for v in results.values())
    near = {lr: v for lr, v in results.items() if v[0] <= best_loss + 0.02}
    best = max(near, key=lambda lr: near[lr][1])
    lines += ["", f"Chosen: LR {best} (lowest validation loss, quiz accuracy breaking ties within 0.02). Full run started "
                  f"{time.strftime('%Y-%m-%d %H:%M')}: runs/v4/ (1 epoch)."]
    (RUNS / "v4_sweep.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    m = train("v4", ["--lr", best, "--epochs", "1", "--quiz-every", "1500"])
    lines.append(f"Full run finished {time.strftime('%Y-%m-%d %H:%M')}: " + (
        f"val loss {m['val_loss']:.4f}, quiz {m['quiz']['base']:.0%} -> {m['quiz']['final']:.0%} (best {m['quiz']['best']['quiz']:.0%} "
        f"at step {m['quiz']['best']['step']}), {m['training']['hours']} h." if m else "FAILED, see runs/v4.stdout.log"))
    (RUNS / "v4_sweep.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
