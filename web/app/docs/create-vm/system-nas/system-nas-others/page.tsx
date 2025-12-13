import type { Metadata } from "next"
import Link from "next/link"
import Image from "next/image"
import { ArrowLeft, HardDrive, Settings, Zap, Sliders, Server, Database, ExternalLink } from "lucide-react"

export const metadata: Metadata = {
  title: "ProxMenux Documentation: Other NAS Systems VM Creation",
  description:
    "Guide for creating and configuring virtual machines for TrueNAS SCALE, TrueNAS CORE, OpenMediaVault, and Rockstor on Proxmox VE using ProxMenux.",
  openGraph: {
    title: "ProxMenux Documentation: Other NAS Systems VM Creation",
    description:
      "Guide for creating and configuring virtual machines for TrueNAS SCALE, TrueNAS CORE, OpenMediaVault, and Rockstor on Proxmox VE using ProxMenux.",
    type: "article",
    url: "https://macrimi.github.io/ProxMenux/docs/virtual-machines/system-nas/others",
    images: [
      {
        url: "https://macrimi.github.io/ProxMenux/vm/other-nas-systems.png",
        width: 1200,
        height: 630,
        alt: "ProxMenux Other NAS Systems",
      },
    ],
  },
  twitter: {
    card: "summary_large_image",
    title: "ProxMenux Documentation: Other NAS Systems VM Creation",
    description:
      "Guide for creating and configuring virtual machines for TrueNAS SCALE, TrueNAS CORE, OpenMediaVault, and Rockstor on Proxmox VE using ProxMenux.",
    images: ["https://macrimi.github.io/ProxMenux/vm/other-nas-systems.png"],
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
          src={src || "/placeholder.svg?height=400&width=768&query=NAS systems configuration"}
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

export default function OtherNASSystemsPage() {
  return (
    <div className="container mx-auto py-10 px-4 bg-white text-black">
      <div className="mb-4">

        <div className="flex items-center gap-3 mb-6">
          <HardDrive className="h-8 w-8 mr-2 text-blue-500" />
          <h1 className="text-3xl font-bold text-black">NAS Systems VM Creation</h1>
        </div>

        <div className="space-y-4 mt-6">
          <p className="text-lg text-black">
            ProxMenux provides automated scripts that create and configure virtual machines for various NAS systems on
            Proxmox VE. This documentation covers the VM creation process for TrueNAS SCALE, TrueNAS CORE,
            OpenMediaVault, and Rockstor.
          </p>
        </div>
      </div>


      <div className="mt-8">
        <h2 className="text-2xl font-bold mb-4 text-black">Script Overview</h2>
        <p className="mb-4">
          The VM creation script for NAS systems automates the process of setting up virtual machines optimized for
          running various Network Attached Storage solutions. The script handles all aspects of VM configuration,
          including hardware allocation, disk setup, and boot options.
        </p>

        <p className="mb-4">The script simplifies the VM creation process by offering the following options:</p>
        <ul className="list-disc pl-5 mb-4">
          <li>Selection of default or advanced configuration</li>
          <li>Configuration of CPU, RAM, BIOS, and machine type</li>
          <li>Choice between virtual disk or physical disk passthrough</li>
          <li>Selection of disk interface type (SCSI, SATA, VirtIO, or IDE)</li>
          <li>Automatic configuration of EFI and TPM when required</li>
          <li>Automatic mounting of installation ISO images</li>
        </ul>

        <div className="mt-8">
          <h3 className="text-xl font-semibold mb-3 flex items-center">
            <Settings className="h-5 w-5 mr-2 text-blue-500" />
            Default and Advanced Configuration
          </h3>
          <p className="mb-3">The script offers two configuration modes:</p>

          <h4 className="text-lg font-medium mt-12 mb-2 flex items-center">
            <Zap className="h-5 w-5 mr-2 text-green-500" />
            Default Configuration
          </h4>
          <p className="mb-3">
            If you select default configuration, the script will automatically apply the following values:
          </p>

          <div className="overflow-x-auto mb-4">
            <table className="min-w-full bg-white border border-gray-200">
              <thead>
                <tr>
                  <th className="py-2 px-4 border-b border-gray-200 bg-gray-50 text-left">Parameter</th>
                  <th className="py-2 px-4 border-b border-gray-200 bg-gray-50 text-left">Default Value</th>
                </tr>
              </thead>
              <tbody>
                <tr>
                  <td className="py-2 px-4 border-b border-gray-200">Machine Type</td>
                  <td className="py-2 px-4 border-b border-gray-200">q35</td>
                </tr>
                <tr>
                  <td className="py-2 px-4 border-b border-gray-200">BIOS Type</td>
                  <td className="py-2 px-4 border-b border-gray-200">OVMF (UEFI)</td>
                </tr>
                <tr>
                  <td className="py-2 px-4 border-b border-gray-200">CPU Type</td>
                  <td className="py-2 px-4 border-b border-gray-200">Host</td>
                </tr>
                <tr>
                  <td className="py-2 px-4 border-b border-gray-200">Core Count</td>
                  <td className="py-2 px-4 border-b border-gray-200">2</td>
                </tr>
                <tr>
                  <td className="py-2 px-4 border-b border-gray-200">RAM Size</td>
                  <td className="py-2 px-4 border-b border-gray-200">8192 MB</td>
                </tr>
                <tr>
                  <td className="py-2 px-4 border-b border-gray-200">Bridge</td>
                  <td className="py-2 px-4 border-b border-gray-200">vmbr0</td>
                </tr>
                <tr>
                  <td className="py-2 px-4 border-b border-gray-200">MAC Address</td>
                  <td className="py-2 px-4 border-b border-gray-200">Automatically generated</td>
                </tr>
                <tr>
                  <td className="py-2 px-4 border-b border-gray-200">Start VM on Completion</td>
                  <td className="py-2 px-4 border-b border-gray-200">No</td>
                </tr>
              </tbody>
            </table>
          </div>
          <p className="mb-4">
            If you want to customize the configuration, select the Advanced Settings option in the menu.
          </p>

          <h4 className="text-lg font-medium mt-12 mb-2 flex items-center">
            <Sliders className="h-5 w-5 mr-2 text-orange-500" />
            Advanced Configuration
          </h4>
          <p className="mb-3">
            If you select advanced configuration, the script will allow you to customize each parameter:
          </p>

          <div className="overflow-x-auto mb-4">
            <table className="min-w-full bg-white border border-gray-200">
              <thead>
                <tr>
                  <th className="py-2 px-4 border-b border-gray-200 bg-gray-50 text-left">Parameter</th>
                  <th className="py-2 px-4 border-b border-gray-200 bg-gray-50 text-left">Options</th>
                </tr>
              </thead>
              <tbody>
                <tr>
                  <td className="py-2 px-4 border-b border-gray-200">Machine Type</td>
                  <td className="py-2 px-4 border-b border-gray-200">q35 or i440fx</td>
                </tr>
                <tr>
                  <td className="py-2 px-4 border-b border-gray-200">BIOS Type</td>
                  <td className="py-2 px-4 border-b border-gray-200">OVMF (UEFI) or SeaBIOS (Legacy)</td>
                </tr>
                <tr>
                  <td className="py-2 px-4 border-b border-gray-200">CPU Type</td>
                  <td className="py-2 px-4 border-b border-gray-200">Host or KVM64</td>
                </tr>
                <tr>
                  <td className="py-2 px-4 border-b border-gray-200">Core Count</td>
                  <td className="py-2 px-4 border-b border-gray-200">Number of CPU cores</td>
                </tr>
                <tr>
                  <td className="py-2 px-4 border-b border-gray-200">RAM Size</td>
                  <td className="py-2 px-4 border-b border-gray-200">Amount of memory allocated to the VM</td>
                </tr>
                <tr>
                  <td className="py-2 px-4 border-b border-gray-200">Bridge</td>
                  <td className="py-2 px-4 border-b border-gray-200">Network bridge for connection</td>
                </tr>
                <tr>
                  <td className="py-2 px-4 border-b border-gray-200">MAC Address</td>
                  <td className="py-2 px-4 border-b border-gray-200">Custom MAC address</td>
                </tr>
                <tr>
                  <td className="py-2 px-4 border-b border-gray-200">VLAN</td>
                  <td className="py-2 px-4 border-b border-gray-200">VLAN tag (if used)</td>
                </tr>
                <tr>
                  <td className="py-2 px-4 border-b border-gray-200">MTU</td>
                  <td className="py-2 px-4 border-b border-gray-200">Maximum Transmission Unit size</td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>

        <div className="mt-8">
          <h3 className="text-xl font-semibold mb-3 flex items-center">
            <HardDrive className="h-5 w-5 mr-2 text-blue-500" />
            Disk Interface Selection
          </h3>
          <p className="mb-3">
            Unlike the Synology-specific script, this script allows you to choose the disk interface type for both
            virtual and physical disks:
          </p>

          <div className="overflow-x-auto mb-4">
            <table className="min-w-full bg-white border border-gray-200">
              <thead>
                <tr>
                  <th className="py-2 px-4 border-b border-gray-200 bg-gray-50 text-left">Interface Type</th>
                  <th className="py-2 px-4 border-b border-gray-200 bg-gray-50 text-left">Description</th>
                  <th className="py-2 px-4 border-b border-gray-200 bg-gray-50 text-left">Best For</th>
                </tr>
              </thead>
              <tbody>
                <tr>
                  <td className="py-2 px-4 border-b border-gray-200">SCSI</td>
                  <td className="py-2 px-4 border-b border-gray-200">
                    Modern interface with good performance and features
                  </td>
                  <td className="py-2 px-4 border-b border-gray-200">
                    Recommended for Linux and Windows (includes discard/trim support)
                  </td>
                </tr>
                <tr>
                  <td className="py-2 px-4 border-b border-gray-200">SATA</td>
                  <td className="py-2 px-4 border-b border-gray-200">Standard interface with high compatibility</td>
                  <td className="py-2 px-4 border-b border-gray-200">
                    Good general-purpose choice (includes discard/trim support)
                  </td>
                </tr>
                <tr>
                  <td className="py-2 px-4 border-b border-gray-200">VirtIO</td>
                  <td className="py-2 px-4 border-b border-gray-200">
                    Paravirtualized interface with highest performance
                  </td>
                  <td className="py-2 px-4 border-b border-gray-200">
                    Advanced users seeking maximum performance (includes discard/trim support)
                  </td>
                </tr>
                <tr>
                  <td className="py-2 px-4 border-b border-gray-200">IDE</td>
                  <td className="py-2 px-4 border-b border-gray-200">Legacy interface with maximum compatibility</td>
                  <td className="py-2 px-4 border-b border-gray-200">Legacy systems only (no discard/trim support)</td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>

        <div className="mt-8">
          <h3 className="text-xl font-semibold mb-3 flex items-center">
            <HardDrive className="h-5 w-5 mr-2 text-blue-500" />
            Disk Selection
          </h3>
          <p className="mb-3">
            Once the machine is configured, the script allows you to choose between two types of disks:
          </p>

          <h4 className="text-lg font-medium mt-4 mb-2">Virtual Disk</h4>
          <ul className="list-disc pl-5 mb-4">
            <li>The script lists the storage options available in Proxmox</li>
            <li>The user selects the disk and size in GB</li>
            <li>
              The virtual disk is automatically assigned to the VM using the selected interface type (SCSI, SATA,
              VirtIO, or IDE)
            </li>
            <li>
              Multiple disks can be added and will be assigned sequential device numbers (e.g., scsi0, scsi1, etc.)
            </li>
          </ul>

          <h4 className="text-lg font-medium mt-4 mb-2">Physical Disk Passthrough</h4>
          <ul className="list-disc pl-5 mb-4">
            <li>The script detects all available physical disks</li>
            <li>The user selects the physical disk or disks they want to use</li>
            <li>
              The physical disk is directly assigned to the VM via passthrough using the selected interface type (SCSI,
              SATA, VirtIO, or IDE)
            </li>
            <li>
              Multiple disks can be added and will be assigned sequential device numbers (e.g., scsi0, scsi1, etc.)
            </li>
          </ul>
        </div>

        <div className="mt-8">
          <h3 className="text-xl font-semibold mb-3 flex items-center">
            <Settings className="h-5 w-5 mr-2 text-blue-500" />
            Additional Features
          </h3>

          <h4 className="text-lg font-medium mt-4 mb-2">EFI Disk Configuration</h4>
          <p className="mb-3">When UEFI BIOS (OVMF) is selected, the script automatically configures an EFI disk:</p>
          <ul className="list-disc pl-5 mb-4">
            <li>The script prompts for storage location for the EFI disk</li>
            <li>A 4MB EFI disk is created and configured</li>
            <li>
              The EFI disk is properly formatted based on the storage type (raw format for directory-based storage)
            </li>
          </ul>

          <h4 className="text-lg font-medium mt-4 mb-2">ISO Mounting</h4>
          <p className="mb-3">The script handles ISO mounting for installation:</p>
          <ul className="list-disc pl-5 mb-4">
            <li>The installation ISO is automatically mounted to the ide2 device</li>
            <li>For Windows VMs, VirtIO driver ISO can be automatically downloaded and mounted to ide3</li>
          </ul>

          <h4 className="text-lg font-medium mt-4 mb-2">QEMU Guest Agent</h4>
          <p className="mb-3">The script automatically configures QEMU Guest Agent support:</p>
          <ul className="list-disc pl-5 mb-4">
            <li>Enables the QEMU Guest Agent in the VM configuration</li>
            <li>Sets up the necessary communication channel</li>
            <li>Provides instructions for installing the guest agent inside the VM after installation</li>
          </ul>
        </div>

        <div className="mt-8">
          <h2 className="text-2xl font-bold mb-4 text-black">NAS-Specific Installation Notes</h2>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-6 mt-4">
            <div className="border rounded-lg p-6 bg-gray-50">
              <div className="flex items-center gap-2 mb-3">
                <Database className="h-6 w-6 text-blue-500" />
                <h3 className="text-xl font-semibold">TrueNAS SCALE</h3>
              </div>
              <ul className="list-disc pl-5 space-y-2">
                <li>
                  Recommended interface: <strong>SATA</strong> or <strong>SCSI</strong>
                </li>
                <li>
                  Minimum RAM: <strong>8GB</strong> (16GB+ recommended)
                </li>
                <li>
                  Minimum CPU cores: <strong>2</strong> (4+ recommended)
                </li>
                <li>UEFI boot is recommended</li>
                <li>VirtIO network adapter provides best performance</li>
              </ul>
            </div>

            <div className="border rounded-lg p-6 bg-gray-50">
              <div className="flex items-center gap-2 mb-3">
                <Database className="h-6 w-6 text-blue-500" />
                <h3 className="text-xl font-semibold">TrueNAS CORE</h3>
              </div>
              <ul className="list-disc pl-5 space-y-2">
                <li>
                  Recommended interface: <strong>SATA</strong>
                </li>
                <li>
                  Minimum RAM: <strong>8GB</strong> (16GB+ recommended)
                </li>
                <li>
                  Minimum CPU cores: <strong>2</strong> (4+ recommended)
                </li>
                <li>UEFI boot is recommended</li>
                <li>VirtIO network adapter provides best performance</li>
              </ul>
            </div>

            <div className="border rounded-lg p-6 bg-gray-50">
              <div className="flex items-center gap-2 mb-3">
                <Server className="h-6 w-6 text-blue-500" />
                <h3 className="text-xl font-semibold">OpenMediaVault</h3>
              </div>
              <ul className="list-disc pl-5 space-y-2">
                <li>
                  Recommended interface: <strong>SATA</strong> or <strong>VirtIO</strong>
                </li>
                <li>
                  Minimum RAM: <strong>2GB</strong> (4GB+ recommended)
                </li>
                <li>
                  Minimum CPU cores: <strong>1</strong> (2+ recommended)
                </li>
                <li>Both UEFI and Legacy BIOS are supported</li>
                <li>VirtIO network adapter provides best performance</li>
              </ul>
            </div>

            <div className="border rounded-lg p-6 bg-gray-50">
              <div className="flex items-center gap-2 mb-3">
                <HardDrive className="h-6 w-6 text-blue-500" />
                <h3 className="text-xl font-semibold">Rockstor</h3>
              </div>
              <ul className="list-disc pl-5 space-y-2">
                <li>
                  Recommended interface: <strong>SATA</strong> or <strong>VirtIO</strong>
                </li>
                <li>
                  Minimum RAM: <strong>2GB</strong> (4GB+ recommended)
                </li>
                <li>
                  Minimum CPU cores: <strong>2</strong>
                </li>
                <li>UEFI boot is recommended</li>
                <li>VirtIO network adapter provides best performance</li>
              </ul>
            </div>
          </div>
        </div>

        <div className="mt-12 p-6 bg-gray-50 rounded-lg border border-gray-200">
          <h2 className="text-xl font-bold mb-4 text-black">Installation Process</h2>
          <p className="mb-4">After configuring the VM settings and disk options, the script will:</p>
          <ol className="list-decimal pl-5 space-y-2">
            <li>Create the VM with the specified configuration</li>
            <li>Configure EFI disk if UEFI BIOS is selected</li>
            <li>Create and attach virtual disks or pass through physical disks</li>
            <li>Mount the installation ISO</li>
            <li>Set the boot order (disk first, then ISO)</li>
            <li>Configure the QEMU Guest Agent</li>
            <li>Generate a detailed HTML description for the VM</li>
            <li>Start the VM if requested</li>
          </ol>
          <p className="mt-4">
            Once the VM is created, you can proceed with the installation of your chosen NAS system by following the
            on-screen instructions in the VM console.
          </p>
        </div>

        <div className="mt-12">
          <h2 className="text-2xl font-bold mb-6 text-black">NAS Systems Interfaces</h2>
          <p className="mb-6">
            Below are screenshots of the shell and web interfaces for each NAS system after successful installation:
          </p>

          {/* TrueNAS SCALE */}
          <div className="mb-12">
            <h3 className="text-xl font-semibold mb-4 flex items-center">
              <Database className="h-6 w-6 mr-2 text-blue-500" />
              TrueNAS SCALE
              <a
                href="https://www.truenas.com/truenas-scale/"
                target="_blank"
                rel="noopener noreferrer"
                className="ml-2 text-sm text-blue-500 hover:text-blue-700 flex items-center"
              >
                Official Website <ExternalLink className="h-3.5 w-3.5 ml-1" />
              </a>
            </h3>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
              <div>
                <h4 className="font-medium mb-2">Shell Interface</h4>
                <div className="border rounded-md overflow-hidden">
                  <Image
                    src="https://macrimi.github.io/ProxMenux/vm/truenas/truenas-scale-shell.png"
                    alt="TrueNAS SCALE Shell Interface"
                    width={600}
                    height={400}
                    className="w-full"
                  />
                </div>
              </div>
              <div>
                <h4 className="font-medium mb-2">Web Interface</h4>
                <div className="border rounded-md overflow-hidden">
                  <Image
                    src="https://macrimi.github.io/ProxMenux/vm/truenas/truenas-scale-web.png"
                    alt="TrueNAS SCALE Web Interface"
                    width={600}
                    height={400}
                    className="w-full"
                  />
                </div>
              </div>
            </div>
          </div>

          {/* TrueNAS CORE */}
          <div className="mb-12">
            <h3 className="text-xl font-semibold mb-4 flex items-center">
              <Database className="h-6 w-6 mr-2 text-blue-500" />
              TrueNAS CORE
              <a
                href="https://www.truenas.com/truenas-core/"
                target="_blank"
                rel="noopener noreferrer"
                className="ml-2 text-sm text-blue-500 hover:text-blue-700 flex items-center"
              >
                Official Website <ExternalLink className="h-3.5 w-3.5 ml-1" />
              </a>
            </h3>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
              <div>
                <h4 className="font-medium mb-2">Shell Interface</h4>
                <div className="border rounded-md overflow-hidden">
                  <Image
                    src="https://macrimi.github.io/ProxMenux/vm/truenas/truenas-core-shell.png"
                    alt="TrueNAS CORE Shell Interface"
                    width={600}
                    height={400}
                    className="w-full"
                  />
                </div>
              </div>
              <div>
                <h4 className="font-medium mb-2">Web Interface</h4>
                <div className="border rounded-md overflow-hidden">
                  <Image
                    src="https://macrimi.github.io/ProxMenux/vm/truenas/truenas-core-web.png"
                    alt="TrueNAS CORE Web Interface"
                    width={600}
                    height={400}
                    className="w-full"
                  />
                </div>
              </div>
            </div>
          </div>

          {/* OpenMediaVault */}
          <div className="mb-12">
            <h3 className="text-xl font-semibold mb-4 flex items-center">
              <Server className="h-6 w-6 mr-2 text-blue-500" />
              OpenMediaVault
              <a
                href="https://www.openmediavault.org"
                target="_blank"
                rel="noopener noreferrer"
                className="ml-2 text-sm text-blue-500 hover:text-blue-700 flex items-center"
              >
                Official Website <ExternalLink className="h-3.5 w-3.5 ml-1" />
              </a>
            </h3>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
              <div>
                <h4 className="font-medium mb-2">Shell Interface</h4>
                <div className="border rounded-md overflow-hidden">
                  <Image
                    src="https://macrimi.github.io/ProxMenux/vm/openmediavault/openmediavault-shell.png"
                    alt="OpenMediaVault Shell Interface"
                    width={600}
                    height={400}
                    className="w-full"
                  />
                </div>
              </div>
              <div>
                <h4 className="font-medium mb-2">Web Interface</h4>
                <div className="border rounded-md overflow-hidden">
                  <Image
                    src="https://macrimi.github.io/ProxMenux/vm/openmediavault/openmediavault-web.png"
                    alt="OpenMediaVault Web Interface"
                    width={600}
                    height={400}
                    className="w-full"
                  />
                </div>
              </div>
            </div>
          </div>

          {/* Rockstor */}
          <div className="mb-12">
            <h3 className="text-xl font-semibold mb-4 flex items-center">
              <HardDrive className="h-6 w-6 mr-2 text-blue-500" />
              Rockstor
              <a
                href="https://rockstor.com"
                target="_blank"
                rel="noopener noreferrer"
                className="ml-2 text-sm text-blue-500 hover:text-blue-700 flex items-center"
              >
                Official Website <ExternalLink className="h-3.5 w-3.5 ml-1" />
              </a>
            </h3>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
              <div>
                <h4 className="font-medium mb-2">Shell Interface</h4>
                <div className="border rounded-md overflow-hidden">
                  <Image
                    src="https://macrimi.github.io/ProxMenux/vm/rockstor/rockstor-shell.png"
                    alt="Rockstor Shell Interface"
                    width={600}
                    height={400}
                    className="w-full"
                  />
                </div>
              </div>
              <div>
                <h4 className="font-medium mb-2">Web Interface</h4>
                <div className="border rounded-md overflow-hidden">
                  <Image
                    src="https://macrimi.github.io/ProxMenux/vm/rockstor/rockstor-web.png"
                    alt="Rockstor Web Interface"
                    width={600}
                    height={400}
                    className="w-full"
                  />
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
