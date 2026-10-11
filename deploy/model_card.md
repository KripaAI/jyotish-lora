---
license: apache-2.0
base_model: Qwen/Qwen3-8B
tags:
- gguf
- llama.cpp
- lora
- astrology
---

# astro-v2-8b (GGUF)

Qwen3-8B with the v2-8b QLoRA adapter merged in, converted to GGUF and quantized to Q4_K_M with llama.cpp.
It answers questions on Vedic (Parashari) astrology in the voice of an astrologer.

- File: `astro-v2-8b.Q4_K_M.gguf`, 5,027,783,584 bytes,
  sha256 `4b1898f08f1ef9476ff4221f6eeee6162a2766c4b8dfa6bb70b7f75bfb1ccf5d`.
- Use the training system prompt (`system_v1.txt`, included) and keep Qwen3 thinking mode off.
- Measured on held-out sets with an AI judge: quiz 73/100, safety 37/50, rubric 3.14/5.
- Known limits: factual accuracy in long answers is weak; it is not a substitute for medical, legal or financial advice;
  run it behind the safety layer from the project. Charts must be computed by code, not by the model.
