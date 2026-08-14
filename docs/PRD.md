# Mahogany — Product Requirements Document

**Product:** Mahogany Life 🌊  
**Slug:** `mahogany`  
**Repo:** [mbugaiov/mahogany](https://github.com/mbugaiov/mahogany)  
**Status:** Greenfield rewrite (migrates legacy `/Users/max/Downloads/project/mahogany` + DO `/root/mahogany`)  
**Owner:** mbugaiov  
**In scope:** Landing · Telegram · Instagram  

---

## 1. Problem

Mahogany (SE Calgary lakeside community) residents, buyers, and Calgary-curious people need a single, always-on information hub. Content already runs unattended on DigitalOcean cron/systemd — **no human in the posting loop**. The legacy tree has no git, no tests, secrets in docs/scripts, stale migration scripts, and shared-droplet risk. We need a factory-ready product that agents can develop, refactor, and maintain (Pantheon pattern).

## 2. Vision

Automated community hub that:

1. Publishes lifestyle / real-estate / local content to **Telegram** `@mahogany_calgary`
2. Cross-posts selected content to **Instagram** `@mahogany.calgary`
3. Funnels discovery via SEO **landing** at `mahogany-calgary.com` → Telegram

Zero manual posting for scheduled jobs. Operators intervene only for secrets, DNS, account recovery, and `human-required` tickets.

## 3. Goals (MVP — this repo)

| ID | Goal | Success signal |
|----|------|----------------|
| G1 | Single public git repo with OpenSpec + factory docs | `mbugaiov/mahogany` public; AGENTS/BRIEF/FACTORY present |
| G2 | Landing served from this repo | Daily stats refresh; STG + prod deploy path documented |
| G3 | Telegram jobs parity (core streams) | News, listings, market, Maya, insider, deals, weather, COL, rentals, HOA on new deploy unit |
| G4 | Instagram automation retained | 3×/day rotate listing/rental/tip/market via scheduled job |
| G5 | Secrets hygiene | No credentials in git; `.env.example` only; DO env files mode 600 |
| G6 | Agent factory (Pantheon pattern) | GitHub Issues + `impl-dev` / `validate-testing`; engines provisioned |
| G7 | Gate + CI | `scripts/gate.sh` (lint + pytest); GitHub Actions PR gate |
| G8 | Cutover | Old Mac launchd + `/root/mahogany` deprecated after STG parity smoke |

## 4. Non-goals (MVP)

- Meta Graph API migration (keep instagrapi until separate ticket; document risk)
- YouTube / Reddit auto-post
- Admin UI / metrics dashboard
- Dedicated droplet split from Pantheon/Colibri (same DO host OK if isolated paths/ports)
- Replacing official Mahogany HOA channels (`@mahoganyhoa`)

## 5. Personas

| Persona | Need |
|---------|------|
| Resident | HOA news, weather/lake, deals, chat (Maya) |
| Buyer / investor | Listings, rentals, market digest |
| Calgary-curious | Landing SEO → join Telegram |
| Operator (you) | Unattended cron; agents maintain code |

## 6. In-scope surfaces

### 6.1 Landing — `mahogany-calgary.com`

- Static SEO page (hero, live-ish stats, CTA → `t.me/mahogany_calgary`)
- Daily job patches stats (active listings, median, gas, etc.) from scrapers
- Schema.org + OG tags
- STG: `http://mahogany.64.225.115.88.nip.io` (nginx) + health `GET /api/build-id` on port **3004**

### 6.2 Telegram — `@mahogany_calgary` (forum group)

| Thread | Content | Schedule (UTC targets; Calgary-aware where noted) |
|--------|---------|-----------------------------------------------------|
| General | Maya chat bot | Always-on |
| News | Scraped news + GPT; market report; weather; cost of living | News ~2h; market daily; weather daily; COL Mon |
| Real Estate | New for-sale listings | Every 4h |
| Rentals | New rentals + weekly report | 4×/day + Mon report |
| Deals | Flipp flyers | Wed + Sat |
| Insider | GPT tips | Tue + Thu |
| HOA | mahoganyhoa.com WP REST | 2×/day Calgary |

**Data sources (canonical):** Kijiji (for-sale + rentals), Google News RSS / local news, Reddit search, Flipp, NRCan, wttr.in, MahoganyHOA WP REST, OpenAI GPT-4o + DALL·E.

### 6.3 Instagram — `@mahogany.calgary`

- Unofficial `instagrapi` session (`ig_session.json` on server, not in git)
- 3×/day (10:00 / 15:00 / 20:00 UTC): rotate listing → tip → rental → tip → listing → market → …
- Caption voice: same “Maya” neighbour tone; bio → Telegram
- Dedup via `ig_seen.json`

## 7. Functional requirements

| ID | Requirement | Priority |
|----|-------------|----------|
| FR-L1 | Landing HTML served over HTTPS at mahogany-calgary.com | P0 |
| FR-L2 | Stats job updates listings/median/gas without full redesign | P0 |
| FR-L3 | CTA links to Telegram; Instagram optional secondary | P0 |
| FR-T1 | Maya responds in General (polling) | P0 |
| FR-T2 | Scheduled jobs post only to configured thread IDs | P0 |
| FR-T3 | Dedup prevents repeat articles/listings | P0 |
| FR-T4 | Failures notify `ADMIN_CHAT_ID` | P1 |
| FR-T5 | `--dry-run` / preview thread supported for news | P1 |
| FR-I1 | Instagram job posts on schedule with rotation | P0 |
| FR-I2 | Session cache; re-login on LoginRequired | P0 |
| FR-I3 | Skip gracefully when no new content | P0 |
| FR-O1 | systemd units under `/opt/mahogany` (new path) | P0 |
| FR-O2 | Env from `/etc/mahogany.env` (secrets never in repo) | P0 |
| FR-O3 | Build id / health for deploy smoke | P0 |
| FR-O4 | Factory tickets `mahogany#N`; labels match Pantheon semantics | P0 |

## 8. Non-functional

| ID | Requirement |
|----|-------------|
| NFR1 | Python 3.11+; typed config; pytest for parsers/dedup/caption helpers |
| NFR2 | No credentials in git, launchd, or markdown |
| NFR3 | Jobs idempotent; min-interval run guards |
| NFR4 | Isolation: never couple to LRM / Pantheon app code; share DO host only with path/port isolation (`/opt/mahogany`, nginx vhost, port 3004) |
| NFR5 | Scrapers tolerate empty results (no crash loops) |
| NFR6 | Instagram ToS risk accepted for MVP; escalate to Graph API if account flags |

## 9. Architecture (target)

```text
                    ┌─────────────────┐
  Scrapers/APIs ──► │ mahogany jobs   │──► Telegram threads
                    │  (Python pkg)   │──► Instagram
                    │  systemd timers │
                    └────────┬────────┘
                             │ stats
                             ▼
                    ┌─────────────────┐
                    │ landing (nginx) │◄── mahogany-calgary.com
                    │ + health :3004  │◄── STG nip.io
                    └─────────────────┘
```

Legacy `/root/mahogany` remains until cutover smoke passes; then disabled.

## 10. Migration plan

1. **Bootstrap** — this repo + factory engines + public GitHub (done in this change set)
2. **Parity** — port jobs; STG deploy to `/opt/mahogany`; dual-run optional (dry-run first)
3. **Cutover** — point timers to new units; pause old `/root/mahogany` + Mac launchd
4. **Deprecate** — archive old folder; remove secrets from SERVER.md; rotate leaked DO/Telegram/IG credentials

## 11. Acceptance (MVP cutover)

- [ ] Public repo + OpenSpec + factory labels
- [ ] Landing STG shows `build-id` match after deploy
- [ ] At least one dry-run news + one listings cycle against preview/STG config
- [ ] Instagram dry-run or staged post documented
- [ ] Old Mac launchd unloaded; old DO units stopped after go-live
- [ ] `gate.sh` green on `main`

## 12. Open questions

| Q | Default for MVP |
|---|-----------------|
| Market report → News vs Real Estate thread? | Keep **News** (legacy code) |
| Economics bot (server-only)? | Defer; ticket later |
| Official IG Graph API? | Defer |
| Dedicated droplet? | Defer |

## 13. Traceability

Canonical OpenSpec: `openspec/specs/mahogany-hub/spec.md`  
Factory runbook: `FACTORY.md`  
Deploy: `docs/DEPLOYMENT.md`
