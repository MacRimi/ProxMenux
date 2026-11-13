"use client"

// How this session reaches the Monitor, as /api/auth/status tells it: the
// access mode and what the profile of the session can do (permissions.py).
// The interface hides what the session cannot use; the backend refuses it
// either way.
import { createContext, useContext } from "react"

export type AccessMode = "undecided" | "password" | "proxmox" | "read_only" | "open"

export interface Capabilities {
  view: boolean
  execute: boolean
  guests: boolean
  backup: boolean
  update: boolean
  terminal: boolean
  admin: boolean
}

export const FULL_ACCESS: Capabilities = {
  view: true, execute: true, guests: true, backup: true, update: true, terminal: true, admin: true,
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
