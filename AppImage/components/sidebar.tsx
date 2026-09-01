"use client"

import { LayoutDashboard, HardDrive, Network, Server, Cpu, FileText, SettingsIcon, Terminal } from "lucide-react"
import { useT } from "../lib/i18n/provider"

const menuItems = [
  { name: "Overview", href: "/", icon: LayoutDashboard },
  { name: "Storage", href: "/storage", icon: HardDrive },
  { name: "Network", href: "/network", icon: Network },
  { name: "Virtual Machines", href: "/virtual-machines", icon: Server },
  { name: "Hardware", href: "/hardware", icon: Cpu },
  { name: "System Logs", href: "/logs", icon: FileText },
  { name: "Terminal", href: "/terminal", icon: Terminal },
  { name: "Settings", href: "/settings", icon: SettingsIcon },
]

const Sidebar = ({ currentPath, setOpen }) => {
  const t = useT()

  const handleNavigation = (tabName: string) => {
    // Dispatch custom event to change tab in dashboard
    const event = new CustomEvent("changeTab", { detail: { tab: tabName } })
    window.dispatchEvent(event)
    setOpen(false)
  }

  return (
    <div>
      <button
        onClick={() => handleNavigation("overview")}
        className={`flex items-center gap-3 px-3 py-2 rounded-lg transition-colors ${
          currentPath === "/" || currentPath === "/overview"
            ? "bg-blue-500/10 text-blue-500"
            : "text-muted-foreground hover:text-foreground hover:bg-accent"
        }`}
      >
        <LayoutDashboard className="h-5 w-5" />
        <span>{t("navigation.overview")}</span>
      </button>

      <button
        onClick={() => handleNavigation("storage")}
        className={`flex items-center gap-3 px-3 py-2 rounded-lg transition-colors ${
          currentPath === "/storage"
            ? "bg-blue-500/10 text-blue-500"
            : "text-muted-foreground hover:text-foreground hover:bg-accent"
        }`}
      >
        <HardDrive className="h-5 w-5" />
        <span>{t("navigation.storage")}</span>
      </button>

      <button
        onClick={() => handleNavigation("network")}
        className={`flex items-center gap-3 px-3 py-2 rounded-lg transition-colors ${
          currentPath === "/network"
            ? "bg-blue-500/10 text-blue-500"
            : "text-muted-foreground hover:text-foreground hover:bg-accent"
        }`}
      >
        <Network className="h-5 w-5" />
        <span>{t("navigation.network")}</span>
      </button>

      <button
        onClick={() => handleNavigation("vms")}
        className={`flex items-center gap-3 px-3 py-2 rounded-lg transition-colors ${
          currentPath === "/virtual-machines"
            ? "bg-blue-500/10 text-blue-500"
            : "text-muted-foreground hover:text-foreground hover:bg-accent"
        }`}
      >
        <Server className="h-5 w-5" />
        <span>{t("navigation.virtualMachines")}</span>
      </button>

      <button
        onClick={() => handleNavigation("hardware")}
        className={`flex items-center gap-3 px-3 py-2 rounded-lg transition-colors ${
          currentPath === "/hardware"
            ? "bg-blue-500/10 text-blue-500"
            : "text-muted-foreground hover:text-foreground hover:bg-accent"
        }`}
      >
        <Cpu className="h-5 w-5" />
        <span>{t("navigation.hardware")}</span>
      </button>

      <button
        onClick={() => handleNavigation("logs")}
        className={`flex items-center gap-3 px-3 py-2 rounded-lg transition-colors ${
          currentPath === "/logs"
            ? "bg-blue-500/10 text-blue-500"
            : "text-muted-foreground hover:text-foreground hover:bg-accent"
        }`}
      >
        <FileText className="h-5 w-5" />
        <span>{t("navigation.systemLogs")}</span>
      </button>

      <button
        onClick={() => handleNavigation("terminal")}
        className={`flex items-center gap-3 px-3 py-2 rounded-lg transition-colors ${
          currentPath === "/terminal"
            ? "bg-blue-500/10 text-blue-500"
            : "text-muted-foreground hover:text-foreground hover:bg-accent"
        }`}
      >
        <Terminal className="h-5 w-5" />
        <span>{t("navigation.terminal")}</span>
      </button>

      <button
        onClick={() => handleNavigation("settings")}
        className={`flex items-center gap-3 px-3 py-2 rounded-lg transition-colors ${
          currentPath === "/settings"
            ? "bg-blue-500/10 text-blue-500"
            : "text-muted-foreground hover:text-foreground hover:bg-accent"
        }`}
      >
        <SettingsIcon className="h-5 w-5" />
        <span>{t("navigation.settings")}</span>
      </button>
    </div>
  )
}

export default Sidebar
