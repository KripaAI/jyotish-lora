---
title: Jyotish LoRA server
emoji: 🪐
colorFrom: indigo
colorTo: yellow
sdk: docker
app_port: 7860
pinned: false
---

# Jyotish LoRA server

llama.cpp server for the fine-tuned Qwen3-8B Vedic astrology model (v2-8b, GGUF Q4_K_M). It exposes an OpenAI-compatible API.

Space settings needed:
- Secret `HF_TOKEN`: a read token that can access the private model repo.
- Secret `API_KEY`: any long random string. Clients send it as `Authorization: Bearer <API_KEY>`.
- Variable `MODEL_REPO`: the model repo, for example `your-username/astro-v2-8b-gguf`.

Clients must use the training system prompt (`prompts/system_v1.txt`), keep thinking off, and wrap calls with the safety layer
(`src/app/safety.py`). This server runs the raw model only.
