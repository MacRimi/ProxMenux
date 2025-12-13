"use client"

import Image from "next/image"
import CopyableCode from "@/components/CopyableCode"
import { Monitor, Settings, Zap, Sliders, HardDrive, ExternalLink, FileCode, Server, Terminal, Cloud } from "lucide-react"


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
          src={src || "/placeholder.svg?height=400&width=768&query=Linux VM configuration"}
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

export default function LinuxVMContent() {
  return (
    <div className="container mx-auto py-10 px-4 bg-white text-black">
      <div className="mb-4">
        <div className="flex items-center gap-3 mb-6">
          <Monitor className="h-8 w-8 mr-2 text-blue-500" />
          <h1 className="text-3xl font-bold text-black">Linux VM Creator Script</h1>
        </div>

        <div className="space-y-4 mt-6">
          <p className="text-lg text-black">
            ProxMenux provides automated scripts that create and configure Linux virtual machines on Proxmox VE. These
            scripts simplify the process by handling the necessary configurations and optimizations for various Linux
            distributions, including Ubuntu, Debian, Fedora, and many others.
          </p>
        </div>
      </div>

      <ImageWithCaption
        src="/images/design-mode/menu_linux.png"
        alt="Linux VM Menu"
        caption="Linux VM Creation Menu in ProxMenux"
      />

      <div className="mt-8">
        <h2 className="text-2xl font-bold mb-4 text-black">Script Overview</h2>
        <p className="mb-4">
          The Linux VM creation script automates the process of setting up virtual machines optimized for running Linux
          operating systems. The script handles all aspects of VM configuration, including hardware allocation, disk
          setup, and boot options.
        </p>

        <p className="mb-4">The script simplifies the VM creation process by offering the following options:</p>
        <ul className="list-disc pl-5 mb-4">
          <li>Selection of default or advanced configuration</li>
          <li>Configuration of CPU, RAM, BIOS, and machine type</li>
          <li>Choice between virtual disk or physical disk passthrough</li>
          <li>Selection of disk interface type (SCSI, SATA, VirtIO, or IDE)</li>
          <li>Automatic configuration of EFI for UEFI boot</li>
          <li>Multiple installation methods: official ISOs, Cloud-Init, or local ISO</li>
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
                  <td className="py-2 px-4 border-b border-gray-200">4096 MB</td>
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
            The script allows you to choose the disk interface type for both virtual and physical disks:
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
                    Recommended for most Linux distributions (includes discard/trim support)
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
                    Best performance for Linux (includes discard/trim support)
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
          <p className="mb-3">
            When UEFI BIOS (OVMF) is selected, the script automatically configures an EFI system disk:
          </p>
          <ul className="list-disc pl-5 mb-4">
            <li>You'll be prompted to select the storage location for the EFI disk</li>
            <li>A 4MB EFI disk is created and attached to the VM</li>
            <li>
              The disk is formatted appropriately based on the selected storage backend (e.g., raw format for
              directory-based storage)
            </li>
          </ul>

          <h4 className="text-lg font-medium mt-4 mb-2">ISO Mounting</h4>
          <p className="mb-3">The script also handles ISO mounting automatically:</p>
          <ul className="list-disc pl-5 mb-4">
            <li>
              The installation ISO is mounted to the first available IDE slot (typically <code>ide2</code>)
            </li>
            <li>For VirtIO disk interfaces, the VirtIO drivers ISO can be mounted if needed</li>
          </ul>

          <h4 className="text-lg font-medium mt-4 mb-2">QEMU Guest Agent</h4>
          <p className="mb-3">The script automatically configures QEMU Guest Agent support:</p>
          <ul className="list-disc pl-5 mb-4">
            <li>Enables the QEMU Guest Agent in the VM configuration</li>
            <li>Sets up the necessary communication channel</li>
            <li>Provides instructions for installing the guest agent inside the VM after installation</li>
          </ul>
        </div>

        <div className="mt-12">
          <h2 className="text-2xl font-bold mb-6 text-black">Linux Installation Options</h2>
          <p className="mb-6">ProxMenux offers three methods for installing Linux on your virtual machine:</p>

          <div className="space-y-24 mt-8">
            <div>
              <div className="flex items-center gap-3 mb-8">
                <Server className="h-12 w-12 text-blue-500" />
                <h3 className="text-xl font-semibold">Official ISO Installation</h3>
              </div>

              <p className="mb-4">
                This option allows you to install Linux using official distribution ISOs. ProxMenux provides a curated
                list of popular Linux distributions that can be automatically downloaded and used for installation.
              </p>

              <h4 className="font-medium mb-2">Available Distributions:</h4>
              <ul className="list-disc pl-5 mb-4 space-y-1">
                <li>Ubuntu (Desktop & Server)</li>
                <li>Debian (Full & Netinst)</li>
                <li>Fedora Workstation</li>
                <li>Rocky Linux</li>
                <li>Linux Mint</li>
                <li>openSUSE Leap</li>
                <li>Alpine Linux</li>
                <li>Kali Linux</li>
                <li>Manjaro</li>
              </ul>

              <div className="mt-4">
                <ImageWithCaption
                  src="/images/design-mode/distro_linux.png"
                  alt="Linux Distribution Selection"
                  caption="Linux Distribution Selection in ProxMenux"
                />
              </div>
            </div>

            <div>
              <div className="flex items-center gap-3 mb-8">
                <Cloud className="h-12 w-12 text-blue-500" />
                <h3 className="text-xl font-semibold">Cloud-Init Installation</h3>
              </div>

              <p className="mb-4">
                This option uses Cloud-Init to automate the installation process. It's faster than traditional
                installation and provides a pre-configured system ready to use.
              </p>

              <h4 className="font-medium mb-2">Available Cloud-Init Images:</h4>
              <ul className="list-disc pl-5 mb-4 space-y-1">
                <li>Arch Linux</li>
                <li>Debian 12</li>
                <li>Ubuntu 22.04 LTS</li>
                <li>Ubuntu 24.04 LTS</li>
                <li>Ubuntu 24.10</li>
              </ul>

              <div className="mt-4 bg-blue-50 border border-blue-200 rounded-md p-4">
                <div className="flex items-center gap-2 mb-2">
                  <ExternalLink className="h-4 w-4 text-blue-500" />
                  <h5 className="font-medium text-blue-800">External Scripts</h5>
                </div>
                <p className="text-sm text-blue-800">
                  Cloud-Init installations use external helper scripts from the community. For more information, visit:
                </p>
                <a
                  href="https://community-scripts.github.io/ProxmoxVE/"
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-sm text-blue-600 hover:text-blue-800 flex items-center mt-1"
                >
                  community-scripts.github.io/ProxmoxVE
                  <ExternalLink className="h-3 w-3 ml-1" />
                </a>
              </div>
            </div>

            <div>
              <div className="flex items-center gap-3 mb-8">
                <HardDrive className="h-12 w-12 text-blue-500" />
                <h3 className="text-xl font-semibold">Local ISO Installation</h3>
              </div>

              <p className="mb-4">
                This option allows you to use your own Linux ISO file that's already uploaded to your Proxmox server's
                local storage. Ideal if you have custom or specific Linux installation media.
              </p>

              <div className="mt-4">
                <ImageWithCaption
                  src="/images/design-mode/local-store.png"
                  alt="Local ISO Selection Menu"
                  caption="Local ISO Selection Menu in ProxMenux"
                />
              </div>
            </div>
          </div>
        </div>

        <div className="mt-24 p-6 bg-gray-50 rounded-lg border border-gray-200">
          <h2 className="text-xl font-bold mb-4 text-black">Installation Process</h2>
          <p className="mb-4">
            After configuring the VM settings and selecting your installation method, the script will:
          </p>
          <ol className="list-decimal pl-5 space-y-2">
            <li>Create the VM with the specified configuration</li>
            <li>Configure EFI disk if UEFI BIOS is selected</li>
            <li>Create and attach virtual disks or pass through physical disks</li>
            <li>Download and mount the Linux ISO (if using official distribution) or mount your local ISO</li>
            <li>Set the boot order (disk first, then ISO)</li>
            <li>Configure the QEMU Guest Agent</li>
            <li>Start the VM if requested</li>
          </ol>
        </div>

        <div className="mt-12 p-6 bg-gray-50 rounded-lg border border-gray-200">
          <h2 className="text-xl font-bold mb-4 text-black flex items-center">
            <Terminal className="h-6 w-6 mr-2 text-blue-500" />
            Linux-Specific Tips
          </h2>

          <div className="space-y-6">
            <div>
              <h3 className="text-lg font-medium mb-2">Installing QEMU Guest Agent</h3>
              <p className="mb-3">
                For better integration with Proxmox, it's recommended to install the QEMU Guest Agent inside your Linux
                VM. This enables features like proper shutdown, file system freeze for snapshots, and more accurate
                memory reporting.
              </p>

              <div className="bg-gray-100 p-4 rounded-md">
                <h4 className="font-medium mb-2">Installation commands by distribution:</h4>
                  <div className="space-y-3">
                    <div>
                      
                      <p className="font-medium text-sm">Debian / Ubuntu:</p>
                      <CopyableCode
                        code={encodeURIComponent(`sudo apt update && sudo apt install qemu-guest-agent -y
                  sudo systemctl enable qemu-guest-agent
                  sudo systemctl start qemu-guest-agent`)}
                      />
                    </div>

                    <div>
                      <p className="font-medium text-sm">Fedora / CentOS / Rocky Linux:</p>
                      <CopyableCode
                        code={encodeURIComponent(`sudo dnf install qemu-guest-agent -y
                  sudo systemctl enable qemu-guest-agent
                  sudo systemctl start qemu-guest-agent`)}
                      />
                    </div>

                    <div>
                      <p className="font-medium text-sm">Arch Linux:</p>
                      <CopyableCode
                        code={encodeURIComponent(`sudo pacman -S qemu-guest-agent
                  sudo systemctl enable qemu-guest-agent
                  sudo systemctl start qemu-guest-agent`)}
                      />
                    </div>

                    <div>
                      <p className="font-medium text-sm">openSUSE:</p>
                      <CopyableCode
                        code={encodeURIComponent(`sudo zypper install qemu-guest-agent
                  sudo systemctl enable qemu-guest-agent
                  sudo systemctl start qemu-guest-agent`)}
                      />
                    </div>
                  </div>
              </div>
            </div>

            <div>
              <h3 className="text-lg font-medium mb-2">VirtIO Drivers in Linux</h3>
              <p className="mb-3">
                Most modern Linux distributions include VirtIO drivers by default, which means you can use VirtIO disk
                and network interfaces without additional configuration. This provides the best performance for your
                Linux VM.
              </p>

              <div className="bg-yellow-50 border-l-4 border-yellow-400 p-4">
                <p className="font-medium">Note:</p>
                <p>
                  If you're using an older Linux distribution (pre-2.6.25 kernel) and VirtIO disk interfaces, you might
                  need to load the VirtIO modules during installation. In such cases, you may need to provide a driver
                  disk or use SATA/SCSI interfaces instead.
                </p>
              </div>
            </div>

            <div>
              <h3 className="text-lg font-medium mb-2">Optimizing Linux VMs</h3>
              <ul className="list-disc pl-5 space-y-2">
                <li>
                  <strong>Enable disk trim/discard:</strong> To enable TRIM support for better SSD performance, add the{" "}
                  <code className="bg-gray-100 px-1 py-0.5 rounded">discard</code> mount option in{" "}
                  <code className="bg-gray-100 px-1 py-0.5 rounded">/etc/fstab</code> for your partitions.
                </li>
                <li>
                  <strong>CPU type selection:</strong> For best performance, use the "host" CPU type which passes
                  through all CPU features from your host to the VM.
                </li>
                <li>
                  <strong>Memory ballooning:</strong> Enable memory ballooning to allow dynamic memory allocation. The
                  balloon driver is included in most Linux distributions.
                </li>
                <li>
                  <strong>Use VirtIO network interfaces:</strong> VirtIO network interfaces provide better performance
                  than emulated network cards.
                </li>
              </ul>
            </div>

          </div>
        </div>

       <div className="mt-8 p-6 bg-gray-50 rounded-lg border border-gray-200">
          <h2 id="other-linux-systems" className="text-xl font-bold mb-4 text-black">
            Other Linux Systems
          </h2>
          <p className="mb-4">
            ProxMenux provides access to external community scripts that allow the creation of specialized Linux virtual machines for specific use cases:
          </p>


          <div className="grid grid-cols-1 md:grid-cols-2 gap-6 mt-4">
            <div className="border rounded-lg p-4 bg-white">
              <div className="flex items-center gap-2 mb-2">
                <Server className="h-5 w-5 text-blue-500" />
                <h3 className="font-semibold">Home Assistant OS VM (HAOS)</h3>
              </div>
              <p className="text-sm mb-3">
                Create a virtual machine that runs Home Assistant OS using a helper script from the community. Ideal for smart home automation.
              </p>
            </div>

            <div className="border rounded-lg p-4 bg-white">
              <div className="flex items-center gap-2 mb-2">
                <Terminal className="h-5 w-5 text-blue-500" />
                <h3 className="font-semibold">Docker VM (Debian + SSH + Docker)</h3>
              </div>
              <p className="text-sm mb-3">
                Deploy a lightweight Debian-based virtual machine with Docker and SSH pre-installed using an external script.
              </p>
            </div>
          </div>

          <div className="mt-6 bg-blue-50 border border-blue-200 rounded-md p-4">
            <div className="flex items-center gap-2 mb-2">
              <ExternalLink className="h-4 w-4 text-blue-500" />
              <h5 className="font-medium text-blue-800">External Scripts</h5>
            </div>
            <p className="text-sm text-blue-800">
              These installations are handled by community-maintained scripts. For more information or to contribute, visit:
            </p>
            <a
              href="https://community-scripts.github.io/ProxmoxVE/"
              target="_blank"
              rel="noopener noreferrer"
              className="text-sm text-blue-600 hover:text-blue-800 flex items-center mt-1"
            >
              community-scripts.github.io/ProxmoxVE
              <ExternalLink className="h-3 w-3 ml-1" />
            </a>
          </div>
        </div>
      </div>
    </div>
  )
}
