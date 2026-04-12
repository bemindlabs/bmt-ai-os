## BMT AI OS v2026.4.12

**Release date:** 2026-04-12

### Highlights

- **OAuth 2.0 provider authentication** — three credential types (API key, OAuth, bearer token) with PKCE flow, auto-refresh, and round-robin key selection
- **AI DLC & Custom OS Builder** — package registry, build profiles, 11 API endpoints, TUI wizard, dashboard image builder with hardware selector
- **GitHub Actions CI** — lint, test, trivy, benchmark pipeline; Pi 5 flash script and first-boot init
- **AI Workspace complete** — persona knowledge vaults, Obsidian editor, IDE terminal, multi-provider AI coding, model A/B comparison
- **All 23 epics complete** — 177 stories, 965 points delivered

### Added

- OAuth 2.0 provider auth backend with PKCE, token refresh, and credential type selector
- Provider OAuth dashboard UI: auth config, key manager, wizard step, callback page
- DLC package registry (`bmt_ai_os/dlc/`) with 40+ AI tool packages and build profiles
- Image builder API (11 endpoints: targets, packages, profiles, builds)
- Image builder dashboard page with hardware selector and build flow wizard
- TUI image builder wizard (`bmt_ai_os dlc configure`, `build`, `list-packages`)
- `build.sh --profile` for DLC custom image builds
- GitHub Actions CI workflow (`.github/workflows/ci.yml`)
- Pi 5 flash script (`scripts/flash-pi5.sh`) and first-boot init scripts
- SSH WebSocket proxy, terminal SSH mode, fleet connect, key management, multi-tab
- Provider setup wizard, model catalog, health dashboard, auto-discovery
- Multi-credential profiles per provider with load balancing and fallback chain
- Monaco code editor with AI coding workflow: diff preview, slash commands, tool use, multi-file edit, git integration
- Model A/B comparison in editor
- Persona knowledge vaults with Obsidian-compatible note editor and vault graph
- Browser terminal emulator with WebSocket backend
- 3-panel resizable AI workspace layout
- Fleet dashboard with device grid
- Training studio with live metrics and TensorBoard embed
- RAG knowledge base manager with collection, ingest, search, and graph tabs
- Multi-agent management page
- Global error boundary and route error pages
- Notification center and theme toggle

### Changed

- Merged Providers into Models as unified Models & Providers page
- Split `api.ts` into 13 domain-specific API modules
- Modernized dashboard pages: editor, training, chat, layout, fleet, overview, logs, agents
- Auto-connect local terminal on mount with improved reconnect handling
- DLC module added to Dockerfile COPY layers

### Fixed

- Cloud providers visible in AI panel even without API keys configured
- WebSocket URLs use browser hostname instead of Docker-internal name
- Missing API exports for persona, knowledge, files, fleet, agents
- Model manager 404 (use `/v1/models` endpoint, add `/api/pull` proxy)
- Missing FallbackChain import and API functions
- Button render prop issues on training page
- Duplicate fleet nav entry removed

### Stats

- **177 stories** across 23 epics (965 points, 100% complete)
- **1900+ unit tests**, 28 e2e tests, 31 security tests, 12 load tests
- **175 files changed**, +33,141 / -1,582 lines since v2026.4.10
- **Epics completed this release:** EPIC-10b through EPIC-23 (14 epics)
