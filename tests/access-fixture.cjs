// An administrator session for components that ask lib/access what the
// profile of the session allows.
const areas = {general: true, apps: true, menux: true, guests: true, node: true, backup: true, logs: true}
const capabilities = {view: true, execute: true, guests: true, backup: true, update: true, terminal: true, admin: true, areas}
const AREAS = Object.keys(areas)
module.exports = {useAccess: () => ({mode: 'password', capabilities}), FULL_ACCESS: capabilities, AREAS,
  withAreas: value => ({...capabilities, ...(value || {}), areas: {...areas, ...((value || {}).areas || {})}})}
