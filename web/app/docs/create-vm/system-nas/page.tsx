import type React from "react"
import type { Metadata } from "next"
import Link from "next/link"
import Image from "next/image"
import { HardDrive, Info, Database, Server, MonitorIcon, Star, Cpu, Github } from "lucide-react"
import { Badge } from "@/components/ui/badge"

export const metadata: Metadata = {
  title: "ProxMenux Documentation: System NAS Virtual Machines",
  description:
    "Guide for creating and configuring NAS virtual machines on Proxmox VE using ProxMenux, including Synology DSM, TrueNAS, and other storage systems.",
  openGraph: {
    title: "ProxMenux Documentation: System NAS Virtual Machines",
    description:
      "Guide for creating and configuring NAS virtual machines on Proxmox VE using ProxMenux, including Synology DSM, TrueNAS, and other storage systems.",
    type: "article",
    url: "https://macrimi.github.io/ProxMenux/docs/virtual-machines/system-nas",
    images: [
      {
        url: "https://macrimi.github.io/ProxMenux/vm/system-nas-menu.png",
        width: 1200,
        height: 630,
        alt: "ProxMenux System NAS Menu",
      },
    ],
  },
  twitter: {
    card: "summary_large_image",
    title: "ProxMenux Documentation: System NAS Virtual Machines",
    description:
      "Guide for creating and configuring NAS virtual machines on Proxmox VE using ProxMenux, including Synology DSM, TrueNAS, and other storage systems.",
    images: ["https://macrimi.github.io/ProxMenux/vm/system-nas-menu.png"],
  },
}

interface ImageWithCaptionProps {
  src: string
  alt: string
  caption: string
}

function ImageWithCaption({ src, alt, caption }: ImageWithCaptionProps) {
  return (
    <div className="flex flex-col items-center w-full max-w-[768px] mx-auto my-4">
      <div className="w-full rounded-md overflow-hidden border border-gray-200">
        <Image
          src={src || "/placeholder.svg"}
          alt={alt}
          width={768}
          height={400}
          style={{ height: "auto" }}
          className="object-contain w-full"
          sizes="(max-width: 768px) 100vw, 768px"
        />
      </div>
      <span className="mt-2 text-sm text-gray-600">{caption}</span>
    </div>
  )
}

interface NASSystemProps {
  name: string
  description: string
  icon: React.ReactNode
  features: string[]
  technicalDetails: string[]
  href: string
  isExternal?: boolean
  externalUrl?: string
}

function NASSystemItem({
  name,
  description,
  icon,
  features,
  technicalDetails,
  href,
  isExternal,
  externalUrl,
}: NASSystemProps) {
  return (
    <div className="border rounded-md mb-6 border-gray-200 overflow-hidden">
      <div className="px-4 py-3 bg-gray-50 border-b border-gray-200 hover:bg-blue-50 transition-colors">
        <div className="flex items-center justify-between">
          {isExternal && externalUrl ? (
            <a href={externalUrl} target="_blank" rel="noopener noreferrer" className="flex items-center gap-3">
              {icon}
              <h3 className="text-lg font-medium text-black hover:text-blue-600">{name}</h3>
            </a>
          ) : (
            <Link href={href} className="flex items-center gap-3">
              {icon}
              <h3 className="text-lg font-medium text-black hover:text-blue-600">{name}</h3>
            </Link>
          )}

          {isExternal && (
            <div className="flex items-center">
              <Badge
                variant="outline"
                className="flex items-center gap-1 bg-gray-100 hover:bg-gray-200 text-gray-800 border-gray-300"
              >
                <Github className="h-3.5 w-3.5 text-gray-700" />
                <span className="text-xs font-medium">External Script</span>
              </Badge>

            </div>
          )}
        </div>
      </div>

      <div className="px-4 py-4">
        <div className="space-y-4">
          <p className="text-gray-700">{description}</p>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div>
              <h4 className="font-semibold mb-2 text-black flex items-center">
                <Star className="h-5 w-5 mr-2 text-green-500" />
                Key Features:
              </h4>
              <ul className="list-disc pl-5 space-y-1 text-gray-700">
                {features.map((feature, index) => (
                  <li key={index}>{feature}</li>
                ))}
              </ul>
            </div>

            <div>
              <h4 className="font-semibold mb-2 text-black flex items-center">
                <Cpu className="h-5 w-5 mr-2 text-purple-500" />
                Technical Details:
              </h4>
              <ul className="list-disc pl-5 space-y-1 text-gray-700">
                {technicalDetails.map((detail, index) => (
                  <li key={index}>{detail}</li>
                ))}
              </ul>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}

export default function SystemNASPage() {
  return (
    <div className="container mx-auto py-10 px-4 bg-white text-black">
      <div className="mb-4">
        <div className="flex items-center gap-3 mb-6">
          <HardDrive className="h-8 w-8 mr-2 text-blue-500" />
          <h1 className="text-3xl font-bold text-black">System NAS Virtual Machines</h1>
        </div>

        <div className="space-y-4 mt-6">
          <p className="text-lg text-black">
            ProxMenux provides automated scripts that create and configure virtual machines for various NAS systems on
            Proxmox VE. These scripts simplify the process by handling the necessary configurations and optimizations
            for each NAS platform.
          </p>
        </div>
      </div>

      <ImageWithCaption
        src="/images/design-mode/system-nas-menu.png"
        alt="System NAS Menu"
        caption="System NAS Menu"
      />

      <div className="mt-8 mb-6">
        <div className="flex items-center gap-2">
          <Info className="h-5 w-5 text-blue-500" />
          <h2 className="text-xl font-semibold text-black">Available NAS Systems</h2>
        </div>
        <p className="mt-2 text-gray-600">
          Select one of the NAS systems below to view detailed documentation on installation and configuration.
        </p>
      </div>

      <div className="mt-6">
        <NASSystemItem
          name="Synology DSM"
          description="Synology DSM (DiskStation Manager) is a popular NAS operating system with a comprehensive set of features for home and business users."
          icon={<HardDrive className="h-6 w-6 text-blue-500" />}
          features={[
            "User-friendly web interface",
            "Extensive app ecosystem",
            "File sharing and synchronization",
            "Media streaming capabilities",
          ]}
          technicalDetails={[
            "Base OS: Linux (Custom)",
            "File Systems: Btrfs, ext4",
            "Virtualization: Yes (Docker)",
            "Hardware Requirements: Moderate",
          ]}
          href="/docs/create-vm/synology"
        />

        <NASSystemItem
          name="TrueNAS SCALE"
          description="TrueNAS SCALE is a Linux-based version of TrueNAS that combines the simplicity of TrueNAS with the scalability of Linux, including support for containerization and hyperconvergence."
          icon={<Database className="h-6 w-6 text-blue-500" />}
          features={[
            "Linux-based (Debian)",
            "Docker container support",
            "Kubernetes integration",
            "Scale-out clustering capabilities",
          ]}
          technicalDetails={[
            "Base OS: Debian Linux",
            "File System: ZFS",
            "Virtualization: Yes (KVM)",
            "Hardware Requirements: High",
          ]}
          href="/docs/create-vm/system-nas/system-nas-others"
        />

        <NASSystemItem
          name="TrueNAS CORE"
          description="TrueNAS CORE (formerly FreeNAS) is a FreeBSD-based open-source NAS operating system that provides file and object storage with enterprise-grade reliability."
          icon={<Database className="h-6 w-6 text-blue-500" />}
          features={["FreeBSD-based", "ZFS file system", "Snapshots and replication", "Encryption"]}
          technicalDetails={[
            "Base OS: FreeBSD",
            "File System: ZFS",
            "Virtualization: Yes (Jails)",
            "Hardware Requirements: Moderate to High",
          ]}
          href="/docs/create-vm/system-nas/system-nas-others"
        />

        <NASSystemItem
          name="OpenMediaVault"
          description="OpenMediaVault (OMV) is a Debian-based NAS solution with a lightweight web interface designed for small home offices and personal use."
          icon={<Server className="h-6 w-6 text-blue-500" />}
          features={[
            "Modular plugin architecture",
            "Multiple filesystem support",
            "Docker support via plugins",
            "Low resource requirements",
          ]}
          technicalDetails={[
            "Base OS: Debian Linux",
            "File Systems: ext4, XFS, Btrfs",
            "Virtualization: Yes (via plugins)",
            "Hardware Requirements: Low",
          ]}
          href="/docs/create-vm/system-nas/system-nas-others"
        />

        <NASSystemItem
          name="Rockstor"
          description="Rockstor is a Linux-based NAS solution built on CentOS with the BTRFS file system, offering advanced storage features with a user-friendly interface."
          icon={<HardDrive className="h-6 w-6 text-blue-500" />}
          features={[
            "BTRFS file system",
            "Web-based UI",
            "Docker-based app framework (Rock-ons)",
            "Snapshots and replication",
          ]}
          technicalDetails={[
            "Base OS: openSUSE based",
            "File System: Btrfs",
            "Virtualization: Yes (Docker)",
            "Hardware Requirements: Moderate",
          ]}
          href="/docs/create-vm/system-nas/system-nas-others"
        />

        <NASSystemItem
          name="ZimaOS"
          description="ZimaOS is a lightweight, customizable NAS operating system designed for simplicity and performance, with a focus on media streaming and home automation."
          icon={<MonitorIcon className="h-6 w-6 text-blue-500" />}
          features={[
            "Low resource footprint",
            "Docker support",
            "Media streaming optimization",
            "Home automation integration",
          ]}
          technicalDetails={[
            "Base OS: ROGGER proxmox-zimaos",
            "File Systems: ext4, XFS",
            "Virtualization: Yes (Docker)",
            "Hardware Requirements: Low",
          ]}
          href="/docs/virtual-machines/system-nas/zimaos"
          isExternal={true}
          externalUrl="https://github.com/R0GGER/proxmox-zimaos"
        />
      </div>

      <div className="mt-12 p-6 bg-gray-50 rounded-lg border border-gray-200">
        <h2 className="text-xl font-bold mb-4 text-black">About NAS Virtual Machines</h2>
        <div className="space-y-4">
          <p className="text-black">
            Network Attached Storage (NAS) systems provide file-level data storage services to other devices on the
            network. Running NAS software in a virtual machine on Proxmox VE allows you to leverage the reliability and
            management features of Proxmox while providing flexible storage solutions.
          </p>

          <p className="text-black">
            ProxMenux simplifies the creation of NAS virtual machines by automating the configuration process, including
            network settings, storage allocation, and system optimization for each specific NAS platform.
          </p>
        </div>
      </div>
    </div>
  )
}
