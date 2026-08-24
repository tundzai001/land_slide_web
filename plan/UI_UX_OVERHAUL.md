# Aitogy Landslide Monitor UI/UX Overhaul

Implementation ledger for the approved UI/UX, Three.js and SEO overhaul.

## Locked decisions

- Aitogy is the masterbrand; Landslide Monitor is the product.
- Teal is the operational palette. Aitogy orange is brand-only; amber/red remain warning/danger.
- The public landing page is semantic HTML with progressive enhancement and one adaptive Three.js story.
- `/` and `/map` are indexable. `/login`, `/management`, `/admin` and legacy aliases are `noindex`.
- Public URL source: `PUBLIC_SITE_URL`, default `https://monitoring.aitogy.com`.
- Existing URLs, REST/WebSocket payloads, role model, database schema, exports and Digital Twin physics remain unchanged.
- Generated files under `frontend/dist` are build artifacts and are never edited by hand.

## Baseline

| Surface | JavaScript | CSS |
|---|---:|---:|
| Landing | 17,986 B | 21,985 B |
| Map | 402,670 B | 144,910 B |
| Management | 415,883 B | 103,651 B |

Pre-existing worktree changes in backend database/runtime files, Pi/admin CSS, `db-manager.js`, management tests and generated `dist` artifacts must be preserved and merged manually.

## Checklist

### 0. Foundation

- [x] Persist decisions, baseline, acceptance criteria and rollout notes.
- [x] Align shared semantic tokens, spacing, radius, focus, touch and z-index scales.
- [x] Correct Map and Management page overrides in the design-system source of truth.

### 1. Brand, shells and SEO

- [x] Preserve and build the official Aitogy logo; add a 1200×630 social image.
- [x] Split semantic `index.html`, indexable `map.html` and private `app.html`.
- [x] Add absolute canonical, OG/Twitter metadata and minimal validated JSON-LD.
- [x] Add `/robots.txt` and `/sitemap.xml`; add `X-Robots-Tag` on private shells.
- [x] Make non-production responses globally `noindex`.

### 2. Landing and story

- [x] Remove React UMD/JSX and keep all copy/CTA usable without JavaScript.
- [x] Implement theme, menu focus handling, auth CTA, reveal and five live-metric states.
- [x] Implement one lazy, render-on-demand Three.js scene with static fallbacks.

### 3. Map Operations

- [x] Remove React station list and all synthetic heat/GNSS/IMU values.
- [x] Normalize timestamps and render reverse-geocode text without `innerHTML`.
- [x] Unify mode/layer/panel state and role-gate privileged actions.
- [x] Lazy-load charts/heat, dispose 3D resources and preserve reconnect/project scope.
- [x] Finish responsive rail/drawer/sheet layout and operational state feedback.

### 4. Management

- [x] Keep all workflows/contracts while completing navigation, responsive and a11y reskin.
- [x] Keep `switchTab()` as the sole desktop/mobile active-state source.
- [x] Complete Projects/Wizard, Database, Pi, Rescue and Users operational states.
- [x] Merge canonical responsive rules and remove dead/unbuilt duplicates.

### 5. Verification

- [x] Clean build and manifest contract; `git diff --check`.
- [x] SEO shell/route tests, JSON-LD parse and asset checks.
- [x] Chromium/Firefox/WebKit UI matrix and keyboard/focus checks.
- [ ] Production smoke has no `pageerror` or `console.error`.
- [ ] Landing Lighthouse mobile ≥90 performance and ≥95 accessibility/SEO.
- [x] Map/Management bundles grow ≤5%; landing local JS/CSS ≤30KB.

Latest production build (`e69d2a6b9a98`): landing 10,166 B JS / 13,596 B CSS;
Map 407,899 B JS / 147,021 B CSS; Management 416,617 B JS / 104,332 B CSS.
Automated verification: 40 responsive Chromium cases, 12 Chromium workflow/story
cases and 24 equivalent Firefox/WebKit cases pass. Reduced-motion behavior remains
implemented in source, but a dedicated automated reduced-motion visual case is still
a release follow-up. Lighthouse and a live production console smoke require a deployed
production URL and are intentionally not marked complete here.

## Release gates

- Merge order: foundation/SEO → landing → Map correctness → Map UI → Management → QA.
- Staging is always `noindex`; production alone publishes canonical and sitemap URLs.
- Google tile licensing/attribution remains a separate production gate; provider changes require an approved licensed URL and attribution.
