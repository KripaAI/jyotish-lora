"""Builds notebooks/rule_qa_kaggle.ipynb: the v4 paraphrase generator (src/dataset/rule_qa.py) on a free Kaggle T4.

The workstation GPU does most of the work; each Kaggle kernel takes one shard of the rule base so several kernels and the
workstation never overlap. The kernel runs llama.cpp (prebuilt CUDA build, same release as the GGUF eval notebooks) with a
Qwen3-14B Q4_K_M GGUF from Hugging Face, then calls the repo's own generator against it (`--backend llamacpp`).

Inputs on Kaggle: dataset `astro-rules-v4` (rules.jsonl, code.zip, done_rule_ids.txt). Output: /kaggle/working/samples_<shard>.jsonl,
folded back with `python -m src.dataset.rule_qa merge-samples <file>`.

    python notebooks/make_rule_qa_notebook.py            # writes the notebook
    python notebooks/make_rule_qa_notebook.py --dataset  # also refreshes kaggle/astro-rules-v4/ (rules, code zip, done ids)
"""
import json
import pathlib
import sys
import zipfile

HERE = pathlib.Path(__file__).parent
ROOT = HERE.parent


def cell(kind, s):
    base = {"cell_type": kind, "metadata": {}, "source": s.strip("\n")}
    return base if kind == "markdown" else {**base, "execution_count": None, "outputs": []}


cells = [cell("markdown", "# Jyotish LoRA v4: rule paraphrases on a Kaggle T4\n\nRuns one shard of `src/dataset/rule_qa.py generate` "
                          "against llama.cpp serving Qwen3-14B Q4_K_M. Output: `samples_<shard>.jsonl` in the kernel output; "
                          "download it and run `python -m src.dataset.rule_qa merge-samples <file>` on the workstation.")]

cells.append(cell("code", r"""
import glob, json, os, subprocess, sys, tarfile, time, urllib.request, hashlib, zipfile
os.environ["CUDA_VISIBLE_DEVICES"] = "0"       # one GPU per kernel

# ---------- settings ----------
SHARDS = "4/8"                 # which shards of the rule base this kernel takes, e.g. "4/8" or "4,5/8"
K = 4                          # pairs per rule
PARALLEL = 4                   # llama-server slots = generator workers
MAX_HOURS = 11.3               # stop and save before Kaggle's 12 h limit; rerun with the same SHARDS to continue
RELEASE = "b11513"
MODEL_REPO = "unsloth/Qwen3-14B-GGUF"
MODEL_FILE = "Qwen3-14B-Q4_K_M.gguf"
CTX_PER_SLOT = 4096
PORT = 8080
WORK = "/kaggle/temp" if os.path.isdir("/kaggle/temp") else "/tmp"
PREBUILT = {
    "llama-b11513-bin-ubuntu-cuda-12.8-x64.tar.gz": "af399b958079ec0a0a002faa5b2432f63269c0bf862e9f4f8add67a38a17aa33",
    "cudart-llama-b11513-bin-ubuntu-cuda-12.8-x64.tar.gz": "bb8ac07d9ae02a9d834d03cd5b2ed7c3b9720f46aea02414d0c304d066fec13c",
}
"""))

cells.append(cell("code", r"""
def sh(cmd, check=True):
    print("$", cmd, flush=True)
    r = subprocess.run(cmd, shell=True, text=True, capture_output=True)
    print((r.stdout + r.stderr)[-2000:], flush=True)
    if check:
        assert r.returncode == 0, "command failed: " + cmd
    return r.returncode, r.stdout + r.stderr

print(sh("nvidia-smi")[1][:700])
sh(f"{sys.executable} -m pip install -q datasketch langdetect huggingface_hub pyswisseph")   # pyswisseph: belt and braces for the chart imports

# repo code -> /kaggle/working/repo. Kaggle sometimes unpacks code.zip on upload (then src/ sits under a code/ folder).
import shutil
REPO = "/kaggle/working/repo"
zips = glob.glob("/kaggle/input/**/code.zip", recursive=True)
if zips:
    zipfile.ZipFile(zips[0]).extractall(REPO)
else:
    marker = glob.glob("/kaggle/input/**/src/dataset/rule_qa.py", recursive=True)
    assert marker, "neither code.zip nor an unpacked code/src folder found in the inputs"
    base = os.path.dirname(os.path.dirname(os.path.dirname(marker[0])))
    for sub in ("src", "prompts"):
        shutil.copytree(os.path.join(base, sub), os.path.join(REPO, sub), dirs_exist_ok=True)
print("repo code at", REPO, os.listdir(REPO))
RULES = glob.glob("/kaggle/input/**/rules.jsonl", recursive=True)[0]
DONE = glob.glob("/kaggle/input/**/done_rule_ids.txt", recursive=True)
print("rules:", RULES, "| done list:", DONE)

# llama.cpp prebuilt CUDA build (verified sha256), fall back to a source build
def fetch(name, sha):
    d = WORK + "/llama_prebuilt"; os.makedirs(d, exist_ok=True)
    path = d + "/" + name
    if not os.path.exists(path):
        urllib.request.urlretrieve(f"https://github.com/ggml-org/llama.cpp/releases/download/{RELEASE}/{name}", path)
    assert hashlib.sha256(open(path, "rb").read()).hexdigest() == sha, "checksum mismatch: " + name
    tarfile.open(path).extractall(d)
    return d
for name, sha in PREBUILT.items():
    d = fetch(name, sha)
SERVER = glob.glob(d + "/**/llama-server", recursive=True)[0]
LIBS = os.path.dirname(SERVER)
os.environ["LD_LIBRARY_PATH"] = LIBS + ":" + os.environ.get("LD_LIBRARY_PATH", "")
rc, out = sh(f"chmod +x {SERVER} && {SERVER} --version", check=False)
if rc != 0:
    print("prebuilt build does not run here: building from source (about 10 min)")
    src = WORK + "/llama.cpp"
    sh(f"git clone --depth 1 --branch {RELEASE} https://github.com/ggml-org/llama.cpp {src}")
    sh(f"cd {src} && cmake -B build -DGGML_CUDA=ON -DCMAKE_BUILD_TYPE=Release && cmake --build build --target llama-server -j4")
    SERVER = src + "/build/bin/llama-server"
print("llama.cpp ready:", SERVER)

from huggingface_hub import hf_hub_download
MODEL = hf_hub_download(MODEL_REPO, MODEL_FILE, local_dir=WORK + "/model")
print("model:", MODEL, round(os.path.getsize(MODEL) / 2**30, 1), "GiB")
"""))

cells.append(cell("code", r"""
server_log = open("/kaggle/working/llama_server.log", "w")
server = subprocess.Popen([SERVER, "-m", MODEL, "-ngl", "99", "-c", str(CTX_PER_SLOT * PARALLEL), "-np", str(PARALLEL),
                           "--port", str(PORT), "--host", "127.0.0.1", "-fa", "on", "--jinja"], stdout=server_log, stderr=subprocess.STDOUT)
t0 = time.time()
while True:
    try:
        urllib.request.urlopen(f"http://127.0.0.1:{PORT}/health", timeout=5).read()
        break
    except Exception:
        time.sleep(5)
    assert server.poll() is None, "llama-server exited: see /kaggle/working/llama_server.log"
    assert time.time() - t0 < 900, "llama-server did not become ready"
print("server ready in %.0f s" % (time.time() - t0))
"""))

cells.append(cell("code", r"""
# the repo's own generator and checks, against the local llama-server
shard_tag = SHARDS.replace("/", "of").replace(",", "-")
OUT = f"/kaggle/working/samples_{shard_tag}.jsonl"
cmd = [sys.executable, "-X", "utf8", "-m", "src.dataset.rule_qa", "generate", "--backend", "llamacpp",
       "--host", f"http://127.0.0.1:{PORT}", "--model", MODEL_FILE, "--k", str(K), "--workers", str(PARALLEL),
       "--shards", SHARDS, "--rules", RULES, "--samples", OUT, "--max-hours", str(MAX_HOURS)]
if DONE:
    # rules the workstation already sampled are skipped: the done list is a tiny samples-like file (rule_id per line)
    done_file = "/kaggle/working/done_from_workstation.jsonl"
    with open(done_file, "w") as f:
        for rid in open(DONE[0]).read().split():
            f.write(json.dumps({"rule_id": rid, "pairs": []}) + "\n")
    cmd += ["--done-from", done_file]
print(" ".join(cmd), flush=True)
r = subprocess.run(cmd, cwd=REPO, text=True, capture_output=True)
print(r.stdout[-6000:]); print(r.stderr[-3000:])
server.terminate()
assert r.returncode == 0, "generator failed (see stderr above)"   # so a broken run shows as an error, not 'complete'
n = sum(1 for _ in open(OUT)) if os.path.exists(OUT) else 0
json.dump({"shards": SHARDS, "k": K, "model": MODEL_FILE, "release": RELEASE, "rules_sampled": n},
          open("/kaggle/working/rule_qa_manifest.json", "w"), indent=2)
print("DONE:", n, "rules sampled ->", OUT)
"""))


def build_dataset() -> None:
    folder = ROOT / "kaggle" / "astro-rules-v4"
    folder.mkdir(parents=True, exist_ok=True)
    import shutil
    shutil.copy(ROOT / "data" / "sft_v4" / "rules.jsonl", folder / "rules.jsonl")
    with zipfile.ZipFile(folder / "code.zip", "w", zipfile.ZIP_DEFLATED) as z:
        for sub in ("src", "prompts"):
            for p in (ROOT / sub).rglob("*"):
                if p.is_file() and "__pycache__" not in p.parts and p.suffix not in (".joblib",):
                    z.write(p, p.relative_to(ROOT))
    samples = ROOT / "data" / "sft_v4" / "rule_qa" / "samples.jsonl"
    done = []
    if samples.exists():
        for line in open(samples, encoding="utf-8"):
            try:
                r = json.loads(line)
                if "pairs" in r:
                    done.append(r["rule_id"])
            except json.JSONDecodeError:
                pass
    (folder / "done_rule_ids.txt").write_text("\n".join(done), encoding="utf-8")
    (folder / "dataset-metadata.json").write_text(json.dumps(
        {"title": "astro-rules-v4", "id": "OWNER/astro-rules-v4", "licenses": [{"name": "other"}]}, indent=2), encoding="utf-8")
    print(f"dataset folder {folder}: rules.jsonl, code.zip, {len(done)} done rule ids (set the owner in dataset-metadata.json)")


if __name__ == "__main__":
    for c in cells:
        if c["cell_type"] == "code":
            compile("\n".join(l for l in c["source"].splitlines() if not l.startswith("!")), "cell", "exec")
    nb = {"cells": cells, "metadata": {"kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
                                       "language_info": {"name": "python"}}, "nbformat": 4, "nbformat_minor": 5}
    (HERE / "rule_qa_kaggle.ipynb").write_text(json.dumps(nb, indent=1, ensure_ascii=False), encoding="utf-8")
    print("wrote rule_qa_kaggle.ipynb; all code cells compile")
    if "--dataset" in sys.argv:
        build_dataset()
