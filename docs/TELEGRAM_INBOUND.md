# Iris Telegram inbound — Mahogany

Mahogany is routed via the **pantheon Iris hub** (one bot, multi-product).

| Item | Value |
|------|--------|
| Hub slug | `pantheon` (iris-agent on DO) |
| Repo | `mbugaiov/mahogany` |
| Labels | `mahogany`, `impl-dev` |
| Keywords | `mahogany`, `mahogany-calgary`, `mahogany.calgary`, `mahogany_calgary`, `mahogany life` |
| Explicit | first line `product:mahogany` |

## Smoke

DM the Iris bot (same chat as Pantheon inbound):

```text
product:mahogany
Iris smoke — mahogany inbound wiring
```

Or any message containing `mahogany …`. Expect a GitHub issue link reply.

Host: `systemctl --user status iris-inbound` on deploy@DO.
