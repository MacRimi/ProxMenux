"use client"

// How this session reaches the Monitor, as /api/auth/status tells it: the
// access mode and what the profile of the session can do (permissions.py).
// The interface hides what the session cannot use; the backend refuses it
// either way.
import { createContext, useContext } from "react"

export type AccessMode = "undecided" | "password" | "proxmox" | "read_only" | "open"

// The areas of the dashboard a profile sees; a custom profile chooses them.
export const AREAS = ["general", "apps", "menux", "guests", "node", "backup", "logs"] as const
export type Area = typeof AREAS[number]

export interface Capabilities {
  view: boolean
  execute: boolean
  guests: boolean
  backup: boolean
  update: boolean
  terminal: boolean
  admin: boolean
  areas: Record<Area, boolean>
}

export const FULL_ACCESS: Capabilities = {
  view: true, execute: true, guests: true, backup: true, update: true, terminal: true, admin: true,
  areas: { general: true, apps: true, menux: true, guests: true, node: true, backup: true, logs: true },
}

// A reply from a Monitor without areas sees them all, as it did then.
export function withAreas(capabilities: Partial<Capabilities> | undefined): Capabilities {
  if (!capabilities) return FULL_ACCESS
  return { ...FULL_ACCESS, ...capabilities, areas: { ...FULL_ACCESS.areas, ...(capabilities.areas || {}) } } as Capabilities
}

interface Access {
  mode: AccessMode
  capabilities: Capabilities
}

const AccessContext = createContext<Access>({ mode: "password", capabilities: FULL_ACCESS })

export const AccessProvider = AccessContext.Provider

export function useAccess(): Access {
  return useContext(AccessContext)
}
