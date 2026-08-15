# Mahogany — Deployment

## Targets

| Item | Value |
|------|--------|
| Host | `64.225.115.88` |
| App path | `/opt/mahogany` (deploy-owned) |
| Data | `/var/lib/mahogany` |
| Landing | `/var/www/mahogany` |
| Env | `/etc/mahogany.env` (copied from legacy — **not rotated yet**) |
| Health | port **3004** · `GET /api/build-id` |
| STG URL | http://mahogany.64.225.115.88.nip.io |
| Prod landing | https://mahogany-calgary.com |
| systemd | `mahogany-health`, `mahogany-groupbot`, timers |

**Note:** Bots/jobs and health run from `/opt/mahogany` (Deploy STG). Prod promote only ships the **public landing** to `/var/www/mahogany`.

## Pipeline (agent-owned)

```
PR → Themis + gate → auto-merge → Deploy STG → Deploy Prod
```

| Workflow | Trigger | Purpose |
|----------|---------|---------|
| `.github/workflows/pr.yml` | PR → `main` | gate + Themis review/isolation + auto-merge → dispatch Deploy STG |
| `.github/workflows/deploy-stg.yml` | push `main` + `workflow_dispatch` | **STG** (`/opt/mahogany` + smoke) then **Prod** landing (`/var/www/mahogany` + smoke) in the same workflow |
| `.github/workflows/deploy-prod.yml` | `workflow_dispatch` (+ optional `workflow_run`) | Manual / backup landing-only promote |

Chain: `PR → Themis → auto-merge → Deploy STG job → Deploy Prod job` (same Actions run).

Repo secrets: `CURSOR_API_KEY`, `DO_DEPLOY_HOST`, `DO_DEPLOY_USER`, `DO_SSH_KEY`, `DO_KNOWN_HOSTS`  
Vars: `STG_URL=http://mahogany.64.225.115.88.nip.io`, `PROD_URL=https://mahogany-calgary.com`  
Local SSH: place key + known_hosts under **`mahogany/.secrets/`** (gitignored) or set `DO_SSH_KEY_FILE` / `DO_KNOWN_HOSTS_FILE` — do not hardcode sibling product paths.

Prod HTML smoke is fail-closed. If Cloudflare lags, set `ALLOW_PROD_CDN_STALE=1` only as a temporary override.
## Local commands

```bash
./scripts/gate.sh
bash scripts/deploy_stg.sh
bash scripts/check_stg_build.sh
bash scripts/deploy_prod.sh      # promote landing after STG
bash scripts/check_prod_build.sh
```

Manual Actions:

```bash
gh workflow run deploy-stg.yml --ref main
gh workflow run deploy-prod.yml --ref main   # or after STG via workflow_run
```

One-time root bootstrap (already applied on droplet): `scripts/bootstrap_droplet.sh`

## Cutover status

**Done (2026-08-14):** systemd units → `/opt/mahogany` CLI; legacy tree moved to `/root/mahogany.pre-cutover`; Mac `com.mahogany.*` launchd unloaded.

### Remaining optional

- Port `economics` job or keep timer disabled
- Delete `/root/mahogany.pre-cutover` after a soak period
- Archive local `/Users/max/Downloads/project/mahogany`
