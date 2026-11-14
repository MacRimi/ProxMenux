// An administrator session for components that ask lib/access what the
// profile of the session allows.
const capabilities = {view: true, execute: true, guests: true, backup: true, update: true, terminal: true, admin: true}
module.exports = {useAccess: () => ({mode: 'password', capabilities}), FULL_ACCESS: capabilities}
