# API Reference

BMT AI OS exposes a REST API at port 8080. The API is OpenAI-compatible, so any tool that supports the OpenAI API works with BMT AI OS out of the box.

## Base URL

```
http://<device-ip>:8080
```

For local development:

```
http://localhost:8080
```

## API Groups

| Group | Base Path | Description |
|-------|-----------|-------------|
| [OpenAI-Compatible](openai-compat.md) | `/v1/` | Chat, completions, embeddings, models |
| [RAG](rag.md) | `/api/v1/` | Query, ingest, collections |
| [Health & Status](health.md) | `/` | Health checks, system status, metrics |

## Interactive Documentation

When the controller is running, the interactive API docs (Swagger UI) are available at:

```
http://localhost:8080/docs
```

ReDoc is also available at:

```
http://localhost:8080/redoc
```

## Authentication

The API does not require authentication by default. For production deployments, see the [Security Policy](../security/security-policy.md) for hardening recommendations.

## OpenAPI Spec

The OpenAPI specification is served at:

```bash
curl http://localhost:8080/openapi.json
```
