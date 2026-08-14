# UX charter — mahogany#9

**Ticket:** mahogany#9  
**Sentinel:** `UX_CHARTER_READY`  
**Mode:** B (charter before implement)

## Problem

Landing reads as generic gradient marketing + Inter; posts often fall back to **AI-generated houses**, which feels fake for a real neighbourhood hub.

## Direction

**Lakeside neighbour, not realtor brochure.** Brand **Mahogany Life** is the hero signal. Real water / real homes.

## Landing (first viewport)

| Element | Spec |
|---------|------|
| Composition | One full-bleed hero plane (photo), not a dashboard |
| Brand | “Mahogany Life” dominant wordmark |
| Headline | One line only |
| Support | One short sentence |
| CTA | Single primary → Telegram `t.me/mahogany_calgary` |
| Image | Edge-to-edge lake/community photo (not abstract gradient alone) |
| Forbidden in hero | Cards, stat strips, schedule grids, floating badges |

Stats live **below** the fold. Secondary sections: what you get in Telegram, then market snapshot with `data-stat-*` hooks for the daily job.

## Motion (ship ≥2)

1. Hero brand/copy fade-up on load  
2. Slow Ken-Burns / scale on hero photo  
3. CTA soft lift on hover  

## Typography & colour

- Display: Fraunces (or keep Playfair) — expressive, not Inter  
- Body: Manrope  
- Tokens: lake `#1a6b8a`, deep `#0d3d52`, gold `#c9a84c`, mist `#e8f1f4`, ink `#1c2b35`  
- Avoid purple gradients and cream/terracotta newspaper looks  

## Posts architecture

| Content | Image rule |
|---------|------------|
| For-sale / rental | **Only** Kijiji (or live) listing photo — skip post if missing |
| Market / tip | Prefer a **real** active listing photo from Mahogany scrape |
| News | Prefer article image; never DALL·E a synthetic house for realestate pillar |

No DALL·E prompts that invent homes in Mahogany.

## Acceptance

- [x] Hero passes brand test without nav  
- [x] Mobile + desktop load cleanly  
- [x] Landing stats still patchable (`data-stat-*`)  
- [x] IG listing/rental never uploads AI homes  
- [x] Gate green  

**UX_CHARTER_READY**

Athena Mode A polish can follow on the same feature branch if needed.
