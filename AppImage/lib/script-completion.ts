// Native OCI `manage` reserves this code for an explicitly declined update.
export const OCI_CANCELLED_EXIT_CODE = 6

export function scriptCompletion(exitCode: number, cancelledExitCode?: number) {
  if (exitCode === 0) return { kind: "success", color: "32" } as const
  if (cancelledExitCode !== undefined && exitCode === cancelledExitCode) {
    return { kind: "cancelled", color: "36" } as const
  }
  return { kind: "error", color: "31" } as const
}

export function shouldRefreshOciAfterCompletion(exitCode?: number) {
  return exitCode !== OCI_CANCELLED_EXIT_CODE
}
