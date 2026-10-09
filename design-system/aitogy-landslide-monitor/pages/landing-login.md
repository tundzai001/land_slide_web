# Landing and Login overrides

- Landing is an operations portal with prominent Dashboard (`/management`) and Map (`/map`) destinations. Login opens `/login?return_to=%2Fmap` and returns to Map after authentication. Direct login defaults to `/map`; explicit return destinations remain supported.
- Introduction and the 3D sensor story live on `/about`. Landing uses a an asymmetric access grid, larger headings, graphite Map entry, white Dashboard entry and existing teal tokens; no decorative 3D or marketing scroll effects.
- Live metrics show freshness plus loading, empty and retry states.
- Login errors stay adjacent to the form and focus the first invalid input.
- Marketing motion is subtle and fully disabled under reduced-motion.
- At mobile widths, content order is brand → outcome → primary action → evidence.
