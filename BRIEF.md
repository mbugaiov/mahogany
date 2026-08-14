# Mahogany — product brief

> **Isolation:** App repo = `mbugaiov/mahogany`. Never couple to LRM / lab-rm / Bitbucket.
> Engine slug = `mahogany` only. Legacy path `/Users/max/Downloads/project/mahogany` is deprecated after cutover.

## Intent

Unattended community content hub for Mahogany, Calgary:

1. **Landing** SEO funnel → Telegram  
2. **Telegram** forum group `@mahogany_calgary` (Maya + scheduled jobs)  
3. **Instagram** `@mahogany.calgary` scheduled cross-posts  

No human in the posting loop (cron/systemd). Humans only for secrets, DNS, and `human-required` tickets.

## Surfaces

| Surface | Purpose |
|---------|---------|
| Landing | `mahogany-calgary.com` — stats + CTA |
| Telegram | News, Real Estate, Rentals, Deals, Insider, HOA, Maya |
| Instagram | Rotating listing / rental / tip / market |

Full requirements: [`docs/PRD.md`](./docs/PRD.md).

## Tracker

**GitHub Issues only — no Jira.** Labels + flow: [FACTORY.md](./FACTORY.md).

## Design-first rule

1. Athena Mode B charter → `UX_CHARTER_READY` when UI/landing IA changes.
2. Hephaestus implements in **this** repo only.
3. Ship via GitHub PR → `main` → DO STG (`/opt/mahogany`).

## Council

Same seats as Pantheon (Hephaestus, Athena, Themis, Argus, Hermes, Metis, Iris, Plutus). See [FACTORY.md](./FACTORY.md).
