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
  Zap,
  Shield,
  Link2,
  Gauge,
} from "lucide-react"
import Image from "next/image"
import { Checkbox } from "./ui/checkbox"

interface OnboardingSlide {
  id: number
  title: string
  description: string
  image?: string
  icon: React.ReactNode
  gradient: string
  features?: { icon: React.ReactNode; text: string }[]
}

const slides: OnboardingSlide[] = [
  {
    id: 0,
    title: "Welcome to ProxMenux Monitor!",
    description:
      "Your new monitoring tool for Proxmox. Discover all the features that will help you manage and supervise your infrastructure efficiently.",
    icon: <Sparkles className="h-16 w-16" />,
    gradient: "from-blue-500 via-purple-500 to-pink-500",
  },
  {
    id: 1,
    title: "What's New in This Version",
    description: "We've added exciting new features and improvements to make ProxMenux Monitor even better!",
    icon: <Zap className="h-16 w-16" />,
    gradient: "from-amber-500 via-orange-500 to-red-500",
    features: [
      {
        icon: <Link2 className="h-5 w-5" />,
        text: "Proxy Support - Access ProxMenux through reverse proxies with full functionality",
      },
      {
        icon: <Shield className="h-5 w-5" />,
        text: "Authentication System - Secure your dashboard with password protection",
      },
      {
        icon: <Gauge className="h-5 w-5" />,
        text: "PCIe Link Speed Detection - View NVMe drive connection speeds and detect performance issues",
      },
      {
        icon: <HardDrive className="h-5 w-5" />,
        text: "Enhanced Storage Display - Better formatting for disk sizes (auto-converts GB to TB when needed)",
      },
      {
        icon: <Network className="h-5 w-5" />,
        text: "SATA/SAS Information - View detailed interface information for all storage devices",
      },
    ],
  },
  {
    id: 2,
    title: "System Overview",
    description:
      "Monitor your server's status in real-time: CPU, memory, temperature, system load and more. Everything in an intuitive and easy-to-understand dashboard.",
    image: "/images/onboarding/imagen1.png",
    icon: <LayoutDashboard className="h-12 w-12" />,
    gradient: "from-blue-500 to-cyan-500",
  },
  {
    id: 3,
    title: "Storage Management",
    description:
      "Visualize the status of all your disks and volumes. Detailed information on capacity, usage, SMART health, temperature and performance of each storage device.",
    image: "/images/onboarding/imagen2.png",
    icon: <HardDrive className="h-12 w-12" />,
    gradient: "from-cyan-500 to-teal-500",
  },
  {
    id: 4,
    title: "Network Metrics",
    description:
      "Monitor network traffic in real-time. Bandwidth statistics, active interfaces, transfer speeds and historical usage graphs.",
    image: "/images/onboarding/imagen3.png",
    icon: <Network className="h-12 w-12" />,
    gradient: "from-teal-500 to-green-500",
  },
  {
    id: 5,
    title: "Virtual Machines & Containers",
    description:
      "Manage all your VMs and LXC containers from one place. Status, allocated resources, current usage and quick controls for each virtual machine.",
    image: "/images/onboarding/imagen4.png",
    icon: <Box className="h-12 w-12" />,
    gradient: "from-green-500 to-emerald-500",
  },
  {
    id: 6,
    title: "Hardware Information",
    description:
      "Complete details of your server hardware: CPU, RAM, GPU, disks, network, UPS and more. Technical specifications, models, serial numbers and status of each component.",
    image: "/images/onboarding/imagen5.png",
    icon: <Cpu className="h-12 w-12" />,
    gradient: "from-emerald-500 to-blue-500",
  },
  {
    id: 7,
    title: "System Logs",
    description:
      "Access system logs in real-time. Filter by event type, search for specific errors and keep complete track of your server activity. Download the displayed logs for further analysis.",
    image: "/images/onboarding/imagen6.png",
    icon: <FileText className="h-12 w-12" />,
    gradient: "from-blue-500 to-indigo-500",
  },
  {
    id: 8,
    title: "Ready for the Future!",
    description:
      "ProxMenux Monitor is prepared to receive updates and improvements that will be added gradually, improving the user experience and being able to execute ProxMenux functions from the web panel.",
    icon: <Rocket className="h-16 w-16" />,
    gradient: "from-indigo-500 via-purple-500 to-pink-500",
  },
]

export function OnboardingCarousel() {
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

          <div
            className={`relative h-48 md:h-64 bg-gradient-to-br ${slide.gradient} flex items-center justify-center overflow-hidden`}
          >
            <div className="absolute inset-0 bg-black/10" />
            <div className="absolute inset-0 bg-[radial-gradient(circle_at_50%_120%,rgba(255,255,255,0.1),transparent)]" />

            {/* Icon or Image */}
            <div className="relative z-10 text-white">
              {slide.image ? (
                <div className="relative w-full h-36 md:h-48 flex items-center justify-center px-4">
                  <Image
                    src={slide.image || "/placeholder.svg"}
                    alt={slide.title}
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

            {/* Decorative elements */}
            <div className="absolute top-10 left-10 w-20 h-20 bg-white/10 rounded-full blur-2xl" />
            <div className="absolute bottom-10 right-10 w-32 h-32 bg-white/10 rounded-full blur-3xl" />
          </div>

          <div className="p-4 md:p-8 space-y-4 md:space-y-6">
            <div className="space-y-2 md:space-y-3">
              <h2 className="text-2xl md:text-3xl font-bold text-foreground text-balance">{slide.title}</h2>
              <p className="text-base md:text-lg text-muted-foreground leading-relaxed text-pretty">
                {slide.description}
              </p>
            </div>

            {slide.features && (
              <div className="space-y-3 py-2">
                {slide.features.map((feature, index) => (
                  <div
                    key={index}
                    className="flex items-start gap-3 p-3 rounded-lg bg-muted/50 border border-border/50"
                  >
                    <div className="text-blue-500 mt-0.5">{feature.icon}</div>
                    <p className="text-sm text-foreground leading-relaxed">{feature.text}</p>
                  </div>
                ))}
              </div>
            )}

            {/* Progress dots */}
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
                  aria-label={`Go to slide ${index + 1}`}
                />
              ))}
            </div>

            <div className="flex flex-col sm:flex-row items-center justify-between gap-3 md:gap-4">
              <Button
                variant="ghost"
                onClick={handlePrev}
                disabled={currentSlide === 0}
                className="gap-2 w-full sm:w-auto"
              >
                <ChevronLeft className="h-4 w-4" />
                Previous
              </Button>

              <div className="flex gap-2 w-full sm:w-auto">
                {currentSlide < slides.length - 1 ? (
                  <>
                    <Button variant="outline" onClick={handleSkip} className="flex-1 sm:flex-none bg-transparent">
                      Skip
                    </Button>
                    <Button onClick={handleNext} className="gap-2 bg-blue-500 hover:bg-blue-600 flex-1 sm:flex-none">
                      Next
                      <ChevronRight className="h-4 w-4" />
                    </Button>
                  </>
                ) : (
                  <Button
                    onClick={handleNext}
                    className="gap-2 bg-gradient-to-r from-blue-500 to-purple-500 hover:from-blue-600 hover:to-purple-600 w-full sm:w-auto"
                  >
                    Get Started!
                    <Sparkles className="h-4 w-4" />
                  </Button>
                )}
              </div>
            </div>

            <div className="flex items-center justify-center gap-2 pt-2">
              <Checkbox
                id="dont-show-again"
                checked={dontShowAgain}
                onCheckedChange={(checked) => setDontShowAgain(checked as boolean)}
              />
              <label
                htmlFor="dont-show-again"
                className="text-sm text-muted-foreground hover:text-foreground transition-colors cursor-pointer"
              >
                Don't show this again
              </label>
            </div>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  )
}
