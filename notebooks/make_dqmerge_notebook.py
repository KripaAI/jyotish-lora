"""Builds notebooks/export_dqmerge.ipynb: the dequantized-merge experiment.

The v2-8b adapter was trained on the 4-bit NF4 base, but the normal export merges it into the original fp16 weights, which the
adapter never saw. Here the merge uses the weights the adapter was trained against:
1. load the fp16 base on CPU (it supplies embeddings, norms and lm_head, which bitsandbytes does not quantize);
2. load the same base in 4-bit NF4 on the GPU with the training config (nf4, double quant, fp16 compute);
3. for every Linear4bit layer, dequantize its weight on the GPU and copy it over the matching fp16 weight on CPU;
4. merge the adapter into that model on CPU, save it with the base repo's tokenizer files, convert with llama.cpp and quantize.
Output: /kaggle/working/<OUT_NAME>.<QUANT>.gguf and export_manifest.json (includes the dequantize check).
Needs a GPU only for step 2-3 (bitsandbytes 4-bit). Input: dataset astro-lora-v2-8b.
"""
import json
import pathlib

cells = []


def md(s):
    cells.append({"cell_type": "markdown", "metadata": {}, "source": s.strip("\n")})


def code(s):
    cells.append({"cell_type": "code", "metadata": {}, "execution_count": None, "outputs": [], "source": s.strip("\n")})


md("# Jyotish LoRA: dequantized merge and GGUF export\n\nMerges the adapter into the dequantized NF4 weights it was trained on, then converts to GGUF.")

code("""
import os
os.environ["CUDA_VISIBLE_DEVICES"] = "0"
os.environ["PYTORCH_CUDA_ALLOC_CONF"] = "expandable_segments:True"
""")

code("""
!pip install -q -U transformers peft accelerate bitsandbytes sentencepiece protobuf
!pip install -q gguf
!pip uninstall -y -q torchao
""")

code("""
import gc, glob, hashlib, json, os, re, shutil, subprocess, time

# ---------- settings ----------
BASE_MODEL = "Qwen/Qwen3-8B"
ADAPTER_HINT = ""            # substring of the adapter path when several inputs carry adapters
OUT_NAME = "astro-v2-8b-dq"
QUANTS = ["Q4_K_M"]
SCRATCH = "/kaggle/temp" if os.path.isdir("/kaggle/temp") else "/tmp"
OUT = "/kaggle/working"

def sh(cmd, **kw):
    print("$", cmd, flush=True)
    r = subprocess.run(cmd, shell=True, text=True, capture_output=True, **kw)
    print((r.stdout + r.stderr)[-1500:], flush=True)
    assert r.returncode == 0, "command failed"

du = shutil.disk_usage(SCRATCH)
print("scratch", SCRATCH, "free GiB %.1f" % (du.free / 2**30))
assert du.free > 36 * 2**30, "not enough scratch space for the merged model and the f16 GGUF"
adapters = sorted(glob.glob("/kaggle/input/**/adapter_config.json", recursive=True))
adapters = [a for a in adapters if ADAPTER_HINT in a] or adapters
ADAPTER = os.path.dirname(adapters[-1])
print("adapter:", ADAPTER)
""")

code("""
import torch
import bitsandbytes as bnb
from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig
from peft import PeftModel

t0 = time.time()
tok = AutoTokenizer.from_pretrained(BASE_MODEL)
model = AutoModelForCausalLM.from_pretrained(BASE_MODEL, dtype=torch.float16, device_map={"": "cpu"}, low_cpu_mem_usage=True)
print("fp16 base on CPU in %.1f min" % ((time.time() - t0) / 60), flush=True)

# exactly the 4-bit config used in training and in evaluation run A
qcfg = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type="nf4", bnb_4bit_use_double_quant=True,
                          bnb_4bit_compute_dtype=torch.float16)
q = AutoModelForCausalLM.from_pretrained(BASE_MODEL, quantization_config=qcfg, dtype=torch.float16, device_map={"": 0})
print("4-bit base on GPU in %.1f min" % ((time.time() - t0) / 60), flush=True)

cpu_mods = dict(model.named_modules())
replaced, rel_err = 0, []
with torch.no_grad():
    for name, m in q.named_modules():
        if not isinstance(m, bnb.nn.Linear4bit):
            continue
        w = bnb.functional.dequantize_4bit(m.weight.data, m.weight.quant_state).to(torch.float16)
        target = cpu_mods[name].weight
        assert tuple(w.shape) == tuple(target.shape), (name, w.shape, target.shape)
        w = w.cpu()
        if replaced < 3 or replaced % 50 == 0:
            rel_err.append([name, float((w.float() - target.float()).norm() / target.float().norm())])
        target.data.copy_(w)
        if m.bias is not None:
            cpu_mods[name].bias.data.copy_(m.bias.data.to(torch.float16).cpu())
        replaced += 1
        del w
n_linear = sum(isinstance(m, torch.nn.Linear) for m in model.modules())
kept = [n for n, m in model.named_modules() if isinstance(m, torch.nn.Linear) and not isinstance(q.get_submodule(n), bnb.nn.Linear4bit)]
print("dequantized and copied", replaced, "of", n_linear, "Linear layers; left as fp16:", kept)
print("relative weight difference NF4 vs fp16 (sample):", rel_err[:6])
assert replaced > 0 and replaced == n_linear - len(kept)
assert all(0 < e < 0.5 for _, e in rel_err), "dequantized weights look wrong"
del q; gc.collect(); torch.cuda.empty_cache()
DQ = {"replaced": replaced, "linear_total": n_linear, "kept_fp16": kept, "rel_err_sample": rel_err,
      "minutes": round((time.time() - t0) / 60, 1)}
""")

code("""
t1 = time.time()
MERGED = SCRATCH + "/merged"
model = PeftModel.from_pretrained(model, ADAPTER).merge_and_unload()
model.save_pretrained(MERGED, safe_serialization=True)
# llama.cpp's converter installs an older transformers that cannot read tokenizer files re-saved by a newer one,
# so the merged model gets the original tokenizer files from the base repo
from huggingface_hub import snapshot_download
snapshot_download(BASE_MODEL, allow_patterns=["tokenizer*", "vocab.json", "merges.txt"], local_dir=MERGED)
del model; gc.collect()
print("merged and saved in %.1f min" % ((time.time() - t1) / 60))
""")

code("""
sh("git clone --depth 1 https://github.com/ggml-org/llama.cpp " + SCRATCH + "/llama.cpp")
sh("pip install -q -r " + SCRATCH + "/llama.cpp/requirements/requirements-convert_hf_to_gguf.txt")
sh("cd " + SCRATCH + "/llama.cpp && cmake -B build -DGGML_NATIVE=OFF -DLLAMA_CURL=OFF > /dev/null && cmake --build build --target llama-quantize -j4")
F16 = SCRATCH + "/" + OUT_NAME + ".f16.gguf"
sh("python " + SCRATCH + "/llama.cpp/convert_hf_to_gguf.py " + MERGED + " --outtype f16 --outfile " + F16)
shutil.rmtree(MERGED, ignore_errors=True)
LLAMA_COMMIT = subprocess.run("git -C " + SCRATCH + "/llama.cpp rev-parse HEAD", shell=True, text=True, capture_output=True).stdout.strip()
""")

code("""
manifest = {"base": BASE_MODEL, "adapter": ADAPTER, "merge": "dequantized NF4 (double quant) + adapter", "dequantize": DQ, "llama_cpp_commit": LLAMA_COMMIT, "files": {}}
for qn in QUANTS:
    dst = "%s/%s.%s.gguf" % (OUT, OUT_NAME, qn)
    sh("%s/llama.cpp/build/bin/llama-quantize %s %s %s" % (SCRATCH, F16, dst, qn))
    h = hashlib.sha256()
    with open(dst, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 24), b""):
            h.update(chunk)
    manifest["files"][os.path.basename(dst)] = {"bytes": os.path.getsize(dst), "sha256": h.hexdigest()}
manifest["chat_template"] = tok.chat_template
json.dump(manifest, open(OUT + "/export_manifest.json", "w"), indent=2)
print(json.dumps({k: v for k, v in manifest.items() if k != "chat_template"}, indent=2))
""")

nb = {"cells": cells, "metadata": {"kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
                                   "language_info": {"name": "python"}}, "nbformat": 4, "nbformat_minor": 5}
for c in cells:
    if c["cell_type"] == "code":
        compile("\n".join(l for l in c["source"].splitlines() if not l.startswith("!")), "cell", "exec")
path = pathlib.Path(__file__).with_name("export_dqmerge.ipynb")
path.write_text(json.dumps(nb, indent=1, ensure_ascii=False), encoding="utf-8")
print("wrote", path, "- all code cells compile")
