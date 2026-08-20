# UI/UX Master Plan — Landslide Monitor

## Direction

- Product language: **Teal Operations** — calm slate/teal surfaces; red and amber are reserved for risk and warning states.
- Default theme: **light** on every route. Users can switch to dark and the choice persists in `localStorage.theme`.
- Scope: Landing, Login and Map Operations receive the main redesign. Management keeps its approved layout and receives regression hardening only.
- Compatibility: preserve URLs, backend APIs, roles, export formats, `AdminManager`, `LegacyTemplates`, map globals and `window.themeManager`.
- Delivery: foundation → public surfaces → map → Management hardening → production QA, with a tested commit for each completed stage.

## Implementation checklist

- [ ] Shared semantic tokens, theme controller and component states
- [ ] Landing and Login responsive/light/dark polish
- [ ] Map shell, station navigation, detail panels, alerts, analysis, rescue and 3D polish
- [ ] Split oversized Map modules at real feature boundaries
- [ ] Management theme/accessibility/loading regression pass
- [ ] Production build, Playwright matrix, backend contracts and live smoke checks

## Acceptance criteria

- No horizontal overflow at 320, 375, 390, 768, 1024, 1440 and 1920px, including 844×390 landscape.
- Interactive targets are at least 44×44px; checkbox/radio glyphs remain 18–20px.
- Light is the first-run default; light/dark selection persists across all routes.
- Loading actions disable correctly and always restore on success, timeout or error.
- Online, stale, offline, warning and critical states include text/icon semantics, not color alone.
- Keyboard focus is visible; drawers/modals support Escape and restore focus.
- Reduced motion and 200% text zoom remain usable.
- No structural emoji icons, no happy-path console errors and no production bundle growth above 5%.

## Out of scope

- Backend schema/API changes, export-format changes and a framework rewrite.
- Redesigning approved Management information architecture without a concrete defect.
