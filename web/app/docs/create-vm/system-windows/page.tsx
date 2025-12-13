import type { Metadata } from "next"
import Link from "next/link"
import Image from "next/image"
import { ArrowLeft, Monitor, Settings, Zap, Sliders, HardDrive, ExternalLink, Server, Target } from "lucide-react"

export const metadata: Metadata = {
  title: "ProxMenux Documentation: Windows Virtual Machines",
  description:
    "Guide for creating and configuring Windows virtual machines on Proxmox VE using ProxMenux, including UUP Dump ISO and local ISO options.",
  openGraph: {
    title: "ProxMenux Documentation: Windows Virtual Machines",
    description:
      "Guide for creating and configuring Windows virtual machines on Proxmox VE using ProxMenux, including UUP Dump ISO and local ISO options.",
    type: "article",
    url: "https://macrimi.github.io/ProxMenux/docs/virtual-machines/windows",
    images: [
      {
        url: "https://macrimi.github.io/ProxMenux/vm/menu_windows.png",
        width: 1200,
        height: 630,
        alt: "ProxMenux Windows VM Menu",
      },
    ],
  },
  twitter: {
    card: "summary_large_image",
    title: "ProxMenux Documentation: Windows Virtual Machines",
    description:
      "Guide for creating and configuring Windows virtual machines on Proxmox VE using ProxMenux, including UUP Dump ISO and local ISO options.",
    images: ["https://macrimi.github.io/ProxMenux/vm/menu_windows.png"],
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
          src={src || "/placeholder.svg?height=400&width=768&query=Windows VM configuration"}
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

export default function WindowsVMPage() {
  return (
    <div className="container mx-auto py-10 px-4 bg-white text-black">
      <div className="mb-4">

        <div className="flex items-center gap-3 mb-6">
          <Monitor className="h-8 w-8 mr-2 text-blue-500" />
          <h1 className="text-3xl font-bold text-black">Windows VM Creator Script</h1>
        </div>

        <div className="space-y-4 mt-6">
          <p className="text-lg text-black">
            ProxMenux provides automated scripts that create and configure Windows virtual machines on Proxmox VE. These
            scripts simplify the process by handling the necessary configurations and optimizations for Windows
            installations, including VirtIO drivers setup and TPM configuration.
          </p>
        </div>
      </div>

      <ImageWithCaption
        src="/images/design-mode/menu_windows.png"
        alt="Windows VM Menu"
        caption="Windows VM Creation Menu in ProxMenux"
      />

      <div className="mt-8">
        <h2 className="text-2xl font-bold mb-4 text-black">Script Overview</h2>
        <p className="mb-4">
          The Windows VM creation script automates the process of setting up virtual machines optimized for running
          Windows operating systems. The script handles all aspects of VM configuration, including hardware allocation,
          disk setup, and boot options.
        </p>

        <p className="mb-4">The script simplifies the VM creation process by offering the following options:</p>
        <ul className="list-disc pl-5 mb-4">
          <li>Selection of default or advanced configuration</li>
          <li>Configuration of CPU, RAM, BIOS, and machine type</li>
          <li>Choice between virtual disk or physical disk passthrough</li>
          <li>Selection of disk interface type (SCSI, SATA, VirtIO, or IDE)</li>
          <li>Automatic configuration of EFI and TPM for secure boot</li>
          <li>Automatic VirtIO drivers setup for optimal performance</li>
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
                  <td className="py-2 px-4 border-b border-gray-200">4</td>
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
                  <td className="py-2 px-4 border-b border-gray-200">TPM</td>
                  <td className="py-2 px-4 border-b border-gray-200">Enabled (v2.0)</td>
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
                <tr>
                  <td className="py-2 px-4 border-b border-gray-200">TPM</td>
                  <td className="py-2 px-4 border-b border-gray-200">Enable or disable TPM</td>
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
                    Recommended for Windows 10/11 (includes discard/trim support)
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
                  <td className="py-2 px-4 border-b border-gray-200">
                    Legacy Windows systems only (no discard/trim support)
                  </td>
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
            When UEFI BIOS (OVMF) is selected, the script automatically configures an EFI system disk to ensure compatibility with modern bootloaders:
          </p>
          <ul className="list-disc pl-5 mb-4">
            <li>You’ll be prompted to select the storage location for the EFI disk</li>
            <li>A 4MB EFI disk is created and attached to the VM</li>
            <li>The disk is formatted appropriately based on the selected storage backend (e.g., raw format for directory-based storage)</li>
          </ul>
          <p className="mb-4">
            For Windows systems, a <strong>TPM 2.0 device</strong> is also added automatically to meet installation requirements for modern versions like Windows 11 and Windows Server 2022.
          </p>

          <h4 className="text-lg font-medium mt-4 mb-2">ISO Mounting</h4>
          <p className="mb-3">
            The script also handles ISO mounting automatically for both installation media and optional drivers:
          </p>
          <ul className="list-disc pl-5 mb-4">
            <li>The main installation ISO is mounted to the first available IDE slot (typically <code>ide2</code>)</li>
            <li>If the system is Windows, the VirtIO drivers ISO is downloaded and mounted to the next IDE slot (typically <code>ide3</code>)</li>
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
          <h2 className="text-2xl font-bold mb-6 text-black">Windows Installation Options</h2>
          <p className="mb-6">ProxMenux offers two methods for installing Windows on your virtual machine:</p>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-8 mt-8">
            <div className="border rounded-lg p-6 bg-gray-50 hover:shadow-md transition-shadow">
              <div className="flex items-center gap-3 mb-4">
                <div className="w-12 h-12 flex items-center justify-center">
                  <Image
                    src="https://uupdump.net/static/images/logo.svg"
                    alt="UUP Dump Logo"
                    width={48}
                    height={48}
                    className="object-contain"
                  />
                </div>
                <h3 className="text-xl font-semibold">Script UUP Dump ISO Creator</h3>
              </div>

              <p className="mb-4">
                 The <strong>UUP Dump ISO Creator</strong> script is a utility included in <strong>ProxMenux</strong> that allows you to 
                 download and create Windows installation media directly from Microsoft's Windows Update servers. 
                 This option provides access to the latest Windows builds, including Insider Preview versions.
              </p>

              <h4 className="font-medium mb-2">Features:</h4>
              <ul className="list-disc pl-5 mb-4 space-y-1">
                <li>Access to the latest Windows builds</li>
                <li>Ability to download Insider Preview versions</li>
                <li>Clean, official Microsoft installation files</li>
                <li>Automatic ISO creation and mounting</li>
                <li>Support for various Windows editions (Home, Pro, Enterprise)</li>
              </ul>

              <p className="mt-4 text-sm text-blue-600">
                <Link href="/docs/utils/UUp-Dump-ISO-Creator" className="hover:underline">
                  Learn more about UUP Dump ISO Creator 
                </Link>
              </p>
            </div>

            <div className="border rounded-lg p-6 bg-gray-50 hover:shadow-md transition-shadow">
              <div className="flex items-center gap-3 mb-4">
                <Server className="h-12 w-12 text-blue-500" />
                <h3 className="text-xl font-semibold">Install with Local ISO</h3>
              </div>

              <p className="mb-4">
                This option allows you to use your own Windows ISO file that's already uploaded to your Proxmox server's
                local storage. Ideal if you have custom or specific Windows installation media.
              </p>

              <div className="mt-4">
                <ImageWithCaption
                  src="/images/design-mode/local-store-windows.png"
                  alt="Local ISO Selection Menu"
                  caption="Local ISO Selection Menu in ProxMenux"
                />
              </div>
            </div>
          </div>
        </div>

                <div className="mt-8 p-6 bg-gray-50 rounded-lg border border-gray-200">
          <h2 className="text-xl font-bold mb-4 text-black">Installation Process</h2>
          <p className="mb-4">
            After configuring the VM settings and selecting your installation method, the script will:
          </p>
          <ol className="list-decimal pl-5 space-y-2">
            <li>Create the VM with the specified configuration</li>
            <li>Configure EFI disk and TPM for secure boot support</li>
            <li>Create and attach virtual disks or pass through physical disks</li>
            <li>Download and mount the Windows ISO (UUP Dump option) or mount your local ISO</li>
            <li>Download and mount the VirtIO drivers ISO</li>
            <li>Set the boot order (disk first, then ISO)</li>
            <li>Configure the QEMU Guest Agent</li>
            <li>Start the VM if requested</li>
          </ol>
        </div>

        <div className="mt-12 p-6 bg-gray-50 rounded-lg border border-gray-200">
          <h2 className="text-xl font-bold mb-4 text-black">VirtIO Drivers Setup</h2>
          <p className="mb-4">
            For optimal performance, Windows VMs require VirtIO drivers. The script automatically handles this by:
          </p>
          <ul className="list-disc pl-5 space-y-2">
            <li>Downloading the latest VirtIO drivers ISO or using an existing one</li>
            <li>Mounting the VirtIO drivers ISO to the VM</li>
            <li>Providing instructions for loading the drivers during Windows installation</li>
          </ul>
          <p className="mt-4">
            If you select a <strong>SCSI</strong> or <strong>VirtIO</strong> disk interface for the virtual machine, 
            Windows installation will not detect the disk by default. In this case, you must click <em>"Load Driver"</em> during the disk selection 
            step and browse to the mounted VirtIO ISO to install the necessary storage drivers.
            <br />
            These interfaces offer significantly better performance compared to traditional <strong>SATA</strong> disks, 
            and are therefore recommended for optimal disk I/O.
          </p>
        </div>

        <section className="mb-8">
          <h2 className="text-2xl font-semibold mt-20 mb-4 flex items-center">
            <Target className="h-6 w-6 mr-2 text-blue-500" />
            Tips
          </h2>
          <ul className="list-disc pl-5 space-y-4">

            <li>
              If you select <strong>VirtIO</strong> as the <strong>network interface</strong> (recommended for performance), 
              you must also install the VirtIO network drivers from the same ISO. This ensures that the Windows installer can access 
              the network to complete updates or activate the system.
            </li>

            <div className="bg-yellow-100 border-l-4 border-yellow-500 text-yellow-700 p-4 mb-4">
              <p className="font-semibold">Important:</p>
              <p>
                Without the VirtIO network driver, the virtual machine will not have internet access during installation,
                which may prevent Windows from completing activation or downloading necessary updates.
              </p>
            </div>
          </ul>
        </section>


        <div className="mt-6 space-y-8">
          {/* Step 1 */}
          <div>
            <h3 className="text-lg font-medium mb-3">
              Step 1: Access the "Where do you want to install Windows?" screen
            </h3>
            <p className="mb-3">
              During Windows installation, if no disks are shown on the “Where do you want to install Windows?” screen, it means the required storage drivers for your selected disk interface (such as SCSI or VirtIO) are not available. You'll need to load them manually.
            </p>
            <ImageWithCaption
              src="/images/design-mode/virtio-step-1.png"
              alt="Windows installation - No disks shown"
              caption="Windows installation screen with no disks available"
            />
          </div>

          {/* Step 2 */}
          <div>
            <h3 className="text-lg font-medium mb-3">Step 2: Click "Load driver"</h3>
            <p className="mb-3">
              Click the “Load driver” button to browse the mounted VirtIO ISO. This will allow you to load the necessary storage drivers so Windows can detect the virtual disk.
            </p>
            <ImageWithCaption
              src="/images/design-mode/virtio-step-2.png"
              alt="Windows installation - Load driver button"
              caption="Click 'Load driver' to browse for VirtIO drivers"
            />
          </div>

          {/* Step 3 */}
          <div>
            <h3 className="text-lg font-medium mb-3">Step 3: Browse to the correct driver location</h3>
            <p className="mb-3">
              On the mounted VirtIO ISO, navigate to the appropriate driver folder that matches your selected disk interface and Windows version.
              For example, the <code className="bg-gray-100 px-1 py-0.5 rounded">viostor</code> folder contains storage drivers, and you'll find subfolders organized by version (e.g., Windows 10, 11, Server).
            </p>
            <ImageWithCaption
              src="/images/design-mode/virtio-step-3.png"
              alt="Windows installation - Browse for driver"
              caption="Browse to the appropriate driver folder on the VirtIO ISO"
            />
          </div>

          {/* Step 4 */}
          <div>
            <h3 className="text-lg font-medium mb-3">Step 4: Select the appropriate driver</h3>
            <p className="mb-3">
              After selecting the folder, Windows will list the available drivers. Choose the appropriate one — usually “Red Hat VirtIO SCSI controller” — and click “Next” to proceed with the installation.
            </p>
            <ImageWithCaption
              src="/images/design-mode/virtio-step-4.png"
              alt="Windows installation - Select driver"
              caption="Select the appropriate VirtIO driver for your disk interface"
            />
          </div>

          {/* Step 5 */}
          <div>
            <h3 className="text-lg font-medium mb-3">Step 5: Install network drivers (recommended)</h3>
            <p className="mb-3">
              <strong>Pro Tip:</strong> If you selected <strong>VirtIO</strong> as the network interface, Windows will not recognize it by default. To enable internet access during installation, load the VirtIO network driver from the ISO by browsing to the <code className="bg-gray-100 px-1 py-0.5 rounded">NetKVM</code> folder and selecting the correct subfolder for your Windows version.
            </p>
            <ImageWithCaption
              src="/images/design-mode/virtio-step-5.png"
              alt="Windows installation - Network drivers"
              caption="Select the appropriate VirtIO network driver to enable internet access"
            />
          </div>


          {/* Post-installation block */}
          <div className="mt-6 bg-blue-50 border border-blue-200 rounded-md p-4">
            <h3 className="text-lg font-medium mb-2 text-blue-800">Post-Installation Driver Setup</h3>
            <p className="text-blue-800">
              After the Windows installation is complete, it's recommended to install the remaining VirtIO drivers for full hardware support and optimal performance.
              To do this, open the mounted VirtIO ISO in File Explorer and run the installer named{" "}
              <code className="bg-white px-1 py-0.5 rounded text-sm">virtio-win-guest-tools.exe</code>. This will install drivers for network, display, input, ballooning, and other virtualized components.
            </p>
          </div>
        </div>


      </div>
    </div>
  )
}
