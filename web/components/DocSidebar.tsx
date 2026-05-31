"use client"

// Use the locale-aware Link from next-intl so every sidebar href gets
// the active /en/ or /es/ prefix automatically. With `next/link` the
// hrefs were emitted without a locale (e.g. /docs/create-vm) and 404'd
// because the routing is configured with `localePrefix: "always"`.
import { Link, usePathname } from "@/i18n/navigation"
import { useState, useEffect } from "react"
import { ChevronDown, ChevronRight, Menu, X } from "lucide-react"
import { useTranslations } from "next-intl"

interface SubMenuItem {
  title: string
  i18nKey?: string  // key under docSidebar.items.* in messages — falls back to `title` if absent
  href: string
  submenu?: SubMenuItem[]
}

interface MenuItem {
  title: string
  i18nKey?: string  // key under docSidebar.items.* in messages — falls back to `title` if absent
  href?: string
  submenu?: SubMenuItem[]
}

function collectHrefs(items: SubMenuItem[]): string[] {
  const out: string[] = []
  for (const it of items) {
    out.push(it.href)
    if (it.submenu) out.push(...collectHrefs(it.submenu))
  }
  return out
}

export const sidebarItems: MenuItem[] = [
  { title: "Introduction", i18nKey: "introduction", href: "/docs/introduction" },
  { title: "Installation", i18nKey: "installation", href: "/docs/installation" },

  {
    title: "ProxMenux Monitor",
    i18nKey: "proxmenuxMonitor",
    submenu: [
      { title: "Overview", i18nKey: "monitorOverview", href: "/docs/monitor" },
      { title: "Architecture", i18nKey: "architecture", href: "/docs/monitor/architecture" },
      { title: "Access & Authentication", i18nKey: "accessAuth", href: "/docs/monitor/access-auth" },
      {
        title: "Dashboard",
        i18nKey: "dashboard",
        href: "/docs/monitor/dashboard",
        submenu: [
          { title: "System Overview tab", i18nKey: "dashboardSystemOverview", href: "/docs/monitor/dashboard/system-overview" },
          { title: "Storage tab", i18nKey: "dashboardStorage", href: "/docs/monitor/dashboard/storage" },
          { title: "Network tab", i18nKey: "dashboardNetwork", href: "/docs/monitor/dashboard/network" },
          { title: "VMs & LXCs tab", i18nKey: "dashboardVmsLxcs", href: "/docs/monitor/dashboard/vms-lxcs" },
          { title: "Hardware tab", i18nKey: "dashboardHardware", href: "/docs/monitor/dashboard/hardware" },
          { title: "System Logs tab", i18nKey: "dashboardSystemLogs", href: "/docs/monitor/dashboard/system-logs" },
          { title: "Terminal tab", i18nKey: "dashboardTerminal", href: "/docs/monitor/dashboard/terminal" },
          { title: "Security tab", i18nKey: "dashboardSecurity", href: "/docs/monitor/dashboard/security" },
          { title: "Settings tab", i18nKey: "dashboardSettings", href: "/docs/monitor/dashboard/settings" },
        ],
      },
      { title: "Health Monitor", i18nKey: "healthMonitor", href: "/docs/monitor/health-monitor" },
      { title: "Notifications", i18nKey: "notifications", href: "/docs/monitor/notifications" },
      { title: "AI Assistant", i18nKey: "aiAssistant", href: "/docs/monitor/ai-assistant" },
      { title: "API Reference", i18nKey: "apiReference", href: "/docs/monitor/api" },
      { title: "Integrations", i18nKey: "integrations", href: "/docs/monitor/integrations" },
    ],
  },

  {
    title: "ProxMenux Scripts",
    i18nKey: "proxmenuxScripts",
    submenu: [
      {
        title: "Post-Install Script",
        i18nKey: "postInstallScript",
        href: "/docs/post-install",
        submenu: [
          { title: "Overview", i18nKey: "postInstallOverview", href: "/docs/post-install" },
          { title: "Automated", i18nKey: "postInstallAutomated", href: "/docs/post-install/automated" },
          {
            title: "Customizable",
            i18nKey: "postInstallCustomizable",
            href: "/docs/post-install/customizable",
            submenu: [
              { title: "Basic Settings", i18nKey: "postInstallBasicSettings", href: "/docs/post-install/basic-settings" },
              { title: "System", i18nKey: "postInstallSystem", href: "/docs/post-install/system" },
              { title: "Virtualization", i18nKey: "postInstallVirtualization", href: "/docs/post-install/virtualization" },
              { title: "Network", i18nKey: "postInstallNetwork", href: "/docs/post-install/network" },
              { title: "Storage", i18nKey: "postInstallStorage", href: "/docs/post-install/storage" },
              { title: "Security", i18nKey: "postInstallSecurity", href: "/docs/post-install/security" },
              { title: "Customization", i18nKey: "postInstallCustomization", href: "/docs/post-install/customization" },
              { title: "Monitoring", i18nKey: "postInstallMonitoring", href: "/docs/post-install/monitoring" },
              { title: "Performance", i18nKey: "postInstallPerformance", href: "/docs/post-install/performance" },
              { title: "Optional", i18nKey: "postInstallOptional", href: "/docs/post-install/optional" },
            ],
          },
          { title: "Apply Available Updates", i18nKey: "postInstallUpdates", href: "/docs/post-install/updates" },
          { title: "Uninstall Optimizations", i18nKey: "postInstallUninstall", href: "/docs/post-install/uninstall" },
        ],
      },

      {
        title: "GPUs and Coral-TPU",
        i18nKey: "gpusCoralTpu",
        href: "/docs/hardware/nvidia-host",
        submenu: [
          { title: "Install NVIDIA Drivers (Host)", i18nKey: "nvidiaHost", href: "/docs/hardware/nvidia-host" },
          { title: "Install Coral TPU (Host)", i18nKey: "coralHost", href: "/docs/hardware/install-coral-tpu-host" },
          { title: "Add GPU to LXC", i18nKey: "addGpuLxc", href: "/docs/hardware/igpu-acceleration-lxc" },
          { title: "Add Coral TPU to LXC", i18nKey: "addCoralLxc", href: "/docs/hardware/coral-tpu-lxc" },
          { title: "Add GPU to VM (Passthrough)", i18nKey: "addGpuVm", href: "/docs/hardware/gpu-vm-passthrough" },
          { title: "Switch GPU Mode (VM ↔ LXC)", i18nKey: "switchGpuMode", href: "/docs/hardware/switch-gpu-mode" },
        ],
      },

      {
        title: "Create VM",
        i18nKey: "createVm",
        href: "/docs/create-vm",
        submenu: [
          { title: "Overview", i18nKey: "createVmOverview", href: "/docs/create-vm" },
          { title: "System NAS", i18nKey: "createVmSystemNas", href: "/docs/create-vm/system-nas" },
          { title: "Synology VM", i18nKey: "createVmSynology", href: "/docs/create-vm/system-nas/synology" },
          { title: "Others System NAS", i18nKey: "createVmNasOthers", href: "/docs/create-vm/system-nas/system-nas-others" },
          { title: "System Windows", i18nKey: "createVmSystemWindows", href: "/docs/create-vm/system-windows" },
          { title: "System Linux", i18nKey: "createVmSystemLinux", href: "/docs/create-vm/system-linux" },
        ],
      },

      {
        title: "Disk Manager",
        i18nKey: "diskManager",
        href: "/docs/disk-manager",
        submenu: [
          { title: "Overview", i18nKey: "diskManagerOverview", href: "/docs/disk-manager" },
          { title: "Import Disk to VM", i18nKey: "diskImportVm", href: "/docs/disk-manager/import-disk-vm" },
          { title: "Import Disk Image to VM", i18nKey: "diskImportImageVm", href: "/docs/disk-manager/import-disk-image-vm" },
          { title: "Add Controller or NVMe to VM", i18nKey: "diskAddController", href: "/docs/disk-manager/add-controller-nvme-vm" },
          { title: "Import Disk to LXC", i18nKey: "diskImportLxc", href: "/docs/disk-manager/import-disk-lxc" },
          { title: "Format / Wipe Physical Disk", i18nKey: "diskFormat", href: "/docs/disk-manager/format-disk" },
          { title: "SMART Disk Health & Test", i18nKey: "diskSmart", href: "/docs/disk-manager/smart-disk-test" },
        ],
      },

      {
        title: "Storage & Share Manager",
        i18nKey: "storageShareManager",
        href: "/docs/storage-share",
        submenu: [
          { title: "Overview", i18nKey: "storageShareOverview", href: "/docs/storage-share" },
          {
            title: "Host storage integration",
            i18nKey: "hostStorage",
            href: "/docs/storage-share#host",
            submenu: [
              { title: "Add NFS share as Proxmox storage", i18nKey: "hostNfs", href: "/docs/storage-share/host-nfs" },
              { title: "Add Samba share as Proxmox storage", i18nKey: "hostSamba", href: "/docs/storage-share/host-samba" },
              { title: "Add iSCSI target as Proxmox storage", i18nKey: "hostIscsi", href: "/docs/storage-share/host-iscsi" },
              { title: "Add local disk as Proxmox storage", i18nKey: "hostLocalDisk", href: "/docs/storage-share/host-local-disk" },
              { title: "Add shared directory on Host", i18nKey: "hostLocalShared", href: "/docs/storage-share/host-local-shared" },
            ],
          },
          { title: "LXC Mount Points (Host ↔ CT)", i18nKey: "lxcMountPoints", href: "/docs/storage-share/lxc-mount-points" },
          {
            title: "LXC network sharing",
            i18nKey: "lxcNetworkSharing",
            href: "/docs/storage-share#lxc-net",
            submenu: [
              { title: "NFS client in LXC", i18nKey: "lxcNfsClient", href: "/docs/storage-share/lxc-nfs-client" },
              { title: "Samba client in LXC", i18nKey: "lxcSambaClient", href: "/docs/storage-share/lxc-samba-client" },
              { title: "NFS server in LXC", i18nKey: "lxcNfsServer", href: "/docs/storage-share/lxc-nfs-server" },
              { title: "Samba server in LXC", i18nKey: "lxcSambaServer", href: "/docs/storage-share/lxc-samba-server" },
            ],
          },
        ],
      },

      {
        title: "Network",
        i18nKey: "network",
        href: "/docs/network",
        submenu: [
          { title: "Overview", i18nKey: "networkOverview", href: "/docs/network" },
          { title: "Diagnostics", i18nKey: "networkDiagnostics", href: "/docs/network/diagnostics" },
          { title: "Live monitoring tools", i18nKey: "networkMonitoring", href: "/docs/network/monitoring" },
          { title: "Bridge analysis & repair", i18nKey: "networkBridge", href: "/docs/network/bridge-analysis" },
          { title: "Config analysis & cleanup", i18nKey: "networkConfig", href: "/docs/network/config-analysis" },
          { title: "Persistent interface names", i18nKey: "networkPersistent", href: "/docs/network/persistent-names" },
          { title: "Interfaces backup & restart", i18nKey: "networkBackup", href: "/docs/network/backup-restore" },
        ],
      },

      {
        title: "Security",
        i18nKey: "security",
        href: "/docs/security",
        submenu: [
          { title: "Overview", i18nKey: "securityOverview", href: "/docs/security" },
          { title: "Fail2Ban", i18nKey: "securityFail2ban", href: "/docs/security/fail2ban" },
          { title: "Lynis", i18nKey: "securityLynis", href: "/docs/security/lynis" },
        ],
      },

      {
        title: "Utilities",
        i18nKey: "utilities",
        href: "/docs/utils",
        submenu: [
          { title: "Overview", i18nKey: "utilsOverview", href: "/docs/utils" },
          { title: "UUP Dump ISO Creator", i18nKey: "utilsUupDump", href: "/docs/utils/UUp-Dump-ISO-Creator" },
          { title: "System Utilities Installer", i18nKey: "utilsSystemUtils", href: "/docs/utils/system-utils" },
          { title: "Proxmox System Update", i18nKey: "utilsSystemUpdate", href: "/docs/utils/system-update" },
          { title: "Upgrade PVE 8 to PVE 9", i18nKey: "utilsUpgradePve", href: "/docs/utils/upgrade-pve8-pve9" },
          { title: "Export VM to OVA / OVF", i18nKey: "utilsExportVm", href: "/docs/utils/export-vm" },
          { title: "Import VM from OVA / OVF", i18nKey: "utilsImportVm", href: "/docs/utils/import-vm" },
        ],
      },

      {
        title: "Settings ProxMenux",
        i18nKey: "settingsProxmenux",
        href: "/docs/settings",
        submenu: [
          { title: "Overview", i18nKey: "settingsOverview", href: "/docs/settings" },
          { title: "ProxMenux Monitor", i18nKey: "settingsMonitor", href: "/docs/settings/proxmenux-monitor" },
          { title: "Change Release Channel", i18nKey: "settingsBeta", href: "/docs/settings/beta-program" },
          // "Change Language" is intentionally hidden until the translation
          // install flow is reactivated. The page file at
          // /docs/settings/change-language/page.tsx is preserved so we can
          // restore this entry in a single line edit once the feature ships.
          // { title: "Change Language", i18nKey: "settingsLanguage", href: "/docs/settings/change-language" },
          { title: "Show Version Information", i18nKey: "settingsVersion", href: "/docs/settings/show-version-information" },
          { title: "Uninstall ProxMenux", i18nKey: "settingsUninstall", href: "/docs/settings/uninstall-proxmenux" },
        ],
      },
    ],
  },

  {
    title: "Commands Reference",
    i18nKey: "commandsReference",
    submenu: [
      { title: "Overview", i18nKey: "commandsOverview", href: "/docs/help-info" },
      { title: "Useful System Commands", i18nKey: "commandsSystem", href: "/docs/help-info/system-commands" },
      { title: "VM and CT Management", i18nKey: "commandsVmCt", href: "/docs/help-info/vm-ct-commands" },
      { title: "Storage and Disks", i18nKey: "commandsStorage", href: "/docs/help-info/storage-commands" },
      { title: "Network Commands", i18nKey: "commandsNetwork", href: "/docs/help-info/network-commands" },
      { title: "Updates and Packages", i18nKey: "commandsUpdates", href: "/docs/help-info/update-commands" },
      { title: "GPU Passthrough", i18nKey: "commandsGpu", href: "/docs/help-info/gpu-commands" },
      { title: "ZFS Management", i18nKey: "commandsZfs", href: "/docs/help-info/zfs-commands" },
      { title: "Backup and Restore", i18nKey: "commandsBackup", href: "/docs/help-info/backup-commands" },
      { title: "System CLI Tools", i18nKey: "commandsTools", href: "/docs/help-info/tools-commands" },
    ],
  },

  { title: "Glossary", i18nKey: "glossary", href: "/docs/glossary" },

  {
    title: "About",
    i18nKey: "about",
    submenu: [
      { title: "Overview", i18nKey: "aboutOverview", href: "/docs/about" },
      { title: "FAQ", i18nKey: "aboutFaq", href: "/docs/about/faq" },
      { title: "Contributors", i18nKey: "aboutContributors", href: "/docs/about/contributors" },
      { title: "Contributing", i18nKey: "aboutContributing", href: "/docs/about/contributing" },
      { title: "Code of Conduct", i18nKey: "aboutCodeOfConduct", href: "/docs/about/code-of-conduct" },
    ],
  },

  { title: "External Repositories", i18nKey: "externalRepositories", href: "/docs/external-repositories" },
]

export default function DocSidebar() {
  const pathname = usePathname()
  const [openSections, setOpenSections] = useState<{ [key: string]: boolean }>({})
  const [isMobileMenuOpen, setIsMobileMenuOpen] = useState(false)
  const t = useTranslations("docSidebar")

  // Resolve the visible label for a sidebar item. Prefer the translated
  // entry under `docSidebar.items.<i18nKey>` and fall back to the literal
  // `title` for items that haven't been keyed yet (so adding a new entry
  // without remembering to add a translation still renders the English
  // string instead of throwing).
  const tItem = (item: { title: string; i18nKey?: string }) => {
    if (!item.i18nKey) return item.title
    try {
      return t(`items.${item.i18nKey}`)
    } catch {
      return item.title
    }
  }

  const toggleSection = (title: string) => {
    setOpenSections((prev) => ({ ...prev, [title]: !prev[title] }))
  }

  const toggleMobileMenu = () => {
    setIsMobileMenuOpen(!isMobileMenuOpen)
  }

  useEffect(() => {
    const handleResize = () => {
      if (window.innerWidth >= 768) {
        setIsMobileMenuOpen(false)
      }
    }

    window.addEventListener("resize", handleResize)
    return () => window.removeEventListener("resize", handleResize)
  }, [])

  const renderSubItem = (subItem: SubMenuItem, depth: number) => {
    const hasChildren = !!subItem.submenu && subItem.submenu.length > 0
    if (hasChildren) {
      const descendantHrefs = collectHrefs(subItem.submenu!)
      const containsActivePage =
        subItem.href === pathname || descendantHrefs.includes(pathname)
      const sectionKey = `${subItem.href}__${subItem.title}`
      const isOpen = (openSections[sectionKey] ?? containsActivePage) || false
      return (
        <li key={subItem.href}>
          <div className="flex items-stretch">
            <Link
              href={subItem.href}
              onClick={() => setIsMobileMenuOpen(false)}
              className={`flex-1 block p-2 rounded-l ${
                pathname === subItem.href
                  ? "bg-blue-500 text-white"
                  : containsActivePage
                    ? "bg-blue-50 text-blue-900 font-medium"
                    : "text-gray-700 hover:bg-gray-200 hover:text-gray-900"
              }`}
            >
              {tItem(subItem)}
            </Link>
            <button
              type="button"
              aria-label={isOpen ? "Collapse" : "Expand"}
              onClick={() => toggleSection(sectionKey)}
              className={`px-2 flex items-center rounded-r ${
                containsActivePage && pathname !== subItem.href
                  ? "bg-blue-50 text-blue-900 hover:bg-blue-100"
                  : "text-gray-500 hover:bg-gray-200"
              }`}
            >
              {isOpen ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
            </button>
          </div>
          {isOpen && (
            <ul className="ml-4 mt-2 space-y-2">
              {subItem.submenu!.map((nested) => renderSubItem(nested, depth + 1))}
            </ul>
          )}
        </li>
      )
    }

    return (
      <li key={subItem.href}>
        <Link
          href={subItem.href}
          className={`block p-2 rounded ${
            pathname === subItem.href
              ? "bg-blue-500 text-white"
              : "text-gray-700 hover:bg-gray-200 hover:text-gray-900"
          }`}
          onClick={() => setIsMobileMenuOpen(false)}
        >
          {tItem(subItem)}
        </Link>
      </li>
    )
  }

  const renderMenuItem = (item: MenuItem) => {
    if (item.submenu) {
      const containsActivePage = collectHrefs(item.submenu).includes(pathname)
      const isOpen = (openSections[item.title] ?? containsActivePage) || false
      return (
        <li key={item.title} className="mb-2">
          <button
            onClick={() => toggleSection(item.title)}
            className={`flex items-center justify-between w-full text-left p-2 rounded transition-colors ${
              containsActivePage
                ? "bg-blue-100 text-blue-900 font-semibold hover:bg-blue-200"
                : "hover:bg-gray-200"
            }`}
          >
            <span>{tItem(item)}</span>
            {isOpen ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
          </button>
          {isOpen && (
            <ul className="ml-4 mt-2 space-y-2">
              {item.submenu.map((subItem) => renderSubItem(subItem, 1))}
            </ul>
          )}
        </li>
      )
    } else {
      return (
        <li key={item.href}>
          <Link
            href={item.href!}
            className={`block p-2 rounded ${
              pathname === item.href ? "bg-blue-500 text-white" : "text-gray-700 hover:bg-gray-200 hover:text-gray-900"
            }`}
            onClick={() => setIsMobileMenuOpen(false)}
          >
            {tItem(item)}
          </Link>
        </li>
      )
    }
  }

  return (
    <>
      <div className="lg:hidden fixed top-16 left-0 right-0 z-50 bg-gray-100 border-b border-gray-200">
        <button
          className="w-full p-4 text-left flex items-center justify-between"
          onClick={toggleMobileMenu}
          aria-label="Toggle menu"
        >
          <span className="font-semibold">{t("documentation")}</span>
          {isMobileMenuOpen ? <X className="h-6 w-6" /> : <Menu className="h-6 w-6" />}
        </button>
      </div>
      {/* On desktop (lg+) the sidebar is FIXED to the left so it stays
          in place while the main content scrolls — matches the
          Docusaurus / Hermes docs UX. The layout adds `lg:pl-72` to
          the <main> so the content isn't hidden beneath the sidebar.
          On mobile the sidebar is still a slide-down drawer triggered
          by the hamburger button above. */}
      <nav
        className={`fixed top-[104px] lg:top-16 left-0 w-full lg:w-72 h-[calc(100vh-104px)] lg:h-[calc(100vh-64px)] bg-gray-100 border-r border-gray-200 p-4 lg:p-6 pt-16 lg:pt-6 transform ${
          isMobileMenuOpen ? "translate-y-0" : "-translate-y-full"
        } lg:translate-y-0 transition-transform duration-300 ease-in-out overflow-y-auto z-30`}
      >
        <h2 className="text-lg font-semibold mb-4 text-gray-900 lg:mt-0 sr-only lg:not-sr-only">{t("documentation")}</h2>
        <ul className="space-y-2">{sidebarItems.map(renderMenuItem)}</ul>
      </nav>
    </>
  )
}
