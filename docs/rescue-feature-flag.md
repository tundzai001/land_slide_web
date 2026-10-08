# Rescue request switch

Set the following in `backend/.env`, then restart the backend:

```dotenv
RESCUE_REQUEST_ENABLED=false
```

`false` hides the floating request button, mobile request shortcut and request
form on the map, and rejects public request submissions with HTTP 404 before
parsing uploads or writing data. Existing requests and admin workflows remain
available. Set `true` to enable intake again; an unset variable defaults to `true`
for compatibility.

The map reads only this boolean from `/api/public/rescue-config` with caching
disabled. Request controls remain hidden while loading or when configuration
cannot be fetched. No other environment values are exposed. Reload existing map
tabs after changing the setting. Local `.env` files are not committed; configure
the deployment's environment separately.
