"use client"

import type React from "react"

import { useState, useEffect } from "react"
import { Button } from "./ui/button"
import { Dialog, DialogContent } from "./ui/dialog"
import {
  ChevronLeft,
  ChevronRight,
  X,
  Sparkles,
  LayoutDashboard,
  HardDrive,
  Network,
  Box,
  Cpu,
  FileText,
  Rocket,
} from "lucide-react"
import Image from "next/image"

interface OnboardingSlide {
  id: number
  title: string
  description: string
  image?: string
  icon: React.ReactNode
  gradient: string
}

const slides: OnboardingSlide[] = [
  {
    id: 0,
    title: "¡Bienvenido a ProxMenux Monitor!",
    description:
      "Tu nueva herramienta de monitoreo profesional para Proxmox. Descubre todas las funcionalidades que te ayudarán a gestionar y supervisar tu infraestructura de manera eficiente.",
    icon: <Sparkles className="h-16 w-16" />,
    gradient: "from-blue-500 via-purple-500 to-pink-500",
  },
  {
    id: 1,
    title: "Vista General del Sistema",
    description:
      "Monitorea en tiempo real el estado de tu servidor: CPU, memoria, temperatura, carga del sistema y más. Todo en un dashboard intuitivo y fácil de entender.",
    image: "/images/onboarding/imagen1.png",
    icon: <LayoutDashboard className="h-12 w-12" />,
    gradient: "from-blue-500 to-cyan-500",
  },
  {
    id: 2,
    title: "Gestión de Almacenamiento",
    description:
      "Visualiza el estado de todos tus discos y volúmenes. Información detallada de capacidad, uso, salud SMART, temperatura y rendimiento de cada dispositivo de almacenamiento.",
    image: "/images/onboarding/imagen2.png",
    icon: <HardDrive className="h-12 w-12" />,
    gradient: "from-cyan-500 to-teal-500",
  },
  {
    id: 3,
    title: "Métricas de Red",
    description:
      "Supervisa el tráfico de red en tiempo real. Estadísticas de ancho de banda, interfaces activas, velocidades de transferencia y gráficos históricos de uso.",
    image: "/images/onboarding/imagen3.png",
    icon: <Network className="h-12 w-12" />,
    gradient: "from-teal-500 to-green-500",
  },
  {
    id: 4,
    title: "Máquinas Virtuales y Contenedores",
    description:
      "Gestiona todas tus VMs y contenedores LXC desde un solo lugar. Estado, recursos asignados, uso actual y controles rápidos para cada máquina virtual.",
    image: "/images/onboarding/imagen4.png",
    icon: <Box className="h-12 w-12" />,
    gradient: "from-green-500 to-emerald-500",
  },
  {
    id: 5,
    title: "Información de Hardware",
    description:
      "Detalles completos del hardware de tu servidor: CPU, memoria RAM, GPU, discos, red, SAI y más. Especificaciones técnicas, modelos, números de serie y estado de cada componente.",
    image: "/images/onboarding/imagen5.png",
    icon: <Cpu className="h-12 w-12" />,
    gradient: "from-emerald-500 to-blue-500",
  },
  {
    id: 6,
    title: "Logs del Sistema",
    description:
      "Accede a los registros del sistema en tiempo real. Filtra por tipo de evento, busca errores específicos y mantén un seguimiento completo de la actividad de tu servidor.",
    image: "/images/onboarding/imagen6.png",
    icon: <FileText className="h-12 w-12" />,
    gradient: "from-blue-500 to-indigo-500",
  },
  {
    id: 7,
    title: "¡Preparado para el Futuro!",
    description:
      "ProxMenux Monitor está en constante evolución. Próximamente: alertas personalizadas, notificaciones push, integración con Telegram/Discord, reportes automáticos y muchas más funcionalidades.",
    icon: <Rocket className="h-16 w-16" />,
    gradient: "from-indigo-500 via-purple-500 to-pink-500",
  },
]

export function OnboardingCarousel() {
  const [open, setOpen] = useState(false)
  const [currentSlide, setCurrentSlide] = useState(0)
  const [direction, setDirection] = useState<"next" | "prev">("next")

  useEffect(() => {
    const hasSeenOnboarding = localStorage.getItem("proxmenux-onboarding-seen")
    if (!hasSeenOnboarding) {
      setOpen(true)
    }
  }, [])

  const handleNext = () => {
    if (currentSlide < slides.length - 1) {
      setDirection("next")
      setCurrentSlide(currentSlide + 1)
    } else {
      handleComplete()
    }
  }

  const handlePrev = () => {
    if (currentSlide > 0) {
      setDirection("prev")
      setCurrentSlide(currentSlide - 1)
    }
  }

  const handleSkip = () => {
    setOpen(false)
  }

  const handleComplete = () => {
    localStorage.setItem("proxmenux-onboarding-seen", "true")
    setOpen(false)
  }

  const handleDotClick = (index: number) => {
    setDirection(index > currentSlide ? "next" : "prev")
    setCurrentSlide(index)
  }

  const slide = slides[currentSlide]

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogContent className="max-w-4xl p-0 gap-0 overflow-hidden border-0 bg-transparent">
        <div className="relative bg-card rounded-lg overflow-hidden shadow-2xl">
          {/* Close button */}
          <Button
            variant="ghost"
            size="icon"
            className="absolute top-4 right-4 z-50 h-8 w-8 rounded-full bg-background/80 backdrop-blur-sm hover:bg-background"
            onClick={handleSkip}
          >
            <X className="h-4 w-4" />
          </Button>

          {/* Gradient header */}
          <div
            className={`relative h-64 bg-gradient-to-br ${slide.gradient} flex items-center justify-center overflow-hidden`}
          >
            <div className="absolute inset-0 bg-black/10" />
            <div className="absolute inset-0 bg-[radial-gradient(circle_at_50%_120%,rgba(255,255,255,0.1),transparent)]" />

            {/* Icon or Image */}
            <div className="relative z-10 text-white">
              {slide.image ? (
                <div className="relative w-full h-48 flex items-center justify-center">
                  <Image
                    src={slide.image || "/placeholder.svg"}
                    alt={slide.title}
                    width={600}
                    height={400}
                    className="rounded-lg shadow-2xl object-cover max-h-48"
                    onError={(e) => {
                      const target = e.target as HTMLImageElement
                      target.style.display = "none"
                      const fallback = target.parentElement?.querySelector(".fallback-icon")
                      if (fallback) {
                        fallback.classList.remove("hidden")
                      }
                    }}
                  />
                  <div className="fallback-icon hidden">{slide.icon}</div>
                </div>
              ) : (
                <div className="animate-pulse">{slide.icon}</div>
              )}
            </div>

            {/* Decorative elements */}
            <div className="absolute top-10 left-10 w-20 h-20 bg-white/10 rounded-full blur-2xl" />
            <div className="absolute bottom-10 right-10 w-32 h-32 bg-white/10 rounded-full blur-3xl" />
          </div>

          {/* Content */}
          <div className="p-8 space-y-6">
            <div className="space-y-3">
              <h2 className="text-3xl font-bold text-foreground text-balance">{slide.title}</h2>
              <p className="text-muted-foreground text-lg leading-relaxed text-pretty">{slide.description}</p>
            </div>

            {/* Progress dots */}
            <div className="flex items-center justify-center gap-2 py-4">
              {slides.map((_, index) => (
                <button
                  key={index}
                  onClick={() => handleDotClick(index)}
                  className={`transition-all duration-300 rounded-full ${
                    index === currentSlide
                      ? "w-8 h-2 bg-blue-500"
                      : "w-2 h-2 bg-muted-foreground/30 hover:bg-muted-foreground/50"
                  }`}
                  aria-label={`Go to slide ${index + 1}`}
                />
              ))}
            </div>

            {/* Navigation buttons */}
            <div className="flex items-center justify-between gap-4">
              <Button variant="ghost" onClick={handlePrev} disabled={currentSlide === 0} className="gap-2">
                <ChevronLeft className="h-4 w-4" />
                Anterior
              </Button>

              <div className="flex gap-2">
                {currentSlide < slides.length - 1 ? (
                  <>
                    <Button variant="outline" onClick={handleSkip}>
                      Omitir
                    </Button>
                    <Button onClick={handleNext} className="gap-2 bg-blue-500 hover:bg-blue-600">
                      Siguiente
                      <ChevronRight className="h-4 w-4" />
                    </Button>
                  </>
                ) : (
                  <Button
                    onClick={handleComplete}
                    className="gap-2 bg-gradient-to-r from-blue-500 to-purple-500 hover:from-blue-600 hover:to-purple-600"
                  >
                    ¡Comenzar!
                    <Sparkles className="h-4 w-4" />
                  </Button>
                )}
              </div>
            </div>

            {/* Don't show again */}
            {currentSlide === slides.length - 1 && (
              <div className="text-center pt-2">
                <button
                  onClick={handleComplete}
                  className="text-sm text-muted-foreground hover:text-foreground transition-colors underline"
                >
                  No mostrar de nuevo
                </button>
              </div>
            )}
          </div>
        </div>
      </DialogContent>
    </Dialog>
  )
}
