import type { Metadata } from "next"
import { Box } from "lucide-react"
import CopyableCode from "@/components/CopyableCode"

export const metadata: Metadata = {
  title: "ProxMenux Post-Install: Virtualization Settings",
  description:
    "Detailed guide to the Virtualization Settings category in the ProxMenux post-install script for Proxmox VE optimization.",
  openGraph: {
    title: "ProxMenux Post-Install: Virtualization Settings",
    description:
      "Detailed guide to the Virtualization Settings category in the ProxMenux post-install script for Proxmox VE optimization.",
    type: "article",
    url: "https://macrimi.github.io/ProxMenux/docs/post-install/virtualization",
    images: [
      {
        url: "https://macrimi.github.io/ProxMenux/virtualization-settings-image.png",
        width: 1200,
        height: 630,
        alt: "ProxMenux Post-Install Virtualization Settings",
      },
    ],
  },
  twitter: {
    card: "summary_large_image",
    title: "ProxMenux Post-Install: Virtualization Settings",
    description:
      "Detailed guide to the Virtualization Settings category in the ProxMenux post-install script for Proxmox VE optimization.",
    images: ["https://macrimi.github.io/ProxMenux/virtualization-settings-image.png"],
  },
}

function StepNumber({ number }: { number: number }) {
  return (
    <div className="inline-flex items-center justify-center w-8 h-8 mr-3 text-white bg-blue-500 rounded-full">
      <span className="text-sm font-bold">{number}</span>
    </div>
  )
}

export default function VirtualizationSettingsPage() {
  return (
    <div className="container mx-auto px-4 py-8">
      <div className="flex items-center mb-6">
        <Box className="h-8 w-8 mr-2 text-blue-500" />
        <h1 className="text-3xl font-bold">Virtualization Settings</h1>
      </div>
      <p className="mb-4">
        The <strong>Virtualization Settings</strong> category optimizes Proxmox VE for enhanced virtualization performance, 
        compatibility, and functionality.
      </p>
      <h2 className="text-2xl font-semibold mt-8 mb-4">Available Optimizations</h2>

      <h3 className="text-xl font-semibold mt-16 mb-4 flex items-center">
        <StepNumber number={1} />
        Enable VFIO IOMMU Support
      </h3>
      <p className="mb-4">
      This setting enables <strong>IOMMU</strong> (Input-Output Memory Management Unit) and configures <strong>VFIO</strong> (Virtual Function I/O) 
      for PCI passthrough, allowing direct assignment of PCI devices to virtual machines.
      </p>
      <p className="mb-4">
      <strong className="block">Why it's beneficial:</strong>
        Enables near-native performance for PCI devices, such as GPUs or network cards, 
        by allowing direct access from VMs. This is essential forGPU acceleration, low-latency networking, 
        and high-performance workloads, reducing hypervisor overhead and improving efficiency.
      </p>
      <p className="text-lg mb-2">This adjustment automates the following commands:</p>
      <CopyableCode
        code={`
# For Intel CPUs
echo "intel_iommu=on" | sudo tee -a /etc/default/grub
# For AMD CPUs
echo "amd_iommu=on" | sudo tee -a /etc/default/grub

echo "vfio vfio_iommu_type1 vfio_pci vfio_virqfd" | sudo tee -a /etc/modules

sudo update-grub
sudo update-initramfs -u -k all
      `}
      />

      <h3 className="text-xl font-semibold mt-16 mb-4 flex items-center">
        <StepNumber number={2} />
        Install Relevant Guest Agent
      </h3>
      <p className="mb-4">
      This optimization installs the appropriate <strong>guest agent</strong> based on the virtualization environment.
      </p>
      <p className="mb-4">
      <strong className="block">Why it's beneficial:</strong>
        Enhances host-guest integration by enabling graceful shutdown, 
        file sharing, performance monitoring, and better resource allocation. 
        This improves VM management and overall system efficiency.
      </p>
      <p className="text-lg mb-2">This adjustment automates the following commands:</p>
      <CopyableCode
        code={`
# For QEMU/KVM VMs
sudo apt-get install -y qemu-guest-agent

# For VMware VMs
sudo apt-get install -y open-vm-tools

# For VirtualBox VMs
sudo apt-get install -y virtualbox-guest-utils
      `}
      />

      <h3 className="text-xl font-semibold mt-20 mb-4 flex items-center">
        <StepNumber number={3} />
        Configure KSM (Kernel Samepage Merging)
      </h3>
      <p className="mb-4">
      This setting enables and configures <strong>KSM</strong> to optimize memory usage by sharing identical 
      memory pages across multiple virtual machines.
      </p>
      <p className="mb-4">
      <strong className="block">Why it's beneficial:</strong>
        Reduces RAM consumption in environments with similar VMs, 
        allowing for higher VM density on a single host. This is particularly useful for systems 
        running multiple instances of the same OS or application, improving memory efficiency and overall performance.
      </p>
      <p className="text-lg mb-2">This adjustment automates the following commands:</p>
      <CopyableCode
        code={`
sudo apt-get install -y ksm-control-daemon

echo "KSM_ENABLED=1" | sudo tee -a /etc/default/ksm
echo "KSM_SLEEP_MSEC=100" | sudo tee -a /etc/default/ksm

sudo systemctl enable ksm
sudo systemctl start ksm
      `}
      />

      <section className="mt-12 p-4 bg-blue-100 rounded-md">
        <h2 className="text-xl font-semibold mb-2">Automatic Application</h2>
        <p>
          All of these optimizations are automatically applied when selected in the Virtualization section. This
          automation ensures that these beneficial settings are applied consistently and correctly, saving time and
          reducing the potential for human error during manual configuration.
        </p>
      </section>
    </div>
  )
}
