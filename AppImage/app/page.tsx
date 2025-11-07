"use client"

import { useState, useEffect } from "react"
import { ProxmoxDashboard } from "../components/proxmox-dashboard"
import { Login } from "../components/login"
import { AuthSetup } from "../components/auth-setup"
import { getApiUrl } from "../lib/api-config"

export default function Home() {
  const [authState, setAuthState] = useState<"loading" | "setup" | "login" | "authenticated">("loading")

  useEffect(() => {
    checkAuthStatus()
  }, [])

  const checkAuthStatus = async () => {
    try {
      const response = await fetch(getApiUrl("/api/auth/status"), {
        method: "GET",
        headers: {
          "Content-Type": "application/json",
        },
      })

      const data = await response.json()

      if (!data.auth_enabled) {
        // Auth no está habilitada, permitir acceso directo
        setAuthState("authenticated")
        return
      }

      // Auth está habilitada, verificar si hay token válido
      const token = localStorage.getItem("proxmenux-auth-token")

      if (!token) {
        setAuthState("login")
        return
      }

      // Verificar que el token sea válido
      const verifyResponse = await fetch(getApiUrl("/api/auth/verify"), {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token}`,
        },
      })

      if (verifyResponse.ok) {
        setAuthState("authenticated")
      } else {
        // Token inválido, limpiar y pedir login
        localStorage.removeItem("proxmenux-auth-token")
        localStorage.removeItem("proxmenux-saved-username")
        localStorage.removeItem("proxmenux-saved-password")
        setAuthState("login")
      }
    } catch (error) {
      console.error("Error checking auth status:", error)
      // En caso de error, mostrar setup
      setAuthState("setup")
    }
  }

  const handleSetupComplete = () => {
    setAuthState("login")
  }

  const handleLoginSuccess = () => {
    setAuthState("authenticated")
  }

  if (authState === "loading") {
    return (
      <div className="min-h-screen bg-background flex items-center justify-center">
        <div className="text-center">
          <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-primary mx-auto"></div>
          <p className="mt-4 text-muted-foreground">Loading...</p>
        </div>
      </div>
    )
  }

  if (authState === "setup") {
    return <AuthSetup onComplete={handleSetupComplete} />
  }

  if (authState === "login") {
    return <Login onLogin={handleLoginSuccess} />
  }

  return <ProxmoxDashboard />
}
