"""Resumable download of one large file from a Kaggle kernel's output.

    python -m src.kaggle_download astro-export-v2-8b astro-v2-8b.Q4_K_M.gguf runs/export8b --size 5027783584 --sha256 <hex>

`kaggle kernels output` loads the whole file into memory and keeps nothing if the connection drops (a 5 GB GGUF failed at
4.1 GB). This asks for the file's signed URL through the same API call, then downloads with HTTP Range requests,
appending to a .part file and resuming after any error. The URL is never printed. KAGGLE_ACCOUNT picks the account
(see src/kaggle_push.py).
"""
from __future__ import annotations

import argparse
import hashlib
import os
import time
from pathlib import Path

import requests

from src import kaggle_push


def signed_url(kernel: str, file_name: str) -> str:
    os.environ.update({k: v for k, v in kaggle_push.kaggle_env().items() if k == "KAGGLE_API_TOKEN"})
    from kaggle.api.kaggle_api_extended import KaggleApi
    from kagglesdk.kernels.types.kernels_api_service import ApiListKernelSessionOutputRequest
    api = KaggleApi()
    api.authenticate()
    with api.build_kaggle_client() as client:
        req = ApiListKernelSessionOutputRequest()
        req.user_name, req.kernel_slug = kaggle_push.OWNER, kernel
        req.page_size = 100
        for item in client.kernels.kernels_api_client.list_kernel_session_output(req).files or []:
            if item.file_name == file_name:
                return item.url
    raise FileNotFoundError(file_name)


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 24), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("kernel")
    ap.add_argument("file_name")
    ap.add_argument("dest_dir")
    ap.add_argument("--size", type=int, required=True, help="expected size in bytes")
    ap.add_argument("--sha256", help="expected sha256 (hex)")
    ap.add_argument("--attempts", type=int, default=60)
    a = ap.parse_args()
    dest = Path(a.dest_dir)
    dest.mkdir(parents=True, exist_ok=True)
    part, final = dest / (a.file_name + ".part"), dest / a.file_name
    for attempt in range(1, a.attempts + 1):
        have = part.stat().st_size if part.exists() else 0
        if have >= a.size:
            break
        try:
            url = signed_url(a.kernel, a.file_name)       # fresh each time: signed URLs expire
            with requests.get(url, headers={"Range": f"bytes={have}-"}, stream=True, timeout=60) as r:
                if r.status_code not in (200, 206):
                    raise RuntimeError(f"HTTP {r.status_code}")
                if r.status_code == 200 and have:          # server ignored Range: start over
                    have = 0
                    part.unlink()
                with open(part, "ab") as out:
                    for chunk in r.iter_content(1 << 20):
                        out.write(chunk)
        except Exception as e:                              # dropped connection etc.: resume
            print(f"attempt {attempt}: {type(e).__name__}; have {part.stat().st_size if part.exists() else 0} of {a.size}", flush=True)
            time.sleep(5)
    size = part.stat().st_size if part.exists() else 0
    assert size == a.size, f"incomplete: {size} of {a.size} bytes"
    if a.sha256:
        got = sha256(part)
        assert got == a.sha256, f"sha256 mismatch: {got}"
        print("sha256 matches")
    part.replace(final)
    print("downloaded", final, size, "bytes")


if __name__ == "__main__":
    main()
