# FAQ

## General

### What is BMT AI OS?
An open-source, ARM64-native operating system that ships LLM inference, RAG, AI coding tools, and on-device training as first-class system services. Boot a $100 board and start coding with AI — fully offline.

### How is this different from just installing Ollama on Linux?
BMT AI OS is a complete OS image, not a package. It includes the kernel, init system, container runtime, AI stack, coding tools, dashboard, and training pipeline — all pre-configured and auto-wired. Ollama is one component inside it.

### Can I run this on x86 / my laptop?
The AI stack runs on any platform via Docker: `docker compose -f docker-compose.dev.yml up -d`. The full OS image is ARM64-only.

### Does it require internet?
Only for initial setup (pulling models and container images). After that, everything runs fully offline. Cloud LLM providers (OpenAI, Anthropic, etc.) are optional fallbacks.

## Hardware

### Which board should I buy?
- **Best performance:** Jetson Orin Nano Super (~$250) — only option for CUDA training
- **Best value:** Orange Pi 5 16GB (~$120) — good CPU inference, lots of RAM
- **Most accessible:** Raspberry Pi 5 + AI HAT+ 2 (~$210) — largest community

### Can I run 70B models?
Not on Tier 1 hardware. The Jetson Orin has 8GB RAM, which fits 7B models comfortably. For 70B models, you need Jetson AGX Orin (64GB) or Apple Silicon.

### Does the Raspberry Pi 5 without Hailo work?
Yes, but limited to 1-3B models at 2-5 tok/s (CPU-only). The AI HAT+ 2 adds 40 TOPS for models up to 1.5B.

## Models

### Which models are recommended?
Qwen-family models are the defaults (best open-source coding models in 2026):
- **Lite:** Qwen3.5-9B Q4 (~6GB)
- **Standard:** Qwen2.5-Coder-7B Q4 (~4GB) + Qwen3-Embedding-8B (~4GB)
- **Full:** Qwen3.5-27B Q4 (~18GB)

### Can I use other models?
Yes. Any model available on Ollama works. The provider layer supports any OpenAI-compatible API.

### What quantization should I use?
Q4_K_M is the default — best balance of quality and size. Use Q8_0 if you have extra RAM for better quality.

## Training

### Can I fine-tune models on this hardware?
Yes, using LoRA/QLoRA which trains only a small number of adapter parameters:
- **Jetson Orin:** LoRA 1.5B (~30 min), QLoRA 3B (~1 hr) with CUDA
- **RK3588:** LoRA 1.5B (~3 hrs) CPU-only
- **Pi 5:** LoRA <1B (~6 hrs) CPU-only

Full fine-tuning (all parameters) is not feasible on edge hardware.

### How do I use my fine-tuned model?
Train → export to GGUF → register with Ollama → it's immediately available to all coding tools and RAG pipeline.

## Coding Tools

### Which coding tools are included?
Claude Code, Aider, Continue.dev, Tabby, Open Interpreter, and support for SWE-agent, Codex CLI, and Mentat.

### How do I connect my IDE?
Point your IDE's AI settings to `http://<device-ip>:8080` as the API base URL. Works with Cursor, GitHub Copilot, and Sourcegraph Cody.

## License

### What license is BMT AI OS?
MIT License. Free for personal and commercial use.

### Who makes this?
[Bemind Technology Co., Ltd.](https://bemind.tech)
