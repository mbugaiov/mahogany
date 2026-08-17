# Mahogany Life 🌊

Automated community hub for **Mahogany, Calgary** — landing + Telegram + Instagram.

- **PRD:** [docs/PRD.md](./docs/PRD.md)
- **Brief:** [BRIEF.md](./BRIEF.md)
- **Factory (GitHub Issues, no Jira):** [FACTORY.md](./FACTORY.md)
- **Deploy:** [docs/DEPLOYMENT.md](./docs/DEPLOYMENT.md)
- **OpenSpec:** [openspec/specs/mahogany-hub/spec.md](./openspec/specs/mahogany-hub/spec.md)
- **GitHub:** https://github.com/mbugaiov/mahogany
- **Factory slug:** `mahogany`

## Surfaces

| Surface | Handle / URL |
|---------|----------------|
| Landing | https://mahogany-calgary.com |
| Telegram | [@mahogany_calgary](https://t.me/mahogany_calgary) |
| Instagram | [@mahogany.calgary](https://www.instagram.com/mahogany.calgary/) |
| STG | http://mahogany.64.225.115.88.nip.io |

## Stack

| Layer | Technology |
|-------|------------|
| Language | Python 3.11+ |
| Jobs | systemd timers on DigitalOcean |
| Landing | Static HTML (nginx) |
| Health | FastAPI sidecar port **3004** `/api/build-id` |
| Tests / gate | pytest · ruff · `./scripts/gate.sh` |
| CI | GitHub Actions (gate + Themis) |

**Themis:** CI `review (Themis)` floats `themis-agent` **main** (shared `review-rules/`).
Local `.themis-agent/` may be stale (pinned via `ensure_themis_agent.sh` for isolation).
`gate.sh` prints the builder tip (path + short SHA) when present; offline local runs may
skip the builder selftest, but **CI fail-closed** — missing checkout/builder exits non-zero.
| Tracker | GitHub Issues only |

Agent notes: [`AGENTS.md`](./AGENTS.md).

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env   # fill locally — never commit
./scripts/gate.sh
```

## Migration

This repo **replaces** the legacy tree at `/Users/max/Downloads/project/mahogany` and DO `/root/mahogany`. Cutover steps: [docs/DEPLOYMENT.md](./docs/DEPLOYMENT.md) § Cutover.
