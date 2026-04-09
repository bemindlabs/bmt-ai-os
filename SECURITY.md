# Security Policy

## Supported Versions

| Version | Supported          |
|---------|--------------------|
| main    | :white_check_mark: |

## Reporting a Vulnerability

**Do not open a public GitHub issue for security vulnerabilities.**

Instead, please email **security@bemind.tech** with:

- Description of the vulnerability
- Steps to reproduce
- Potential impact
- Suggested fix (if any)

We will acknowledge receipt within 48 hours and provide a detailed response within 7 days.

## Scope

Security issues in the following areas are in scope:

- Container isolation and escape
- Secrets management (API keys, credentials)
- Network exposure of services (Ollama, ChromaDB, Dashboard)
- Authentication bypass on dashboard or API endpoints
- Supply chain risks in Buildroot packages or Docker images
- NPU/GPU driver privilege escalation

## Out of Scope

- Vulnerabilities in upstream dependencies (report to the upstream project)
- Denial of service on local-only services
- Issues requiring physical access to the device

## Disclosure Policy

We follow coordinated disclosure. We will credit reporters in the security advisory unless they prefer to remain anonymous.
