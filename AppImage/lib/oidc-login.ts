import { getApiUrl } from "./api-config"

// The fragment carries a browser-bound, single-use exchange code, never a JWT.
export async function completeOIDCLogin(): Promise<void> {
  const fragment = new URLSearchParams(window.location.hash.slice(1))
  const code = fragment.get("oidc_code")
  if (!code && !fragment.has("oidc_error")) return
  window.history.replaceState(null, "", window.location.pathname + window.location.search)
  try {
    if (!code) throw new Error("OIDC sign-in failed")
    const response = await fetch(getApiUrl("/api/auth/oidc/exchange"), {
      method: "POST", credentials: "include",
      headers: { "Content-Type": "application/json" }, body: JSON.stringify({ code }),
    })
    const data = await response.json()
    if (!response.ok || typeof data.token !== "string" || !data.token) throw new Error("OIDC sign-in failed")
    localStorage.setItem("proxmenux-auth-token", data.token)
    sessionStorage.removeItem("proxmenux-auth-401-handled")
    sessionStorage.removeItem("proxmenux-oidc-error")
  } catch {
    // Continue through the normal auth gate even when the exchange fails.
    try { sessionStorage.setItem("proxmenux-oidc-error", "1") } catch { /* Storage may be disabled. */ }
  }
}
