# Aitogy Monitoring — Design System

## Product direction

Teal Operations for a public-safety monitoring product: calm, precise and data-first. Aitogy is the masterbrand; Monitoring is the product name in every header, login screen and footer. Monitoring covers dam, structural, geotechnical and environmental monitoring. “Bản đồ” is a destination, not a brand. Red and amber communicate operational risk only. Aitogy orange is brand-only.

## Semantic tokens

| Role | Light | Dark |
|---|---:|---:|
| Background | `#F5F7F8` | `#071A1C` |
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
- Spacing follows 4/8px rhythm. Radius scale is 6/8/12/16px.
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

## Operations interface refinement

- Use solid surfaces, short shadows and restrained teal accents. Navigation, forms and tables carry the hierarchy; no neon, decorative gradients or hover tilt in operational workspaces.
- Component tokens: `--control-radius`, `--panel-radius`, `--control-height`, `--control-focus`, `--panel-shadow`, `--overlay-shadow`, `--motion-control`. These resolve through existing semantic colors and theme surfaces.
- Management uses a labeled 248px desktop sidebar, a direct Map link and compact data tables. Phones use bottom navigation and labeled record cards; the main workspace scrolls independently beneath fixed controls.
- Map uses solid toolbar and station/detail panels. Station names wrap, status keeps text and color, and the legend stays clear of open panels.
- Login uses concise capability descriptions. Successful direct login returns to Map. An explicit authorized return destination remains supported.
- Keep actual data, permissions, chart behavior and station configuration flows unchanged.

## Workspace visual hierarchy

- Graphite navigation chrome (`--workspace-chrome`) stays distinct from the light or dark data canvas. Teal remains the action color; pale mint identifies the account action on Map.
- Management project directory uses wide rows: project identity, description/location, actual station count, then actions. Summary totals derive from the loaded project dataset. Mobile stacks each row without changing keyboard order.
- Map toolbar spans the viewport. The station directory docks beneath it on desktop; detail panels preserve readable station names and independent scrolling.
- Public portal gives Map the larger, dark primary entry and Dashboard a white secondary entry. No fabricated telemetry, illustrations or decorative effects.

## Map and chart controls

- Basemap picker offers Google roadmap, satellite, hybrid and terrain through the existing Leaflet tile integration. Save the choice locally; theme switches preserve it. Keep position, zoom and data overlays unchanged. Tile errors remain visible in the picker.
- Chart workspace filters by measurement, expands/collapses, refreshes bypassing history cache, and exports loaded chart values as CSV or the rendered plot as PNG. CSV timestamps are ISO UTC; missing values stay empty.
- Each series exposes valid count, minimum, maximum and average. Tooltips retain full dates. Rain and GNSS start at zero; water and other measurements auto-scale. Do not treat historical extrema as risk thresholds.
- Preserve existing per-range API sample limits and show the loaded count. No new chart dependency or history API is introduced.
