"use client"

// How this session reaches the Monitor, as /api/auth/status tells it: the
// access mode and what the session can do. The interface hides what the
// session cannot use; the backend refuses it either way.
import { createContext, useContext } from "react"

export type AccessMode = "undecided" | "password" | "read_only" | "open"

export interface Capabilities {
  view: boolean
  execute: boolean
  terminal: boolean
  admin: boolean
}

export const FULL_ACCESS: Capabilities = { view: true, execute: true, terminal: true, admin: true }

interface Access {
  mode: AccessMode
  capabilities: Capabilities
}

const AccessContext = createContext<Access>({ mode: "password", capabilities: FULL_ACCESS })

export const AccessProvider = AccessContext.Provider

export function useAccess(): Access {
  return useContext(AccessContext)
}
