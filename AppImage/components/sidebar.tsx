import { LayoutDashboard, HardDrive, Network, Server, Cpu, FileText, SettingsIcon, Terminal } from "lucide-react"

const menuItems = [
  { name: "Overview", href: "/", icon: LayoutDashboard },
  { name: "Storage", href: "/storage", icon: HardDrive },
  { name: "Network", href: "/network", icon: Network },
  { name: "Virtual Machines", href: "/virtual-machines", icon: Server },
  { name: "Hardware", href: "/hardware", icon: Cpu },
  { name: "Terminal", href: "/terminal", icon: Terminal },
  { name: "System Logs", href: "/logs", icon: FileText },
  { name: "Settings", href: "/settings", icon: SettingsIcon },
]
