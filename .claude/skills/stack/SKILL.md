---
name: stack
description: Manage the AI stack (start, stop, status, test)
argument-hint: "up|down|ps|test|health"
user-invocable: true
allowed-tools: "Bash Read"
---

# AI Stack Management

Manage the BMT AI OS Docker stack.

## Commands

Parse `$ARGUMENTS` to determine action:

- **up**: `docker compose -f bmt_ai_os/ai-stack/docker-compose.yml up -d`
- **down**: `docker compose -f bmt_ai_os/ai-stack/docker-compose.yml down`
- **ps**: `docker compose -f bmt_ai_os/ai-stack/docker-compose.yml ps`
- **test**: Run functional tests (health endpoints, inference, vector query)
- **health**: Check all service health endpoints

## Current Status

!`docker compose -f bmt_ai_os/ai-stack/docker-compose.yml ps --format "{{.Name}}: {{.Status}}" 2>/dev/null || echo "Stack not running"`
