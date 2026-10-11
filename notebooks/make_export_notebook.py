"""Builds notebooks/export_gguf.ipynb (Phase 7.1-7.2): merge the LoRA adapter into the fp16 base and make a GGUF.

CPU-only (no GPU hours). Input on Kaggle: a dataset holding the adapter (adapter_config.json + weights).
Output: /kaggle/working/<OUT_NAME>.Q4_K_M.gguf and export_manifest.json.
Intermediates (merged fp16 model, f16 GGUF) go to a scratch folder because /kaggle/working is limited to 20 GB.
"""
import json
import pathlib

cells = []


def md(s):
    cells.append({"cell_type": "markdown", "metadata": {}, "source": s.strip("\n")})


def code(s):
    cells.append({"cell_type": "code", "metadata": {}, "execution_count": None, "outputs": [], "source": s.strip("\n")})


md("# Jyotish LoRA: merge and export to GGUF (Phase 7)\n\nMerges the adapter into the fp16 base, converts to GGUF with llama.cpp and quantizes to Q4_K_M.")

code("""
!pip install -q -U transformers peft accelerate sentencepiece protobuf
!pip install -q gguf
!pip uninstall -y -q torchao
""")

code("""
import glob, hashlib, json, os, re, shutil, subprocess, time

# ---------- settings ----------
BASE_MODEL = "Qwen/Qwen3-8B"
ADAPTER_HINT = ""            # substring of the adapter path when several inputs carry adapters
OUT_NAME = "astro-v2-8b"
QUANTS = ["Q4_K_M"]
SCRATCH = "/kaggle/temp" if os.path.isdir("/kaggle/temp") else "/tmp"
OUT = "/kaggle/working"

def sh(cmd, **kw):
    print("$", cmd, flush=True)
    r = subprocess.run(cmd, shell=True, text=True, capture_output=True, **kw)
    print((r.stdout + r.stderr)[-1500:], flush=True)
    assert r.returncode == 0, "command failed"

print(shutil.disk_usage(SCRATCH))
assert shutil.disk_usage(SCRATCH).free > 40 * 2**30, "not enough scratch space for the merged model and the f16 GGUF"
adapters = sorted(glob.glob("/kaggle/input/**/adapter_config.json", recursive=True))
adapters = [a for a in adapters if ADAPTER_HINT in a] or adapters
ADAPTER = os.path.dirname(adapters[-1])
print("adapter:", ADAPTER)
""")

code("""
import torch
from transformers import AutoModelForCausalLM, AutoTokenizer
from peft import PeftModel

t0 = time.time()
MERGED = SCRATCH + "/merged"
tok = AutoTokenizer.from_pretrained(BASE_MODEL)
model = AutoModelForCausalLM.from_pretrained(BASE_MODEL, dtype=torch.float16, device_map={"": "cpu"}, low_cpu_mem_usage=True)
model = PeftModel.from_pretrained(model, ADAPTER).merge_and_unload()
model.save_pretrained(MERGED, safe_serialization=True)
# llama.cpp's converter installs an older transformers that cannot read tokenizer files re-saved by a newer one
# (extra_special_tokens becomes a list), so the merged model gets the original tokenizer files from the base repo
from huggingface_hub import snapshot_download
snapshot_download(BASE_MODEL, allow_patterns=["tokenizer*", "vocab.json", "merges.txt"], local_dir=MERGED)
del model
print("merged and saved in %.1f min" % ((time.time() - t0) / 60))
""")

code("""
sh("git clone --depth 1 https://github.com/ggml-org/llama.cpp " + SCRATCH + "/llama.cpp")
sh("pip install -q -r " + SCRATCH + "/llama.cpp/requirements/requirements-convert_hf_to_gguf.txt")
sh("cd " + SCRATCH + "/llama.cpp && cmake -B build -DGGML_NATIVE=OFF -DLLAMA_CURL=OFF > /dev/null && cmake --build build --target llama-quantize -j4")
F16 = SCRATCH + "/" + OUT_NAME + ".f16.gguf"
sh("python " + SCRATCH + "/llama.cpp/convert_hf_to_gguf.py " + MERGED + " --outtype f16 --outfile " + F16)
""")

code("""
manifest = {"base": BASE_MODEL, "adapter": ADAPTER, "files": {}}
for q in QUANTS:
    dst = "%s/%s.%s.gguf" % (OUT, OUT_NAME, q)
    sh("%s/llama.cpp/build/bin/llama-quantize %s %s %s" % (SCRATCH, F16, dst, q))
    h = hashlib.sha256()
    with open(dst, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 24), b""):
            h.update(chunk)
    manifest["files"][os.path.basename(dst)] = {"bytes": os.path.getsize(dst), "sha256": h.hexdigest()}
# the chat template as stored in the tokenizer, for checking the Ollama template against it
manifest["chat_template"] = tok.chat_template
json.dump(manifest, open(OUT + "/export_manifest.json", "w"), indent=2)
print(json.dumps({k: v for k, v in manifest.items() if k != "chat_template"}, indent=2))
""")

nb = {"cells": cells, "metadata": {"kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
                                   "language_info": {"name": "python"}}, "nbformat": 4, "nbformat_minor": 5}
for c in cells:
    if c["cell_type"] == "code":
        compile("\n".join(l for l in c["source"].splitlines() if not l.startswith("!")), "cell", "exec")
path = pathlib.Path(__file__).with_name("export_gguf.ipynb")
path.write_text(json.dumps(nb, indent=1, ensure_ascii=False), encoding="utf-8")
print("wrote", path, "- all code cells compile")
