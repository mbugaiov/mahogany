# Mahogany factory — GitHub Issues (no Jira)

Backlog = **GitHub Issues** on [`mbugaiov/mahogany`](https://github.com/mbugaiov/mahogany).

Hephaestus / Athena / Argus use engine slug **`mahogany`**. App commits only in this repo.

**Tech stack:** [`AGENTS.md`](./AGENTS.md) § Stack · `docs/PRD.md`.

## Portfolio wake (Kairos)

Default campus path: **Kairos** polls this repo’s Issues → wakes Hephaestus(`mahogany`) **oneshot** → drain → idle → sleep. Do not keep a permanent `dev-loop.sh mahogany` under Kairos. Iris only creates tickets; it does not arm the forge.

## Council involvement

| Seat | When | Required signal |
|------|------|-----------------|
| **Hermes** | `ba-spec-first` / `impl-ba` | `BA_SPEC_READY` |
| **Athena** | `ux-charter-first` / landing IA | `UX_CHARTER_READY` |
| **Hephaestus** | `impl-dev` | Branch → gate → PR → STG → handoff |
| **Themis** | Every PR | `review (Themis)` + `isolation (Themis)` green; Risks/Nits disposed before auto-merge |
| **Argus** | After handoff | STG smoke → ledger → `github_close_issue` |

## Labels

| Label | Owner | Meaning |
|-------|--------|---------|
| `impl-dev` | Hephaestus | Ready to implement |
| `impl-ba` | Hermes | BA owns slice |
| `ba-spec-first` | Hermes → Hephaestus | Wait for `BA_SPEC_READY` |
| `impl-ux` | Athena | UX owns slice |
| `ux-charter-first` | Athena → Hephaestus | Wait for `UX_CHARTER_READY` |
| `needs-ux-pass` | Athena | Mode A polish |
| `validate-testing` | Argus | STG retest |
| `done` | Argus | Closed after PASS |
| `mahogany` | all | Product isolation |
| `infra` | Hephaestus (+ human) | Gate / CI / DO |
| `human-required` | Human | Droplet, DNS, secrets, IG 2FA |
| `factory-pause` | Human | Stop agents |

## Label state machine

```text
[open + impl-dev] ──pickup──► Hephaestus
       │
       ├─(ba-spec-first)──► Hermes → BA_SPEC_READY
       ├─(ux-charter-first)──► Athena → UX_CHARTER_READY
       ▼
  gate → PR → merge → STG buildId
       ▼
  post_github_handoff ──► −impl-dev +validate-testing
       ▼
  Argus ── PASS → close +done
       └── FAIL → confirmed-defect + QA RETURN → impl-dev
```

## Agent start (mandatory)

Announce in Cursor chat **and** GitHub issue:

```markdown
### Hephaestus started
**Ticket:** mahogany#N
**Goal:** …
```

## Isolation

Never LRM / Pantheon app coupling. Shared DO host OK with path/port isolation only.
