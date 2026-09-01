"use client"

import type React from "react"

import { useState, useEffect } from "react"
import { Button } from "./ui/button"
import { Dialog, DialogContent, DialogTitle } from "./ui/dialog"
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
import { Checkbox } from "./ui/checkbox"
import { useT } from "../lib/i18n/provider"

interface OnboardingSlide {
  id: number
  titleKey: string
  descriptionKey: string
  image?: string
  icon: React.ReactNode
  gradient: string
}

const slides: OnboardingSlide[] = [
  {
    id: 0,
    titleKey: "onboarding.slides.welcome.title",
    descriptionKey: "onboarding.slides.welcome.description",
    icon: <Sparkles className="h-16 w-16" />,
    gradient: "from-blue-500 via-purple-500 to-pink-500",
  },
  {
    id: 1,
    titleKey: "onboarding.slides.overview.title",
    descriptionKey: "onboarding.slides.overview.description",
    image: "/images/onboarding/imagen1.png",
    icon: <LayoutDashboard className="h-12 w-12" />,
    gradient: "from-blue-500 to-cyan-500",
  },
  {
    id: 2,
    titleKey: "onboarding.slides.storage.title",
    descriptionKey: "onboarding.slides.storage.description",
    image: "/images/onboarding/imagen2.png",
    icon: <HardDrive className="h-12 w-12" />,
    gradient: "from-cyan-500 to-teal-500",
  },
  {
    id: 3,
    titleKey: "onboarding.slides.network.title",
    descriptionKey: "onboarding.slides.network.description",
    image: "/images/onboarding/imagen3.png",
    icon: <Network className="h-12 w-12" />,
    gradient: "from-teal-500 to-green-500",
  },
  {
    id: 4,
    titleKey: "onboarding.slides.virtualMachines.title",
    descriptionKey: "onboarding.slides.virtualMachines.description",
    image: "/images/onboarding/imagen4.png",
    icon: <Box className="h-12 w-12" />,
    gradient: "from-green-500 to-emerald-500",
  },
  {
    id: 5,
    titleKey: "onboarding.slides.hardware.title",
    descriptionKey: "onboarding.slides.hardware.description",
    image: "/images/onboarding/imagen5.png",
    icon: <Cpu className="h-12 w-12" />,
    gradient: "from-emerald-500 to-blue-500",
  },
  {
    id: 6,
    titleKey: "onboarding.slides.logs.title",
    descriptionKey: "onboarding.slides.logs.description",
    image: "/images/onboarding/imagen6.png",
    icon: <FileText className="h-12 w-12" />,
    gradient: "from-blue-500 to-indigo-500",
  },
  {
    id: 7,
    titleKey: "onboarding.slides.future.title",
    descriptionKey: "onboarding.slides.future.description",
    icon: <Rocket className="h-16 w-16" />,
    gradient: "from-indigo-500 via-purple-500 to-pink-500",
  },
]

export function OnboardingCarousel() {
  const t = useT()
  const [open, setOpen] = useState(false)
  const [currentSlide, setCurrentSlide] = useState(0)
  const [direction, setDirection] = useState<"next" | "prev">("next")
  const [dontShowAgain, setDontShowAgain] = useState(false)

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
      if (dontShowAgain) {
        localStorage.setItem("proxmenux-onboarding-seen", "true")
      }
      setOpen(false)
    }
  }

  const handlePrev = () => {
    if (currentSlide > 0) {
      setDirection("prev")
      setCurrentSlide(currentSlide - 1)
    }
  }

  const handleSkip = () => {
    if (dontShowAgain) {
      localStorage.setItem("proxmenux-onboarding-seen", "true")
    }
    setOpen(false)
  }

  const handleClose = () => {
    if (dontShowAgain) {
      localStorage.setItem("proxmenux-onboarding-seen", "true")
    }
    setOpen(false)
  }

  const handleDotClick = (index: number) => {
    setDirection(index > currentSlide ? "next" : "prev")
    setCurrentSlide(index)
  }

  const slide = slides[currentSlide]
  const slideTitle = t(slide.titleKey)
  const slideDescription = t(slide.descriptionKey)

  return (
    <Dialog open={open} onOpenChange={handleClose}>
      <DialogContent className="max-w-4xl p-0 gap-0 overflow-hidden border-0 bg-transparent">
        <DialogTitle className="sr-only">{t("onboarding.dialogTitle")}</DialogTitle>
        <div className="relative bg-card rounded-lg overflow-hidden shadow-2xl">
          <Button
            variant="ghost"
            size="icon"
            className="absolute top-4 right-4 z-50 h-8 w-8 rounded-full bg-background/80 backdrop-blur-sm hover:bg-background"
            onClick={handleClose}
          >
            <X className="h-4 w-4" />
          </Button>

          <div
            className={`relative h-48 md:h-64 bg-gradient-to-br ${slide.gradient} flex items-center justify-center overflow-hidden`}
          >
            <div className="absolute inset-0 bg-black/10" />
            <div className="absolute inset-0 bg-[radial-gradient(circle_at_50%_120%,rgba(255,255,255,0.1),transparent)]" />

            <div className="relative z-10 text-white">
              {slide.image ? (
                <div className="relative w-full h-36 md:h-48 flex items-center justify-center px-4">
                  <Image
                    src={slide.image || "/placeholder.svg"}
                    alt={slideTitle}
                    width={600}
                    height={400}
                    className="rounded-lg shadow-2xl object-cover max-h-36 md:max-h-48"
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

            <div className="absolute top-10 left-10 w-20 h-20 bg-white/10 rounded-full blur-2xl" />
            <div className="absolute bottom-10 right-10 w-32 h-32 bg-white/10 rounded-full blur-3xl" />
          </div>

          <div className="p-4 md:p-8 space-y-3 md:space-y-6 max-h-[60vh] md:max-h-none overflow-y-auto">
            <div className="space-y-2 md:space-y-3">
              <h2 className="text-xl md:text-3xl font-bold text-foreground text-balance">{slideTitle}</h2>
              <p className="text-sm md:text-lg text-muted-foreground leading-relaxed text-pretty">
                {slideDescription}
              </p>
            </div>

            <div className="flex items-center justify-center gap-2 py-2 md:py-4">
              {slides.map((_, index) => (
                <button
                  key={index}
                  onClick={() => handleDotClick(index)}
                  className={`transition-all duration-300 rounded-full ${
                    index === currentSlide
                      ? "w-8 h-2.5 bg-blue-500 shadow-lg shadow-blue-500/50"
                      : "w-2.5 h-2.5 bg-muted-foreground/60 hover:bg-muted-foreground/80 border border-muted-foreground/40"
                  }`}
                  aria-label={t("onboarding.goToSlide", { number: index + 1 })}
                />
              ))}
            </div>

            <div className="flex flex-col sm:flex-row items-center justify-between gap-2 md:gap-4">
              <Button
                variant="ghost"
                onClick={handlePrev}
                disabled={currentSlide === 0}
                className="gap-2 w-full sm:w-auto text-sm"
              >
                <ChevronLeft className="h-4 w-4" />
                {t("onboarding.previous")}
              </Button>

              <div className="flex gap-2 w-full sm:w-auto">
                {currentSlide < slides.length - 1 ? (
                  <>
                    <Button
                      variant="outline"
                      onClick={handleSkip}
                      className="flex-1 sm:flex-none bg-transparent text-sm"
                    >
                      {t("onboarding.skip")}
                    </Button>
                    <Button
                      onClick={handleNext}
                      className="gap-2 bg-blue-500 hover:bg-blue-600 flex-1 sm:flex-none text-sm"
                    >
                      {t("onboarding.next")}
                      <ChevronRight className="h-4 w-4" />
                    </Button>
                  </>
                ) : (
                  <Button
                    onClick={handleNext}
                    className="gap-2 bg-gradient-to-r from-blue-500 to-purple-500 hover:from-blue-600 hover:to-purple-600 w-full sm:w-auto text-sm"
                  >
                    {t("onboarding.getStarted")}
                    <Sparkles className="h-4 w-4" />
                  </Button>
                )}
              </div>
            </div>

            <div className="flex items-center justify-center gap-2 pt-2 pb-1">
              <Checkbox
                id="dont-show-again"
                checked={dontShowAgain}
                onCheckedChange={(checked) => setDontShowAgain(checked as boolean)}
              />
              <label
                htmlFor="dont-show-again"
                className="text-xs md:text-sm text-muted-foreground hover:text-foreground transition-colors cursor-pointer select-none"
              >
                {t("onboarding.dontShowAgain")}
              </label>
            </div>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  )
}
