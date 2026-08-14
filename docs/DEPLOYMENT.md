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
| Prod landing | https://mahogany-calgary.com (legacy nginx vhost still serves `/var/www/mahogany`) |
| systemd (new) | `mahogany-health` |
| systemd (legacy) | still `/root/mahogany` — **left running** until cutover |

## Pipelines (GitHub Actions)

| Workflow | Trigger | Purpose |
|----------|---------|---------|
| `.github/workflows/pr.yml` | PR / push | ruff + pytest gate |
| `.github/workflows/deploy-stg.yml` | push `main` + `workflow_dispatch` | rsync → `/opt/mahogany`, restart health, smoke STG |

Repo secrets (already wired): `DO_DEPLOY_HOST`, `DO_DEPLOY_USER`, `DO_SSH_KEY`, `DO_KNOWN_HOSTS`  
Var: `STG_URL=http://mahogany.64.225.115.88.nip.io`

## Local commands

```bash
./scripts/gate.sh
bash scripts/deploy_stg.sh
bash scripts/check_stg_build.sh
```

One-time root bootstrap (already applied on droplet): `scripts/bootstrap_droplet.sh`

## Cutover status

**Done (2026-08-14):** systemd units → `/opt/mahogany` CLI; legacy tree moved to `/root/mahogany.pre-cutover`; Mac `com.mahogany.*` launchd unloaded.

### Remaining optional

- Rotate secrets (mahogany#3)
- Port `economics` job or keep timer disabled
- Delete `/root/mahogany.pre-cutover` after a soak period
- Archive local `/Users/max/Downloads/project/mahogany`

## Cutover (historical)

1. Point job timers at `/opt/mahogany` CLI  
2. Stop legacy `/root/mahogany` units  
3. Unload Mac `com.mahogany.*`  
4. Rotate secrets when you choose (ticket #3)
