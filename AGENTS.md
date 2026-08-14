# Mahogany — agent notes

Read before coding, reviewing, or testing. Product brief: [`BRIEF.md`](./BRIEF.md). Factory: [`FACTORY.md`](./FACTORY.md). PRD: [`docs/PRD.md`](./docs/PRD.md).

## Stack

| Layer | Technology |
|-------|------------|
| Language | Python 3.11+ |
| Package | `src/mahogany` (jobs + scrapers + telegram + instagram) |
| Landing | `landing/index.html` → nginx |
| Health | FastAPI `:3004` `/api/build-id` |
| Tests | pytest |
| Gate | `./scripts/gate.sh` (ruff + pytest) |
| Spec | OpenSpec `openspec/specs/mahogany-hub/spec.md` |
| CI | GitHub Actions — gate + Themis |
| Deploy | DO `/opt/mahogany` · systemd `mahogany-*` · nginx vhost |
| STG | `http://mahogany.64.225.115.88.nip.io` |
| Tracker | GitHub Issues · slug **`mahogany`** · tickets `mahogany#N` |

## Factory

- Labels / state machine: [`FACTORY.md`](./FACTORY.md)
- Do **not** put `Closes #N` in PR bodies — use `Related: #N`
- Design lock: [`DESIGN.md`](./DESIGN.md)

## Isolation

- Never couple to LRM / RQ-* / Bitbucket lab-rm  
- Ports: **3004** mahogany health (3001 LRM, 3002 Colibri, 3003 Pantheon)  
- Paths: `/opt/mahogany`, `/var/www/mahogany`, `/etc/mahogany.env`  
- Legacy `/root/mahogany` is read-only reference until cutover — do not extend it  

## Secrets

Never commit `.env`, `ig_session.json`, or DO passwords. Use `.env.example` + server `/etc/mahogany.env`.
