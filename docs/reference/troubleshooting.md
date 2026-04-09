# Troubleshooting

## Ollama Not Responding

```bash
# Check if running
curl http://localhost:11434/api/tags

# Check container status
docker ps | grep ollama

# View logs
docker logs bmt-ollama --tail 50

# Restart
docker restart bmt-ollama
```

**Common causes:**
- Model too large for available RAM — try a smaller model or quantization
- GPU/NPU driver not loaded — check `nvidia-smi` (Jetson) or `ls /dev/rknpu` (RK3588)

## ChromaDB Connection Failed

```bash
curl http://localhost:8000/api/v1/heartbeat

# Check logs
docker logs bmt-chromadb --tail 50

# Check disk space (ChromaDB needs room for embeddings)
df -h /var/lib/chromadb
```

## Out of Memory (OOM)

**Symptoms:** Services crash, `dmesg` shows OOM killer

**Fix:**
```bash
# Check current memory usage
free -h

# Switch to a lighter model preset
bmt-ai-os models install lite

# Or pull a smaller model
ollama pull qwen2.5-coder:3b
```

**RAM guidelines:**
| Device RAM | Max Model | Recommended Preset |
|-----------|-----------|-------------------|
| 8GB | 7B Q4 (tight) | lite (9B Q4) |
| 16GB | 13B Q4 | standard |
| 32GB | 27B Q4 | full |

## Slow Inference

**Expected speeds:**

| Hardware | 7B Q4 tok/s |
|----------|-------------|
| Jetson Orin | 15-22 |
| RK3588 (CPU) | 4-6 |
| Pi 5 (CPU) | 2-4 |

**If slower than expected:**
1. Check CPU temperature: `sensors` — throttling starts at ~80°C
2. Verify NPU/GPU is being used: check Ollama logs for acceleration
3. Ensure no other heavy processes: `htop`
4. Check quantization — Q4_K_M is fastest, BF16/FP16 is slowest

## Dashboard Not Loading

```bash
# Check port 9090
curl http://localhost:9090

# Check if the dashboard process is running
ps aux | grep next

# Rebuild dashboard
cd bmt-ai-os/dashboard && npm run build
```

## Dev Stack (Docker) Issues

```bash
# GPU not detected — remove GPU reservation from compose
# Edit docker-compose.dev.yml, remove deploy.resources section

# Port already in use
docker compose -f docker-compose.dev.yml down
lsof -i :11434  # Find what's using the port

# Reset all data
docker compose -f docker-compose.dev.yml down -v
```

## Getting Help

- [GitHub Issues](https://github.com/bemindlabs/bmt-ai-os/issues)
- [FAQ](faq.md)
- Security issues: security@bemind.tech
