"""Keeps a training run going without anyone watching: restarts it from the latest checkpoint after a crash, and after a
power cut once Windows is back (`install` puts a hidden launcher in the user's Startup folder, so Windows runs this again at every logon).

    python -m src.train.supervisor run --job v4          # the loop (run detached; the logon task does this)
    python -m src.train.supervisor install --job v4      # put the launcher in the Startup folder (current user, no admin needed)
    python -m src.train.supervisor uninstall --job v4    # remove it
    python -m src.train.supervisor status --job v4

A job is a set of train_local arguments in runs/supervisor_<job>.json (written by `install`). The loop:
- exits when runs/<run>/run_manifest.json exists (finished) or runs/<run>/DIVERGED exists (the guard stopped it; a person decides);
- starts training (with --resume if a checkpoint exists) whenever no train_local process for this run is alive;
- gives up after MAX_RESTARTS restarts in an hour (a crash loop needs a person, not more restarts).
Everything it does is appended to runs/supervisor_<job>.log; a second copy started at logon exits if one is already running.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RUNS = ROOT / "runs"
TRAIN_PY = Path(r"C:\Users\mobirizer\.venvs\train\Scripts\python.exe")
TASK = "JyotishLoRA-train-supervisor"
POLL = 60
MAX_RESTARTS = 4
JOBS = {"v4": {"run": "v4", "args": ["--batch", "4", "--grad-accum", "2", "--lr", "2e-4", "--epochs", "1", "--quiz-every", "1500",
                                     "--save-steps", "150", "--keep-ckpts", "3"]},
        # v5: rebalanced mix (data/sft_v5), lower LR and tighter clipping after v4's two loss spikes
        "v5": {"run": "v5", "args": ["--data", "sft_v5", "--batch", "4", "--grad-accum", "2", "--lr", "1.5e-4", "--max-grad-norm", "0.5",
                                     "--epochs", "1", "--quiz-every", "1500", "--save-steps", "150", "--keep-ckpts", "3"]}}


def log(job: str, msg: str) -> None:
    line = f"{time.strftime('%Y-%m-%d %H:%M:%S')} {msg}"
    print(line, flush=True)
    with open(RUNS / f"supervisor_{job}.log", "a", encoding="utf-8") as f:
        f.write(line + "\n")


def ps(query: str) -> str:
    return subprocess.run(["powershell", "-NoProfile", "-Command", query], capture_output=True, text=True).stdout.strip()


def count_procs(pattern: str) -> int:
    out = ps(f"(Get-CimInstance Win32_Process | Where-Object {{ $_.CommandLine -like '{pattern}' -and $_.Name -like 'python*' }} | Measure-Object).Count")
    try:
        return int(out or 0)
    except ValueError:
        return 0


def load_job(job: str) -> dict:
    p = RUNS / f"supervisor_{job}.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else JOBS[job]


def start_training(job: str, spec: dict) -> None:
    run = spec["run"]
    ckpts = list((RUNS / run / "ckpt").glob("checkpoint-*"))
    args = [str(TRAIN_PY), "-X", "utf8", "-m", "src.train.train_local", "--run", run, *spec["args"]]
    if ckpts:
        args += ["--resume", "--resume-mode", spec.get("resume_mode", "full")]   # full matched an uninterrupted run exactly (runs/rt-*)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    out = open(RUNS / f"{run}.sup-{stamp}.log", "w", encoding="utf-8")
    flags = 0x00000008 | 0x00000200 if os.name == "nt" else 0       # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    # PYTHONUNBUFFERED: metrics reach the log as they happen. FOR_DISABLE_CONSOLE_CTRL_HANDLER: the Intel Fortran runtime inside
    # numpy/scipy (MKL) otherwise aborts training on a console close event ("forrtl: error (200) ... window-CLOSE event",
    # which killed the v5 run at 13:56 on 2026-10-21).
    env = {**os.environ, "PYTHONUNBUFFERED": "1", "FOR_DISABLE_CONSOLE_CTRL_HANDLER": "1"}
    subprocess.Popen(args, cwd=ROOT, stdout=out, stderr=subprocess.STDOUT, creationflags=flags, env=env)
    log(job, f"started training ({'resume from ' + str(len(ckpts)) + ' checkpoint(s)' if ckpts else 'fresh'}); log runs/{run}.sup-{stamp}.log")


def rollback_once(job: str, run: str) -> bool:
    """After the divergence guard trips: move every checkpoint newer than the best one aside, clear the flag, and let the loop
    resume from the best checkpoint. Allowed once per run (marker ROLLED_BACK); returns False if already used."""
    d = RUNS / run
    marker = d / "ROLLED_BACK"
    if marker.exists():
        return False
    info = json.loads((d / "DIVERGED").read_text(encoding="utf-8"))
    best = info.get("best_checkpoint")
    if not best or not Path(best).exists():
        log(job, f"divergence guard tripped but the best checkpoint ({best}) is missing; cannot roll back")
        return False
    best_step = int(Path(best).name.split("-")[1])
    aside = d / "ckpt_after_divergence"
    aside.mkdir(exist_ok=True)
    for p in (d / "ckpt").glob("checkpoint-*"):
        if int(p.name.split("-")[1]) > best_step:
            p.rename(aside / p.name)
    (d / "DIVERGED").rename(d / f"DIVERGED.{time.strftime('%Y%m%d-%H%M%S')}")
    marker.write_text(json.dumps({"rolled_back_to": best, "at": time.strftime("%Y-%m-%d %H:%M:%S"), "divergence": info}), encoding="utf-8")
    log(job, f"divergence at step {info.get('step')} (eval {info.get('eval_loss'):.3f} vs best {info.get('best'):.3f}); "
             f"rolled back to {Path(best).name}; later checkpoints moved to ckpt_after_divergence/")
    return True


def run_loop(job: str) -> None:
    # Single instance via a lock file holding the PID. (Counting matching processes does not work on Windows: a venv's
    # python.exe is a launcher that starts a second interpreter process with the same command line.)
    lock = RUNS / f"supervisor_{job}.lock"
    if lock.exists():
        old = lock.read_text(encoding="utf-8").strip()
        if old.isdigit() and ps(f"if (Get-Process -Id {old} -ErrorAction SilentlyContinue) {{ 'alive' }}") == "alive":
            print(f"supervisor already running (pid {old}); exiting")
            return
    lock.write_text(str(os.getpid()), encoding="utf-8")
    spec = load_job(job)
    run = spec["run"]
    pattern = f"*src.train.train_local*--run {run} *"
    restarts: list[float] = []
    log(job, f"supervisor up for run {run}")
    while True:
        if (RUNS / run / "run_manifest.json").exists():
            log(job, "training finished (run_manifest.json present); supervisor exits")
            return
        if (RUNS / run / "DIVERGED").exists():
            if not rollback_once(job, run):
                log(job, "divergence guard stopped the run again after a rollback; supervisor exits for a person to look")
                return
        if count_procs(pattern) == 0:
            restarts = [t for t in restarts if time.time() - t < 3600]
            if len(restarts) >= MAX_RESTARTS:
                log(job, f"{MAX_RESTARTS} restarts within an hour: crash loop, supervisor exits; see the newest runs/{run}.sup-*.log")
                (RUNS / run / "CRASHLOOP").write_text(time.strftime("%Y-%m-%d %H:%M:%S"), encoding="utf-8")
                return
            if restarts or (RUNS / run / "ckpt").exists():
                log(job, "no training process alive")
            start_training(job, spec)
            restarts.append(time.time())
            time.sleep(180)      # loading the model takes ~2 minutes; don't double-start
        time.sleep(POLL)


def install(job: str) -> None:
    spec = load_job(job)
    (RUNS / f"supervisor_{job}.json").write_text(json.dumps(spec, indent=2), encoding="utf-8")
    action = f'"{TRAIN_PY}" -X utf8 -m src.train.supervisor run --job {job}'
    # A small launcher keeps the working directory right and runs hidden.
    launcher = RUNS / f"supervisor_{job}.vbs"
    launcher.write_text('Set sh = CreateObject("WScript.Shell")\r\n'
                        f'sh.CurrentDirectory = "{ROOT}"\r\n'
                        f'sh.Run """{TRAIN_PY}"" -X utf8 -m src.train.supervisor run --job {job}", 0, False\r\n',
                        encoding="utf-8")
    # A logon scheduled task needs administrator rights on this machine; the user's Startup folder does not, and Windows runs
    # everything in it at each logon of this user.
    import shutil as _sh
    _sh.copy(launcher, startup_path(job))
    print(f"installed {startup_path(job)} -> runs: {action}")


def startup_path(job: str) -> Path:
    return Path(os.environ["APPDATA"]) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup" / f"{TASK}-{job}.vbs"


def uninstall(job: str) -> None:
    p = startup_path(job)
    p.unlink(missing_ok=True)
    print(f"removed {p}")


def status(job: str) -> None:
    spec = load_job(job)
    run = spec["run"]
    lock = RUNS / f"supervisor_{job}.lock"
    pid = lock.read_text(encoding="utf-8").strip() if lock.exists() else ""
    alive = bool(pid) and ps(f"if (Get-Process -Id {pid} -ErrorAction SilentlyContinue) {{ 'alive' }}") == "alive"
    print("training processes:", count_procs(f"*src.train.train_local*--run {run} *"),
          "| supervisor alive:", alive, f"(pid {pid})" if pid else "",
          "| finished:", (RUNS / run / "run_manifest.json").exists(), "| diverged:", (RUNS / run / "DIVERGED").exists(),
          "| checkpoints:", sorted(p.name for p in (RUNS / run / "ckpt").glob("checkpoint-*")))
    print("starts at logon:", startup_path(job).exists(), startup_path(job))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("command", choices=["run", "install", "uninstall", "status"])
    ap.add_argument("--job", default="v4")
    a = ap.parse_args()
    {"run": run_loop, "install": install, "uninstall": uninstall, "status": status}[a.command](a.job)


if __name__ == "__main__":
    main()
