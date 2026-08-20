# Aitogy Landslide Monitor — Design System

## Product direction

**Teal Operations** for a public-safety monitoring product: calm, precise and data-first. Red and amber communicate operational risk only. Decorative neon, gold luxury styling, structural emoji and layout-shifting hover effects are forbidden.

## Semantic color tokens

| Role | Light | Dark |
|---|---:|---:|
| Background | `#F4F8F7` | `#071A1C` |
| Surface | `#FFFFFF` | `#0B2427` |
| Elevated surface | `#EEF5F4` | `#123034` |
| Foreground | `#0F2A2E` | `#F0FDFA` |
| Secondary text | `#526B70` | `#A7C1BE` |
| Muted text | `#70878B` | `#83A09D` |
| Border | `#D5E3E1` | `#29494C` |
| Primary | `#0F766E` | `#2DD4BF` |
| Interactive | `#0D9488` | `#5EEAD4` |
| Info | `#2563EB` | `#60A5FA` |
| Success | `#15803D` | `#4ADE80` |
| Warning | `#B45309` | `#FBBF24` |
| Danger | `#B91C1C` | `#FB7185` |

## Typography and density

- Interface: `DM Sans`, with system sans-serif fallback.
- Data and timestamps: system monospace with tabular numerals.
- Type scale: 12, 14, 16, 18, 24, 32px. Body line-height: 1.5–1.65.
- Spacing: 4/8px rhythm. Core gaps: 8, 12, 16, 24, 32px.
- Radius: 8px controls, 12px compact cards, 16px panels, 22px hero surfaces.
- Motion: 150–300ms and only for state/continuity. Respect `prefers-reduced-motion`.

## Interaction contract

- Touch targets are at least 44×44px; checkbox/radio glyphs are 18–20px inside a larger label target.
- Every icon-only control has an accessible name and visible focus state.
- Loading actions are disabled, show progress and restore in `finally`.
- Empty, loading, stale, offline and error are distinct states with recovery actions.
- Status never relies on color alone.
- Drawers and modals close with Escape, trap focus while open and restore focus to the trigger.

## Page defaults

- Landing/Login: spacious, trust-first, responsive, light by default with dark available.
- Map: full-viewport operational workspace with compact floating panels and mobile bottom navigation.
- Management: dense light-first operations console; retain the approved information architecture.

Page rules in `pages/` override this file only where explicitly stated.
