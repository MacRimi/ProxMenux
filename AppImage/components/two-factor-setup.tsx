"use client"

import { useState } from "react"
import { Button } from "./ui/button"
import { Input } from "./ui/input"
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "./ui/dialog"
import { AlertCircle, CheckCircle, Copy, Shield, Check } from "lucide-react"
import { getApiUrl } from "../lib/api-config"
import Image from "next/image"

interface TwoFactorSetupProps {
  open: boolean
  onClose: () => void
  onSuccess: () => void
}

export function TwoFactorSetup({ open, onClose, onSuccess }: TwoFactorSetupProps) {
  const [step, setStep] = useState(1)
  const [qrCode, setQrCode] = useState("")
  const [secret, setSecret] = useState("")
  const [backupCodes, setBackupCodes] = useState<string[]>([])
  const [verificationCode, setVerificationCode] = useState("")
  const [error, setError] = useState("")
  const [loading, setLoading] = useState(false)
  const [copiedSecret, setCopiedSecret] = useState(false)
  const [copiedCodes, setCopiedCodes] = useState(false)

  const handleSetupStart = async () => {
    setError("")
    setLoading(true)

    try {
      const token = localStorage.getItem("proxmenux-auth-token")
      const response = await fetch(getApiUrl("/api/auth/totp/setup"), {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token}`,
        },
      })

      const data = await response.json()

      if (!response.ok) {
        throw new Error(data.message || "Failed to setup 2FA")
      }

      setQrCode(data.qr_code)
      setSecret(data.secret)
      setBackupCodes(data.backup_codes)
      setStep(2)
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to setup 2FA")
    } finally {
      setLoading(false)
    }
  }

  const handleVerify = async () => {
    if (!verificationCode || verificationCode.length !== 6) {
      setError("Please enter a 6-digit code")
      return
    }

    setError("")
    setLoading(true)

    try {
      const token = localStorage.getItem("proxmenux-auth-token")
      const response = await fetch(getApiUrl("/api/auth/totp/enable"), {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({ token: verificationCode }),
      })

      const data = await response.json()

      if (!response.ok) {
        throw new Error(data.message || "Invalid verification code")
      }

      setStep(3)
    } catch (err) {
      setError(err instanceof Error ? err.message : "Verification failed")
    } finally {
      setLoading(false)
    }
  }

  const copyToClipboard = (text: string, type: "secret" | "codes") => {
    navigator.clipboard.writeText(text)
    if (type === "secret") {
      setCopiedSecret(true)
      setTimeout(() => setCopiedSecret(false), 2000)
    } else {
      setCopiedCodes(true)
      setTimeout(() => setCopiedCodes(false), 2000)
    }
  }

  const handleClose = () => {
    setStep(1)
    setQrCode("")
    setSecret("")
    setBackupCodes([])
    setVerificationCode("")
    setError("")
    onClose()
  }

  const handleFinish = () => {
    handleClose()
    onSuccess()
  }

  return (
    <Dialog open={open} onOpenChange={handleClose}>
      <DialogContent className="max-w-md max-h-[90vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Shield className="h-5 w-5 text-blue-500" />
            Configurar Autenticación de Dos Factores
          </DialogTitle>
          <DialogDescription>Añade una capa extra de seguridad a tu cuenta</DialogDescription>
        </DialogHeader>

        {error && (
          <div className="bg-red-500/10 border border-red-500/20 rounded-lg p-3 flex items-start gap-2">
            <AlertCircle className="h-5 w-5 text-red-500 flex-shrink-0 mt-0.5" />
            <p className="text-sm text-red-500">{error}</p>
          </div>
        )}

        {step === 1 && (
          <div className="space-y-4">
            <div className="bg-blue-500/10 border border-blue-500/20 rounded-lg p-4">
              <p className="text-sm text-blue-500">
                La autenticación de dos factores (2FA) añade una capa extra de seguridad requiriendo un código de tu
                aplicación de autenticación además de tu contraseña.
              </p>
            </div>

            <div className="space-y-2">
              <h4 className="font-medium">Necesitarás:</h4>
              <ul className="text-sm text-muted-foreground space-y-1 list-disc list-inside">
                <li>Una aplicación de autenticación (Google Authenticator, Authy, etc.)</li>
                <li>Escanear un código QR o introducir una clave manualmente</li>
                <li>Guardar códigos de respaldo de forma segura</li>
              </ul>
            </div>

            <Button onClick={handleSetupStart} className="w-full bg-blue-500 hover:bg-blue-600" disabled={loading}>
              {loading ? "Iniciando..." : "Comenzar Configuración"}
            </Button>
          </div>
        )}

        {step === 2 && (
          <div className="space-y-4">
            <div className="space-y-2">
              <h4 className="font-medium">1. Escanea el código QR</h4>
              <p className="text-sm text-muted-foreground">
                Abre tu aplicación de autenticación y escanea este código QR
              </p>
              {qrCode && (
                <div className="flex justify-center p-4 bg-white rounded-lg">
                  <Image src={qrCode || "/placeholder.svg"} alt="QR Code" width={200} height={200} />
                </div>
              )}
            </div>

            <div className="space-y-2">
              <h4 className="font-medium">O introduce la clave manualmente:</h4>
              <div className="flex gap-2">
                <Input value={secret} readOnly className="font-mono text-sm" />
                <Button
                  variant="outline"
                  size="icon"
                  onClick={() => copyToClipboard(secret, "secret")}
                  title="Copiar clave"
                >
                  {copiedSecret ? <Check className="h-4 w-4 text-green-500" /> : <Copy className="h-4 w-4" />}
                </Button>
              </div>
            </div>

            <div className="space-y-2">
              <h4 className="font-medium">2. Introduce el código de verificación</h4>
              <p className="text-sm text-muted-foreground">
                Introduce el código de 6 dígitos que aparece en tu aplicación
              </p>
              <Input
                type="text"
                placeholder="000000"
                value={verificationCode}
                onChange={(e) => setVerificationCode(e.target.value.replace(/\D/g, "").slice(0, 6))}
                className="text-center text-lg tracking-widest font-mono"
                maxLength={6}
                disabled={loading}
              />
            </div>

            <div className="flex gap-2">
              <Button onClick={handleVerify} className="flex-1 bg-blue-500 hover:bg-blue-600" disabled={loading}>
                {loading ? "Verificando..." : "Verificar y Activar"}
              </Button>
              <Button onClick={handleClose} variant="outline" className="flex-1 bg-transparent" disabled={loading}>
                Cancelar
              </Button>
            </div>
          </div>
        )}

        {step === 3 && (
          <div className="space-y-4">
            <div className="bg-green-500/10 border border-green-500/20 rounded-lg p-4 flex items-start gap-2">
              <CheckCircle className="h-5 w-5 text-green-500 flex-shrink-0 mt-0.5" />
              <div>
                <p className="font-medium text-green-500">2FA Activado Correctamente</p>
                <p className="text-sm text-green-500 mt-1">
                  Tu cuenta ahora está protegida con autenticación de dos factores
                </p>
              </div>
            </div>

            <div className="space-y-2">
              <h4 className="font-medium text-orange-500">Importante: Guarda tus códigos de respaldo</h4>
              <p className="text-sm text-muted-foreground">
                Estos códigos te permitirán acceder a tu cuenta si pierdes acceso a tu aplicación de autenticación.
                Guárdalos en un lugar seguro.
              </p>

              <div className="bg-muted/50 rounded-lg p-4 space-y-2">
                <div className="flex justify-between items-center mb-2">
                  <span className="text-sm font-medium">Códigos de Respaldo</span>
                  <Button variant="outline" size="sm" onClick={() => copyToClipboard(backupCodes.join("\n"), "codes")}>
                    {copiedCodes ? (
                      <Check className="h-4 w-4 text-green-500 mr-2" />
                    ) : (
                      <Copy className="h-4 w-4 mr-2" />
                    )}
                    Copiar Todos
                  </Button>
                </div>
                <div className="grid grid-cols-2 gap-2">
                  {backupCodes.map((code, index) => (
                    <div key={index} className="bg-background rounded px-3 py-2 font-mono text-sm text-center">
                      {code}
                    </div>
                  ))}
                </div>
              </div>
            </div>

            <Button onClick={handleFinish} className="w-full bg-blue-500 hover:bg-blue-600">
              Finalizar
            </Button>
          </div>
        )}
      </DialogContent>
    </Dialog>
  )
}
