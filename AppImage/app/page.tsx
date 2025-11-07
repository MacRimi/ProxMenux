"use client"

import { useState, useEffect } from "react"
import { ProxmoxDashboard } from "../components/proxmox-dashboard"
import { Login } from "../components/login"
import { AuthSetup } from "../components/auth-setup"
import { getApiUrl } from "../lib/api-config"

export default function Home() {
  const [authStatus, setAuthStatus] = useState<{
    loading: boolean
    authEnabled: boolean
    authConfigured: boolean
    authenticated: boolean
  }>({
    loading: true,
    authEnabled: false,
    authConfigured: false,
    authenticated: false,
  })

  useEffect(() => {
    checkAuthStatus()
  }, [])

  const checkAuthStatus = async () => {
    try {
      const token = localStorage.getItem("proxmenux-auth-token")
      const response = await fetch(getApiUrl("/api/auth/status"), {
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      })
      const data = await response.json()

      console.log("[v0] Auth status:", data)

      const authenticated = data.auth_enabled ? data.authenticated : true

      setAuthStatus({
        loading: false,
        authEnabled: data.auth_enabled,
        authConfigured: data.auth_configured,
        authenticated,
      })
    } catch (error) {
      console.error("[v0] Failed to check auth status:", error)
      setAuthStatus({
        loading: false,
        authEnabled: false,
        authConfigured: false,
        authenticated: true,
      })
    }
  }

  const handleAuthComplete = () => {
    checkAuthStatus()
  }

  const handleLoginSuccess = () => {
    checkAuthStatus()
  }

  if (authStatus.loading) {
    return (
      <div className="min-h-screen bg-background flex items-center justify-center">
        <div className="text-center space-y-4">
          <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-primary mx-auto"></div>
          <p className="text-muted-foreground">Loading...</p>
        </div>
      </div>
    )
  }

  if (authStatus.authEnabled && !authStatus.authenticated) {
    return <Login onLogin={handleLoginSuccess} />
  }

  // Show dashboard in all other cases
  return (
    <>
      {!authStatus.authConfigured && <AuthSetup onComplete={handleAuthComplete} />}
      <ProxmoxDashboard />
    </>
  )
}
