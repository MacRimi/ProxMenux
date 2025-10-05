import { LayoutDashboard, HardDrive, Network, Server, Cpu, FileText } from "path-to-icons"

const menuItems = [
  { name: "Overview", href: "/", icon: LayoutDashboard },
  { name: "Storage", href: "/storage", icon: HardDrive },
  { name: "Network", href: "/network", icon: Network },
  { name: "Virtual Machines", href: "/virtual-machines", icon: Server },
  { name: "Hardware", href: "/hardware", icon: Cpu }, // New Hardware section
  { name: "System Logs", href: "/logs", icon: FileText },
]
