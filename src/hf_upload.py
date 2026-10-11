"""Upload the deployed GGUF to a private Hugging Face model repo, and optionally create the Docker Space that serves it.

    python -m src.hf_upload model              # private repo <user>/astro-v2-8b-gguf: GGUF, model card, system prompt, manifest
    python -m src.hf_upload space              # private Docker Space <user>/astro-v2-8b-server (needs a plan that allows it)

The token is read from the Desktop env file (HF_TOKEN=...) and never printed. The Space's API key is generated here, stored as a
Space secret, and saved to runs/hf_space_api_key.txt (keep that file private) so a client can use it.
"""
from __future__ import annotations

import argparse
import hashlib
import re
import secrets

from huggingface_hub import HfApi

from src.common import PROMPTS, ROOT, RUNS
from src.kaggle_push import ENV_FILE

GGUF = RUNS / "export8b" / "astro-v2-8b.Q4_K_M.gguf"
SHA256 = "4b1898f08f1ef9476ff4221f6eeee6162a2766c4b8dfa6bb70b7f75bfb1ccf5d"
MODEL_NAME, SPACE_NAME = "astro-v2-8b-gguf", "astro-v2-8b-server"


def token() -> str:
    for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        m = re.match(r"\s*(?:export\s+)?HF_TOKEN\s*=\s*(.*)", line)
        if m:
            return m.group(1).strip().strip("\"'")
    raise SystemExit("HF_TOKEN not found in the env file: create a write token at huggingface.co/settings/tokens and add HF_TOKEN=...")


def sha256(path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 24), b""):
            h.update(chunk)
    return h.hexdigest()


def upload_model(api: HfApi, user: str) -> str:
    assert sha256(GGUF) == SHA256, "local GGUF does not match the recorded sha256; not uploading"
    repo = f"{user}/{MODEL_NAME}"
    api.create_repo(repo, repo_type="model", private=True, exist_ok=True)
    api.upload_file(path_or_fileobj=str(ROOT / "deploy" / "model_card.md"), path_in_repo="README.md", repo_id=repo)
    api.upload_file(path_or_fileobj=str(PROMPTS / "system_v1.txt"), path_in_repo="system_v1.txt", repo_id=repo)
    api.upload_file(path_or_fileobj=str(RUNS / "export8b" / "export_manifest.json"), path_in_repo="export_manifest.json", repo_id=repo)
    print("uploading", GGUF.name, "(5 GB, resumable) ...", flush=True)
    api.upload_file(path_or_fileobj=str(GGUF), path_in_repo=GGUF.name, repo_id=repo)
    remote = {f.rfilename: f for f in api.model_info(repo, files_metadata=True).siblings}
    size = remote[GGUF.name].size
    print(f"done: https://huggingface.co/{repo} ({GGUF.name}: {size} bytes)")
    assert size == GGUF.stat().st_size, "uploaded size differs from the local file"
    return repo


def create_space(api: HfApi, user: str, tok: str) -> None:
    space, repo = f"{user}/{SPACE_NAME}", f"{user}/{MODEL_NAME}"
    api.create_repo(space, repo_type="space", space_sdk="docker", private=True, exist_ok=True)
    api.upload_folder(folder_path=str(ROOT / "deploy" / "hf_space"), repo_id=space, repo_type="space")
    key_file = RUNS / "hf_space_api_key.txt"
    key = key_file.read_text().strip() if key_file.exists() else secrets.token_urlsafe(32)
    key_file.write_text(key)
    api.add_space_secret(space, "HF_TOKEN", tok)
    api.add_space_secret(space, "API_KEY", key)
    api.add_space_variable(space, "MODEL_REPO", repo)
    sub = space.replace("/", "-").lower()
    print(f"Space created: https://huggingface.co/spaces/{space}\nAPI base URL once running: https://{sub}.hf.space/v1\n"
          f"API key saved to {key_file} (not printed). First start downloads the 5 GB model: allow several minutes.")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("what", choices=["model", "space"])
    a = ap.parse_args()
    tok = token()
    api = HfApi(token=tok)
    user = api.whoami()["name"]
    if a.what == "model":
        upload_model(api, user)
    else:
        create_space(api, user, tok)


if __name__ == "__main__":
    main()
