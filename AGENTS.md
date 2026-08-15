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
| CI | GitHub Actions — **gate + review (Themis) + isolation (Themis) + auto-merge** |
| Deploy | **STG** → `/opt/mahogany` then **Prod** landing → `/var/www/mahogany` |
| STG | `http://mahogany.64.225.115.88.nip.io` |
| Prod | `https://mahogany-calgary.com` (landing promote after STG) |
| Tracker | GitHub Issues · slug **`mahogany`** · tickets `mahogany#N` |

## Factory

- Labels / state machine: [`FACTORY.md`](./FACTORY.md)
- Do **not** put `Closes #N` in PR bodies — use `Related: #N`
- Design lock: [`DESIGN.md`](./DESIGN.md)
- **Themis is mandatory** on every PR (same as Pantheon): blocking review + isolation; auto-merge only after Risks/Nits disposed

## Isolation

- Never couple to LRM / RQ-* / Bitbucket lab-rm  
- Ports: **3004** mahogany health (3001 LRM, 3002 Colibri, 3003 Pantheon)  
- Paths: `/opt/mahogany`, `/var/www/mahogany`, `/etc/mahogany.env`  
- Legacy archive: `/root/mahogany.pre-cutover` / local `mahogany.pre-cutover` — do not extend 

## Secrets

Never commit `.env`, `ig_session.json`, or DO passwords. Use `.env.example` + server `/etc/mahogany.env`.
