// Single source of truth for the app version displayed inside the
// Monitor. Every component that renders the version (dashboard footer,
// SMART report footer, release-notes modal…) imports from here so a
// version bump only has to be applied once per file lane:
//
//   1. AppImage/lib/version.ts       ← this file
//   2. AppImage/package.json         ← npm/Next.js metadata
//   3. beta_version.txt              ← bash pipeline (build_appimage.sh)
//
// Keep the three in sync on every bump.
export const APP_VERSION = "1.2.5"
