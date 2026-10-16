// Use the dashboard's existing update colors for every executable action.
// Version availability remains separate from action styling and enablement.
export function getUpdateActionButtonClass(hasUpdate: boolean, isCurrent: boolean): string {
  return !hasUpdate && isCurrent
    ? "bg-green-500/10 hover:bg-green-500/20 border border-green-500/30 text-green-400 hover:text-green-300"
    : "bg-purple-600/15 hover:bg-purple-600/25 border border-purple-500/40 text-purple-300 hover:text-purple-200"
}
