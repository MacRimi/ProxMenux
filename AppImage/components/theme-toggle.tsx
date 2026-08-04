"use client"
import { Moon, Sun } from "lucide-react"
import { useTheme } from "next-themes"
import { useEffect, useState } from "react"

import { Button } from "./ui/button"
import { useT } from "../lib/i18n/provider"

export function ThemeToggle() {
  const t = useT()
  const { theme, setTheme } = useTheme()
  const [mounted, setMounted] = useState(false)

  useEffect(() => {
    setMounted(true)
  }, [])

  const handleThemeToggle = () => {
    const newTheme = theme === "light" ? "dark" : "light"
    setTheme(newTheme)
  }

  if (!mounted) {
    return (
      <Button variant="outline" size="sm" className="border-border bg-transparent w-9 h-9">
        <Sun className="h-4 w-4" />
        <span className="sr-only">{t("actions.toggleTheme")}</span>
      </Button>
    )
  }

  return (
    <Button variant="outline" size="sm" onClick={handleThemeToggle} className="border-border bg-transparent w-9 h-9">
      <Sun className="h-4 w-4 rotate-0 scale-100 transition-all dark:-rotate-90 dark:scale-0" />
      <Moon className="absolute h-4 w-4 rotate-90 scale-0 transition-all dark:rotate-0 dark:scale-100" />
      <span className="sr-only">{t("actions.toggleTheme")}</span>
    </Button>
  )
}
