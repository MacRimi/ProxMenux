import type React from "react"
import type { Metadata } from "next"
import Link from "next/link"
import Image from "next/image"
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from "@/components/ui/card"
import {
  ArrowRight,
  Terminal,
  HardDrive,
  Network,
  Package,
  Cpu,
  Database,
  Archive,
  PenToolIcon as Tool,
  BookOpenCheck,
  Book,
} from "lucide-react"


export const metadata: Metadata = {
  title: "ProxMenux Documentation: Help and Info",
  description:
    "Comprehensive collection of useful commands and references for Proxmox VE, organized by category for easy access and quick reference.",
  openGraph: {
    title: "ProxMenux Documentation: Help and Info",
    description:
      "Comprehensive collection of useful commands and references for Proxmox VE, organized by category for easy access and quick reference.",
    type: "article",
    url: "https://macrimi.github.io/ProxMenux/docs/help-info",
    images: [
      {
        url: "https://macrimi.github.io/ProxMenux/help/help-info-menu.png",
        width: 1200,
        height: 630,
        alt: "ProxMenux Help and Info Menu",
      },
    ],
  },
  twitter: {
    card: "summary_large_image",
    title: "ProxMenux Documentation: Help and Info",
    description:
      "Comprehensive collection of useful commands and references for Proxmox VE, organized by category for easy access and quick reference.",
    images: ["https://macrimi.github.io/ProxMenux/help/help-info-menu.png"],
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
          height={0}
          style={{ height: "auto" }}
          className="object-contain w-full"
          sizes="(max-width: 768px) 100vw, 768px"
        />
      </div>
      <span className="mt-2 text-sm text-gray-600">{caption}</span>
    </div>
  )
}

export default function HelpAndInfoPage() {
  return (
    <div className="container mx-auto py-10 px-4 bg-white text-black">
      <div className="mb-10">
        <div className="flex items-center gap-3 mb-6">
          <BookOpenCheck className="h-8 w-8 mr-2 text-blue-500" />
          <h1 className="text-3xl font-bold text-black">Help and Info Menu</h1>
        </div>

        <div className="space-y-4 mt-6">
          <p className="text-lg text-black">
            ProxMenux provides an interactive command reference menu for Proxmox VE through a dialog-based interface.
            Select one of the categories below to explore the available commands.
          </p>


          <p className="text-black">
            Each category contains commands with descriptions, making it easier to find exactly what
            you need when you need it. This eliminates the need to remember complex command syntax or search through
            documentation when performing administrative tasks.
          </p>
        </div>
      </div>

      <ImageWithCaption
        src="/images/design-mode/help-info-menu.png"
        alt="Help and Info Menu"
        caption="Help and Info Menu"
      />

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6 mt-10">
        <CommandCard
          title="Useful System Commands"
          description="Basic commands to manage and monitor the Proxmox system"
          icon={<Terminal className="h-8 w-8 text-blue-500" />}
          href="/docs/help-info/system-commands"
        />

        <CommandCard
          title="VM and CT Management"
          description="Commands to manage virtual machines and containers"
          icon={<Cpu className="h-8 w-8 text-blue-500" />}
          href="/docs/help-info/vm-ct-commands"
        />

        <CommandCard
          title="Storage and Disks"
          description="Commands to manage storage devices and partitions"
          icon={<HardDrive className="h-8 w-8 text-blue-500" />}
          href="/docs/help-info/storage-commands"
        />

        <CommandCard
          title="Network Commands"
          description="Commands to configure and monitor the network"
          icon={<Network className="h-8 w-8 text-blue-500" />}
          href="/docs/help-info/network-commands"
        />

        <CommandCard
          title="Updates and Packages"
          description="Commands to update the system and manage packages"
          icon={<Package className="h-8 w-8 text-blue-500" />}
          href="/docs/help-info/update-commands"
        />

        <CommandCard
          title="GPU Passthrough"
          description="Commands to configure and manage GPU passthrough"
          icon={<Cpu className="h-8 w-8 text-blue-500" />}
          href="/docs/help-info/gpu-commands"
        />

        <CommandCard
          title="ZFS Management"
          description="Commands to manage ZFS file systems"
          icon={<Database className="h-8 w-8 text-blue-500" />}
          href="/docs/help-info/zfs-commands"
        />

        <CommandCard
          title="Backup and Restore"
          description="Commands to perform and manage backups"
          icon={<Archive className="h-8 w-8 text-blue-500" />}
          href="/docs/help-info/backup-commands"
        />

        <CommandCard
          title="System CLI Tools"
          description="Useful command-line tools for administration"
          icon={<Tool className="h-8 w-8 text-blue-500" />}
          href="/docs/help-info/tools-commands"
        />
      </div>

      <div className="mt-16 mb-6">
        <div className="flex items-center gap-3 mb-6">
          <Book className="h-8 w-8 mr-2 text-blue-500" />
          <h2 className="text-2xl font-bold text-black">ProxMenux Guides</h2>
        </div>

        <p className="text-lg mb-6 text-black">
          Check out the guides section for additional resources, tutorials, and documentation to help you get the most
          out of Proxmox VE and ProxMenux.
        </p>

        <div className="flex justify-center">
          <Link
            href="/guides"
            className="inline-flex items-center px-6 py-3 bg-blue-500 text-white rounded-md hover:bg-blue-600 transition-colors"
          >
            View Guides <ArrowRight className="ml-2 h-5 w-5" />
          </Link>
        </div>
      </div>
    </div>
  )
}

interface CommandCardProps {
  title: string
  description: string
  icon: React.ReactNode
  href: string
}

function CommandCard({ title, description, icon, href }: CommandCardProps) {
  return (
    <Card className="transition-all duration-300 hover:shadow-md hover:border-blue-300 bg-white text-black border-2 border-gray-200">
      <CardHeader>
        <div className="flex items-center gap-3">
          {icon}
          <CardTitle className="text-xl text-black">{title}</CardTitle>
        </div>
      </CardHeader>
      <CardContent>
        <CardDescription className="text-base text-gray-600">{description}</CardDescription>
      </CardContent>
      <CardFooter>
        <Link href={href} className="flex items-center text-blue-500 hover:text-blue-700 transition-colors">
          View commands <ArrowRight className="ml-2 h-4 w-4" />
        </Link>
      </CardFooter>
    </Card>
  )
}
