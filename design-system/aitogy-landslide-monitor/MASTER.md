# Aitogy Monitoring — Design System

## Product direction

Teal Operations for a public-safety monitoring product: calm, precise and data-first. Aitogy is the masterbrand; Monitoring is the product name in every header, login screen and footer. Monitoring covers dam, structural, geotechnical and environmental monitoring. “Bản đồ” is a destination, not a brand. Red and amber communicate operational risk only. Aitogy orange is brand-only.

## Semantic tokens

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
| Brand orange | `#FF6B00` | `#FF7A1A` |

## Typography, density and motion

- Interface: DM Sans with system sans-serif fallback. Data/timestamps use system monospace and tabular numerals.
- Type scale: 12, 14, 16, 18, 24, 32px; body line-height 1.5–1.65. Mobile body is 16px; metadata never below 12px.
- Spacing follows 4/8px rhythm. Radius scale is 8/12/16/22px.
- Touch targets are at least 44×44px and focus rings are 3px with WCAG AA contrast.
- Landing may use exactly one complex scroll-linked story. Other motion is 150–300ms, limited to transform/opacity/interaction state and disabled under reduced motion.
- Use named z-index tokens; do not introduce arbitrary high values.

## Interaction contract

- Every icon-only control has an accessible name. Status always has text/icon in addition to color.
- Loading actions are disabled, show progress and restore in `finally`.
- Empty, loading, stale, offline and error are distinct states with recovery actions.
- Drawers and modals close with Escape, trap focus while open and restore focus to the trigger.

## Page defaults

- Landing/Login: spacious, trust-first, light by default with dark available.
- Map: full-viewport operational workspace with compact panels and mobile bottom navigation.
- Management: dense light-first operations console; preserve approved IA, permissions and workflows while allowing a full presentation reskin.
