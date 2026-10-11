# Hugging Face Docker Space: serves the fine-tuned Jyotish model with llama.cpp's OpenAI-compatible server.
# At start-up llama-server downloads the GGUF from the (private) model repo, using the Space secret HF_TOKEN.
# Endpoints: POST /v1/chat/completions, POST /completion, GET /health. Every request needs "Authorization: Bearer <API_KEY>".
FROM ghcr.io/ggml-org/llama.cpp:server

# Writable cache for the downloaded model (Spaces run the container as a non-root user).
ENV LLAMA_CACHE=/tmp/llama-cache

# MODEL_REPO and API_KEY come from the Space's variables and secrets (see README.md in this folder).
ENTRYPOINT ["/bin/sh", "-c", "exec /app/llama-server --hf-repo \"$MODEL_REPO\" --hf-file astro-v2-8b.Q4_K_M.gguf --host 0.0.0.0 --port 7860 -c 4096 -t 2 --jinja --api-key \"$API_KEY\""]
