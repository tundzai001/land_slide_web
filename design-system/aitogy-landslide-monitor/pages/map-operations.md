# Map Operations overrides

- Full-viewport operational workspace; never use a marketing hero or CTA layout.
- At ≥1440px: collapsible 320–360px station rail, map center, 380–440px context panel.
- At 1024–1439px: map-first workspace with overlay rail/detail drawers.
- At ≤900px: compact top bar, four-item bottom navigation and only one sheet/workspace open at a time.
- Status/layer controls use independent state. Loading, empty, stale, disconnected, API and tile errors are distinct and recoverable.
- Prefer static status changes and short interaction transitions; no ambient blinking or decorative glow.
- Chart data is teal; warning/danger colors are thresholds only; missing values remain gaps/null.
