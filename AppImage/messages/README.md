# Monitor dashboard translations

The ProxMenux Monitor dashboard uses a small client-side i18n layer.

- English (`en`) is the source language and the runtime fallback.
- Eight locales are shipped and fully populated end-to-end: `en`, `de`, `es`, `fr`, `it`, `pt`, `sk`, `sv`. Non-English catalogs started from an automated bootstrap and are being polished as native speakers pass through them.

To improve a translation, edit the values in your locale's `common.json` — keep placeholders such as `{uptime}`, `{vmid}` or `{count}` unchanged, and don't translate brand or product names (`ProxMenux Monitor`, `Proxmox Backup Server`, `Secure Gateway`, `Tailscale`, etc.). Missing keys fall back to English at runtime, so a partial refresh is always safe to merge.

To add a new locale, see [§11 → Adding a new locale](../../CONTRIBUTING.md#adding-a-new-locale) in the Contributing Guide.
