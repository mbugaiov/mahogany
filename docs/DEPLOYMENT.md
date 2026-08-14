# Mahogany — Deployment

## Targets

| Item | Value |
|------|--------|
| Host | `64.225.115.88` (shared DO — isolated paths) |
| App path | `/opt/mahogany` |
| Landing | `/var/www/mahogany` |
| Env | `/etc/mahogany.env` (mode 600) |
| Health | `http://127.0.0.1:3004/api/build-id` |
| STG URL | `http://mahogany.64.225.115.88.nip.io` |
| Prod landing | `https://mahogany-calgary.com` |
| systemd | `mahogany-*.service` / `mahogany-*.timer` |

Ports: **3004** only for mahogany health (3001 LRM, 3002 Colibri, 3003 Pantheon).

## Local gate

```bash
./scripts/gate.sh
```

## Secrets (names only)

See `.env.example`. Never commit values. On server, write `/etc/mahogany.env` from operator secrets store.

## Cutover (from legacy)

1. Deploy this repo to `/opt/mahogany` + sync `landing/` → `/var/www/mahogany`
2. Install new systemd units from `deploy/systemd/`
3. Point env at same Telegram/IG credentials (rotated if leaked in old `SERVER.md`)
4. Run dry-run jobs; compare thread output
5. Stop legacy units under `/root/mahogany` and unload Mac `com.mahogany.*` launchd
6. Archive old local folder

## Dual-run note

Until cutover, prefer **dry-run / preview thread** on new code so DO cron on legacy keeps production posts.
