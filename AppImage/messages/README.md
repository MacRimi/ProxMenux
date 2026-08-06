# Monitor dashboard translations

The ProxMenux Monitor dashboard uses a small client-side i18n layer.

- English (`en`) is the source language and the fallback.
- Slovak (`sk`) is complete.
- Spanish, French, German, Italian and Portuguese are registered as
  community translation targets and currently fall back to English.

To add or improve a translation, copy the matching keys from
`messages/en/common.json` into your locale's `common.json` file and
translate only the values. Keep placeholders such as `{uptime}` unchanged.
