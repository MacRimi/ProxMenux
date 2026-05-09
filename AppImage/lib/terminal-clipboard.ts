/**
 * Clipboard helpers for the web terminals.
 *
 * Mobile browsers (iOS Safari, Android Chrome) don't expose xterm.js's text
 * selection / clipboard the same way desktop does, and the mobile toolbar
 * around our terminals doesn't include explicit copy/paste keys. The helpers
 * below give the toolbar a robust path that:
 *   - Uses the modern async Clipboard API on HTTPS / localhost.
 *   - Falls back to a hidden <textarea> + document.execCommand on plain HTTP
 *     (where the async API is gated by the secure-context requirement).
 *   - Surfaces a user-visible cue (no toast manager in this stack yet) by
 *     returning a result the caller can react to.
 */

// xterm.js is imported dynamically by the terminal components and the
// `term` field is typed `any` there. We mirror that here with a minimal
// structural type so this helper has no hard dependency on @xterm/xterm.
type XtermLike = { getSelection?: () => string }

export type ClipboardResult = {
  ok: boolean
  /** Bytes / chars copied (only meaningful on copy). */
  length?: number
  /** Best-effort error string for logging — never surfaced verbatim to the user. */
  error?: string
}

/**
 * Copies the current xterm selection to the clipboard. If there is no active
 * selection, returns ok=false with length=0 so the caller can decide whether to
 * show a "select text first" hint.
 */
export async function copyTerminalSelection(term: XtermLike | null | undefined): Promise<ClipboardResult> {
  const text = term?.getSelection?.() ?? ""
  if (!text) {
    return { ok: false, length: 0, error: "no-selection" }
  }
  return copyText(text)
}

/**
 * Reads text from the clipboard and feeds it to the terminal via `sendFn`.
 * The `sendFn` is the WebSocket sender (or any fn that takes a string and
 * pushes it to the remote PTY). Any newlines remain intact so that pasting
 * a multi-line block triggers as Enter on each line — same as desktop xterm.
 *
 * Mobile users on plain HTTP (the common case for this dashboard — accessed
 * via `http://<host>:8008` from an iPad/phone on the LAN) hit two layers of
 * blocking:
 *   1. `window.isSecureContext` is false on plain HTTP, so the legacy code
 *      skipped the async API and surfaced a silent error.
 *   2. There is no `execCommand('paste')` equivalent that works portably.
 *
 * The fix here:
 *   - Attempt `navigator.clipboard.readText()` even when not secure-context;
 *     many modern browsers permit it on localhost/LAN with user gesture, and
 *     when they don't they throw, which falls through cleanly.
 *   - If that fails / returns empty, fall back to `window.prompt()`. The
 *     native prompt accepts a long-press paste from the OS clipboard on
 *     every mobile platform, so the user can finish the paste manually
 *     with one extra tap. Empty / cancelled prompt returns ok=false.
 */
export async function pasteFromClipboard(
  sendFn: (text: string) => void,
): Promise<ClipboardResult> {
  // Path 1 — async Clipboard API. Try regardless of `isSecureContext` so
  // browsers that allow it on LAN-HTTP (Chrome on Android, Firefox) can
  // succeed. Throws on iOS Safari / strict configurations — we fall through.
  try {
    if (typeof navigator !== "undefined" && navigator.clipboard?.readText) {
      const text = await navigator.clipboard.readText()
      if (text) {
        sendFn(text)
        return { ok: true, length: text.length }
      }
    }
  } catch {
    // Permission denied / not focused / insecure context — fall through to prompt().
  }

  // Path 2 — `window.prompt()` fallback. Universally supported, accepts a
  // long-press paste from the system clipboard, and works over plain HTTP.
  // This is the path mobile users without HTTPS rely on.
  try {
    const text = typeof window !== "undefined"
      ? window.prompt("Paste content for the terminal:", "")
      : null
    if (text) {
      sendFn(text)
      return { ok: true, length: text.length }
    }
    return { ok: false, error: "user-cancelled" }
  } catch (e) {
    return { ok: false, error: e instanceof Error ? e.message : "prompt-failed" }
  }
}

async function copyText(text: string): Promise<ClipboardResult> {
  // Preferred path: async Clipboard API on HTTPS / localhost.
  try {
    if (typeof navigator !== "undefined" && navigator.clipboard && window.isSecureContext) {
      await navigator.clipboard.writeText(text)
      return { ok: true, length: text.length }
    }
  } catch {
    // fall through
  }
  // Legacy fallback: hidden textarea + execCommand("copy"). Works on plain HTTP
  // where the async API is blocked by the secure-context gate.
  try {
    const textarea = document.createElement("textarea")
    textarea.value = text
    textarea.style.position = "fixed"
    textarea.style.left = "-9999px"
    textarea.style.top = "-9999px"
    textarea.style.opacity = "0"
    textarea.readOnly = true
    document.body.appendChild(textarea)
    textarea.focus()
    textarea.select()
    const ok = document.execCommand("copy")
    document.body.removeChild(textarea)
    return ok ? { ok: true, length: text.length } : { ok: false, error: "execCommand-failed" }
  } catch (e) {
    return { ok: false, error: e instanceof Error ? e.message : "fallback-failed" }
  }
}
