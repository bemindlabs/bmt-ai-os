# Development Setup (x86/ARM64 Docker)

Run the full BMT AI OS stack on any machine using Docker — no ARM64 hardware required.

## Prerequisites

- Docker & Docker Compose
- Python 3.10+
- (Optional) NVIDIA GPU + nvidia-docker for GPU acceleration

## Start the Dev Stack

```bash
git clone https://github.com/bemindlabs/bmt-ai-os.git
cd bmt-ai-os

# Start all services
docker compose -f docker-compose.dev.yml up -d
```

This starts:

| Service | Port | URL |
|---------|------|-----|
| Ollama | 11434 | http://localhost:11434 |
| ChromaDB | 8000 | http://localhost:8000 |
| Jupyter Lab | 8888 | http://localhost:8888 (token: `bmtaios`) |
| TensorBoard | 6006 | http://localhost:6006 |

## Verify

```bash
# Check services
curl http://localhost:11434/api/tags
curl http://localhost:8000/api/v1/heartbeat

# Pull a model
docker exec bmt-ollama ollama pull qwen2.5-coder:7b

# Chat
docker exec -it bmt-ollama ollama run qwen2.5-coder:7b
```

## Run the Controller

```bash
pip install docker
python bmt-ai-os/controller/main.py
```

## GPU Support

If you have an NVIDIA GPU, the dev stack automatically uses it. If not, remove the `deploy.resources.reservations.devices` section from `docker-compose.dev.yml`:

```yaml
# Remove this block if no NVIDIA GPU:
deploy:
  resources:
    reservations:
      devices:
        - driver: nvidia
          count: all
          capabilities: [gpu]
```

## Data Persistence

All data is stored in named Docker volumes:

| Volume | Contents |
|--------|----------|
| `bmt-ollama-models` | Downloaded LLM models |
| `bmt-chromadb-data` | Vector database |
| `bmt-jupyter-notebooks` | Jupyter notebooks |
| `bmt-training-runs` | TensorBoard training logs |

```bash
# View volumes
docker volume ls | grep bmt

# Remove all data (destructive)
docker compose -f docker-compose.dev.yml down -v
```

## Stop

```bash
docker compose -f docker-compose.dev.yml down
```
