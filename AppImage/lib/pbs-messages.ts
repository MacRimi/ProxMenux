type Translate = (key: string, params?: Record<string, string | number>) => string

const ERROR_KEYS: Record<string, string> = {
  pbs_config_read: "pbs.errors.configRead", pbs_invalid_config: "pbs.errors.invalidConfig",
  pbs_invalid_field: "pbs.errors.invalidField", pbs_invalid_url: "pbs.errors.invalidUrl",
  pbs_name_required: "pbs.errors.nameRequired", pbs_token_id_format: "pbs.errors.tokenIdFormat",
  pbs_token_secret: "pbs.errors.tokenSecret", pbs_invalid_token_id: "pbs.errors.invalidTokenId",
  pbs_invalid_fingerprint: "pbs.errors.invalidFingerprint", pbs_fingerprint_mismatch: "pbs.errors.fingerprintMismatch",
  pbs_token_rejected: "pbs.errors.tokenRejected", pbs_invalid_response: "pbs.errors.invalidResponse",
  pbs_invalid_json: "pbs.errors.invalidJson", pbs_connect_failed: "pbs.errors.connectFailed",
  pbs_invalid_id: "pbs.errors.invalidId", pbs_invalid_datastores: "pbs.errors.invalidDatastores",
  pbs_username: "pbs.errors.username", pbs_password: "pbs.errors.password",
  pbs_login_rejected: "pbs.errors.loginRejected", pbs_invalid_login: "pbs.errors.invalidLogin",
  pbs_token_create_denied: "pbs.errors.tokenCreateDenied", pbs_invalid_token: "pbs.errors.invalidToken",
  pbs_audit_role_denied: "pbs.errors.auditRoleDenied", pbs_not_found: "pbs.errors.notFound",
  pbs_read_failed: "pbs.errors.readFailed", pbs_invalid_list: "pbs.errors.invalidList",
  pbs_local_unavailable: "pbs.errors.localUnavailable", pbs_auth_required: "pbs.errors.authRequired",
  pbs_save_failed: "pbs.saveFailed", pbs_remove_failed: "pbs.removeFailed",
  pbs_saved_refresh_failed: "pbs.savedRefreshFailed", pbs_removed_refresh_failed: "pbs.removedRefreshFailed",
  pbs_datastore_offline: "pbs.errors.datastoreOffline", pbs_datastore_unavailable: "pbs.errors.datastoreUnavailable",
}

// Accept structured codes, never arbitrary error text as a translation key.
function pbsErrorTranslation(error: unknown): { key: string; params?: { count: number } } | null {
  const body = error && typeof error === "object" && "body" in error ? error.body : error
  if (!body || typeof body !== "object" || !("code" in body) || typeof body.code !== "string") return null
  if (body.code === "pbs_connection_limit") {
    const params = "params" in body ? body.params : null
    const count = params && typeof params === "object" && "count" in params ? params.count : null
    return typeof count === "number" && Number.isSafeInteger(count) && count > 0
      ? { key: "pbs.errors.connectionLimit", params: { count } } : null
  }
  return Object.prototype.hasOwnProperty.call(ERROR_KEYS, body.code) ? { key: ERROR_KEYS[body.code] } : null
}

export function pbsIsKnownError(error: unknown): boolean {
  return pbsErrorTranslation(error) !== null
}

export function pbsErrorText(error: unknown, t: Translate, fallback = "pbs.loadFailed"): string {
  const translated = pbsErrorTranslation(error)
  return translated ? t(translated.key, translated.params) : t(fallback)
}

export function pbsDiagnostic(error: unknown): string | undefined {
  if (!error || typeof error !== "object") return undefined
  const body = "body" in error ? error.body : null
  if (body && typeof body === "object" && "error" in body && typeof body.error === "string") return body.error
  return "message" in error && typeof error.message === "string" ? error.message : undefined
}

const TASK_TYPES: Record<string, string> = {
  backup: "backup", reader: "restore", verify: "verify", verificationjob: "verify",
  verify_group: "verifyGroup", verify_snapshot: "verifySnapshot", prune: "prune", prunejob: "prune",
  garbage_collection: "garbageCollection", sync: "sync", syncjob: "sync", aptupdate: "updateCheck",
  termproxy: "terminal", dircreate: "createDatastore", "create-datastore": "createDatastore",
}
export function pbsTaskType(type: string | undefined, t: Translate): string {
  return type && Object.prototype.hasOwnProperty.call(TASK_TYPES, type)
    ? t(`pbs.taskTypes.${TASK_TYPES[type]}`) : t("pbs.taskTypes.other", { type: type || "—" })
}

export function pbsResultText(status: string | undefined, t: Translate): string {
  if (!status || status === "unknown") return t("pbs.states.unknown")
  if (status.toLowerCase() === "ok") return t("pbs.states.ok")
  const warnings = /^WARNINGS:\s*(\d+)\s*$/i.exec(status)
  if (warnings && Number.isSafeInteger(Number(warnings[1]))) return t("pbs.states.warnings", { count: Number(warnings[1]) })
  return /^warn/i.test(status) ? t("pbs.states.warning") : t("pbs.states.error")
}

export function pbsServiceState(state: string, t: Translate): string {
  const known = ["active", "inactive", "failed", "activating", "deactivating", "unknown"]
  return t(`pbs.serviceStates.${known.includes(state) ? state : "unknown"}`)
}

export function formatPBSDuration(seconds: number, t: Translate): string {
  if (!Number.isFinite(seconds) || seconds < 0) return "—"
  const unit = (key: string, count: number) => t(`pbs.durationUnits.${key}`, { count })
  if (seconds < 60) return unit("seconds", Math.round(seconds))
  const minutes = Math.floor(seconds / 60)
  if (minutes < 60) return `${unit("minutes", minutes)} ${unit("seconds", Math.round(seconds % 60))}`
  const hours = Math.floor(minutes / 60)
  return hours < 24 ? `${unit("hours", hours)} ${unit("minutes", minutes % 60)}`
    : `${unit("days", Math.floor(hours / 24))} ${unit("hours", hours % 24)}`
}
