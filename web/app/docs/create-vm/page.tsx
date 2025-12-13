import type React from "react"
import type { Metadata } from "next"
import Link from "next/link"
import Image from "next/image"
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from "@/components/ui/card"
import { ArrowRight, Server, ComputerIcon as Windows, LaptopIcon as Linux, HardDrive, Monitor } from "lucide-react"

export const metadata: Metadata = {
  title: "ProxMenux Documentation: Virtual Machines",
  description:
    "Comprehensive guide for creating and configuring virtual machines on Proxmox VE using ProxMenux, with dedicated sections for NAS, Windows, and Linux systems.",
  openGraph: {
    title: "ProxMenux Documentation: Virtual Machines",
    description:
      "Comprehensive guide for creating and configuring virtual machines on Proxmox VE using ProxMenux, with dedicated sections for NAS, Windows, and Linux systems.",
    type: "article",
    url: "https://macrimi.github.io/ProxMenux/docs/virtual-machines",
    images: [
      {
        url: "https://macrimi.github.io/ProxMenux/vm/vm-creation-menu.png",
        width: 1200,
        height: 630,
        alt: "ProxMenux Virtual Machines Menu",
      },
    ],
  },
  twitter: {
    card: "summary_large_image",
    title: "ProxMenux Documentation: Virtual Machines",
    description:
      "Comprehensive guide for creating and configuring virtual machines on Proxmox VE using ProxMenux, with dedicated sections for NAS, Windows, and Linux systems.",
    images: ["https://macrimi.github.io/ProxMenux/vm/vm-creation-menu.png"],
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

export default function VirtualMachinesPage() {
  return (
    <div className="container mx-auto py-10 px-4 bg-white text-black">
      <div className="mb-10">
        <div className="flex items-center gap-3 mb-6">
          <Server className="h-8 w-8 mr-2 text-blue-500" />
          <h1 className="text-3xl font-bold text-black">Virtual Machines Menu</h1>
        </div>

        <div className="space-y-4 mt-6">
          <p className="text-lg text-black">
            ProxMenux provides an automated system for creating and configuring virtual machines on Proxmox VE through
            an interactive menu interface. Select one of the categories below to explore the available VM creation
            options.
          </p>

          <p className="text-black">
            Each category contains specialized scripts and configurations designed to simplify the process of creating
            virtual machines for different operating systems and use cases. This eliminates the need to remember complex
            command syntax or manually configure VMs when deploying new systems.
          </p>
        </div>
      </div>

      <ImageWithCaption
        src="https://macrimi.github.io/ProxMenux/vm/vm-creation-menu.png"
        alt="Virtual Machines Creation Menu"
        caption="Virtual Machines Creation Menu"
      />

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-2 gap-6 mt-10">
        <VMCard
          title="System NAS"
          description="Create and configure NAS virtual machines including Synology DSM, TrueNAS, and other storage systems"
          icon={<HardDrive className="h-8 w-8 text-blue-500" />}
          href="/docs/create-vm/system-nas"
        />

        <VMCard
          title="System Windows"
          description="Deploy Windows virtual machines with optimized configurations for Windows"
          icon={<Windows className="h-8 w-8 text-blue-500" />}
          href="/docs/create-vm/system-windows"
        />

        <VMCard
          title="System Linux"
          description="Create Linux virtual machines with configurations for popular distributions like Ubuntu, Debian, and CentOS"
          icon={<Linux className="h-8 w-8 text-blue-500" />}
          href="/docs/create-vm/system-linux"
        />

        <VMCard
          title="Other Linux Systems"
          description="Deploy specialized Linux distributions and configurations for specific use cases"
          icon={<Server className="h-8 w-8 text-blue-500" />}
          href="/docs/create-vm/system-linux#other-linux-systems"
        />


        <VMCard
          title="System macOS"
          description="Easily install macOS on Proxmox VE with just a few steps! This guide provides the simplest and most effective way to set up macOS on Proxmox, whether you're using AMD or Intel hardware. This is an external script; for more information, visit the project's page."
          icon={<Monitor className="h-8 w-8 text-blue-500" />}
          href="https://osx-proxmox.com"
          externalLink 
        />
      </div>
    </div>
  )
}

interface VMCardProps {
  title: string
  description: string
  icon: React.ReactNode
  href: string
  externalLink?: boolean 
}

function VMCard({ title, description, icon, href, externalLink = false }: VMCardProps) {
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
        {externalLink ? (
          <a
            href={href}
            target="_blank"
            rel="noopener noreferrer"
            className="flex items-center text-blue-500 hover:text-blue-700 transition-colors"
          >
            View details <ArrowRight className="ml-2 h-4 w-4" />
          </a>
        ) : (
          <Link
            href={href}
            className="flex items-center text-blue-500 hover:text-blue-700 transition-colors"
          >
            View details <ArrowRight className="ml-2 h-4 w-4" />
          </Link>
        )}
      </CardFooter>
    </Card>
  )
}
