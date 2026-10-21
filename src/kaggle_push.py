"""Prepare a Kaggle kernel folder from a notebook with chosen settings, and push it.

    python -m src.kaggle_push train --id astro-lora-v2-4b --data astro-sft-v2 --set RUN_NAME='"astro-lora-v2-4b"' [--push]
    python -m src.kaggle_push eval  --id astro-eval-v2-4b --data astro-eval-v2 --kernel-input astro-lora-v2-4b [--push]

--set NAME=VALUE replaces the line `NAME = ...` in the notebook's code (VALUE is Python source). The Kaggle token is read
from the Desktop env file and never printed.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

from src.common import ROOT

# Usernames can be overridden per machine (KAGGLE_OWNER_MAIN / KAGGLE_OWNER_NEW) when different accounts are used.
ACCOUNTS = {"main": (os.environ.get("KAGGLE_OWNER_MAIN", "krishmithlesh0786"), "KAGGLE_API_TOKEN"),
            "new": (os.environ.get("KAGGLE_OWNER_NEW", "kripashankar81"), "NEW_KAGGLE_API_TOKEN")}
ACCOUNT = os.environ.get("KAGGLE_ACCOUNT", "main")   # "new" runs everything on the second account
OWNER = ACCOUNTS[ACCOUNT][0]
# Paths differ per machine: the original laptop (user rdits) or the workstation (user mobirizer). Override with env vars.
ENV_FILE = Path(os.environ.get("KAGGLE_ENV_FILE", r"C:\Users\rdits\OneDrive\Desktop\env"))
KAGGLE = Path(os.environ.get("KAGGLE_CLI", r"C:\Users\rdits\.venvs\astro\Scripts\kaggle.exe"))
if not KAGGLE.exists():
    KAGGLE = Path(sys.executable).with_name("kaggle.exe")   # the venv that runs this module
NOTEBOOKS = {"train": ROOT / "notebooks" / "train_lora.ipynb", "eval": ROOT / "notebooks" / "eval_generate.ipynb",
             "export": ROOT / "notebooks" / "export_gguf.ipynb", "dqmerge": ROOT / "notebooks" / "export_dqmerge.ipynb",
             "gguf_eval": ROOT / "notebooks" / "gguf_eval.ipynb", "mmlu": ROOT / "notebooks" / "mmlu_forgetting.ipynb", "twogpu": ROOT / "notebooks" / "twogpu_smoke.ipynb", "live_demo": ROOT / "notebooks" / "live_demo.ipynb",
             "dpo_sample": ROOT / "notebooks" / "dpo_sample.ipynb", "dpo_train": ROOT / "notebooks" / "dpo_train.ipynb",
             "rule_qa": ROOT / "notebooks" / "rule_qa_kaggle.ipynb"}
WORK = ROOT / "runs" / "kaggle_push"


def kaggle_env() -> dict:
    token = None
    for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        m = re.match(rf"\s*(?:export\s+)?{ACCOUNTS[ACCOUNT][1]}\s*=\s*(.*)", line)
        if m:
            token = m.group(1).strip().strip("\"'")
    assert token, f"{ACCOUNTS[ACCOUNT][1]} not found in the env file"
    return {**os.environ, "KAGGLE_API_TOKEN": token, "PYTHONUTF8": "1"}


def kaggle(*args: str) -> str:
    out = subprocess.run([str(KAGGLE), *args], capture_output=True, text=True, encoding="utf-8", env=kaggle_env())
    return (out.stdout + out.stderr).strip()


def prepare(kind: str, kernel_id: str, data: list[str], kernel_inputs: list[str], settings: dict[str, str]) -> Path:
    nb = json.loads(NOTEBOOKS[kind].read_text(encoding="utf-8"))
    applied = set()
    for c in nb["cells"]:
        if c["cell_type"] != "code":
            continue
        lines = c["source"].split("\n")
        for i, line in enumerate(lines):
            for name, value in settings.items():
                if re.match(rf"{re.escape(name)}\s*=", line):
                    comment = line[line.index("#"):] if "#" in line else ""
                    lines[i] = f"{name} = {value}" + (f"   {comment}" if comment else "")
                    applied.add(name)
        c["source"] = "\n".join(lines)
    missing = set(settings) - applied
    assert not missing, f"settings not found in notebook: {missing}"
    folder = WORK / kernel_id
    folder.mkdir(parents=True, exist_ok=True)
    code_file = NOTEBOOKS[kind].name
    (folder / code_file).write_text(json.dumps(nb, indent=1, ensure_ascii=False), encoding="utf-8")
    meta = {"id": f"{OWNER}/{kernel_id}", "title": kernel_id, "code_file": code_file, "language": "python",
            "kernel_type": "notebook", "is_private": True, "enable_gpu": kind != "export", "enable_internet": True,
            "dataset_sources": [f"{OWNER}/{d}" for d in data], "kernel_sources": [f"{OWNER}/{k}" for k in kernel_inputs],
            "competition_sources": [], "model_sources": []}
    if kind != "export":
        meta["machine_shape"] = "NvidiaTeslaT4"
    (folder / "kernel-metadata.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return folder


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("kind", choices=sorted(NOTEBOOKS))
    ap.add_argument("--id", required=True)
    ap.add_argument("--data", nargs="*", default=[])
    ap.add_argument("--kernel-input", nargs="*", default=[])
    ap.add_argument("--set", nargs="*", default=[], help="NAME=VALUE (Python source)")
    ap.add_argument("--push", action="store_true")
    a = ap.parse_args()
    settings = dict(s.split("=", 1) for s in a.set)
    folder = prepare(a.kind, a.id, a.data, a.kernel_input, settings)
    print("prepared", folder, settings)
    if a.push:
        print(kaggle("kernels", "push", "-p", str(folder)))


if __name__ == "__main__":
    main()
