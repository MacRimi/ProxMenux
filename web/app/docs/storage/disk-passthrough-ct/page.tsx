import { Steps } from "@/components/ui/steps"
import { HardDrive, ArrowRight } from "lucide-react"
import { ImageWithCaption } from "@/components/ui/image-with-caption"
import type { Metadata } from "next"

export const metadata: Metadata = {
  title: "Disk Passthrough to a CT | ProxMenux Documentation",
  description: "Step-by-step guide to configure disk passthrough to a container (CT) in Proxmox VE using ProxMenux.",
  openGraph: {
    title: "Disk Passthrough to a CT | ProxMenux Documentation",
    description: "Step-by-step guide to configure disk passthrough to a container (CT) in Proxmox VE using ProxMenux.",
    type: "article",
    url: "https://macrimi.github.io/ProxMenux/docs/disk-ct",
    images: [
      {
        url: "https://macrimi.github.io/ProxMenux/disk-ct/disk-selection.png",
        width: 1200,
        height: 630,
        alt: "Disk Passthrough to a CT",
      },
    ],
  },
  twitter: {
    card: "summary_large_image",
    title: "Disk Passthrough to a CT | ProxMenux Documentation",
    description: "Step-by-step guide to configure disk passthrough to a container (CT) in Proxmox VE using ProxMenux.",
    images: ["https://macrimi.github.io/ProxMenux/disk-ct/disk-selection.png"],
  },
}

export default function DiskPassthroughCT() {
  return (
    <div className="max-w-3xl mx-auto">
      <div className="flex items-center mb-6">
        <HardDrive className="h-8 w-8 mr-2 text-blue-500" />
        <ArrowRight className="h-5 w-5 mr-2 text-gray-500" />
        <h1 className="text-3xl font-bold">
          Disk Passthrough to a <span className="text-blue-500">CT</span>
        </h1>
      </div>

      <p className="mb-4">
        This guide explains how to assign a <strong>dedicated physical disk</strong> to a container (CT) in{" "}
        <strong>Proxmox VE</strong> using <strong>ProxMenux</strong>. Assigning a full disk to a container is useful
        when you need isolation, ease of access, or the ability to move the disk between systems, especially for
        services handling large volumes of data such as Samba, Nextcloud, or video surveillance software, among others.
      </p>

      <p className="mb-4">
        While it's more common to passthrough entire disks to virtual machines (VMs), there are scenarios where giving
        full disk access to an LXC container can be very useful.
      </p>

      <ul className="list-disc pl-6 mb-4 space-y-1">
        <li>
          A user running a video surveillance system like <strong>Frigate</strong> or <strong>Agent DVR</strong> might
          want recordings saved on a dedicated disk, so they can easily transfer it to another system for review.
        </li>
        <li>
          A <strong>Nextcloud</strong> container might need full disk access to manage user files and take advantage of
          the entire disk capacity.
        </li>
        <li>
          A container may be used for downloads, storing files on a dedicated disk and sharing them over the local
          network.
        </li>
        <li>Another use case could be writing backups to an isolated disk.</li>
      </ul>

      <p className="mb-6">
        As you can see, there are many different use cases where assigning a physical disk directly to a CT is the ideal
        solution.
      </p>

      <h2 className="text-2xl font-semibold mt-8 mb-4">Description</h2>
      <ol className="list-decimal pl-6 space-y-2 mb-6">
        <li>Lists physical disks on the Proxmox host, excluding the system disk and mounted system disks.</li>
        <li>Displays all existing LXC containers (CTs) for user selection.</li>
        <li>
          Allows the user to select <strong>one physical disk</strong> per execution.
        </li>
        <li>
          Formats the disk (with user confirmation) or reuses it, then assigns it as a mount point in the selected CT.
        </li>
      </ol>

      <h2 className="text-2xl font-semibold mt-8 mb-4">Step-by-Step Instructions</h2>
      <Steps>
        <Steps.Step title="CT Selection">
        <ImageWithCaption
            src="https://macrimi.github.io/ProxMenux/disk/select-container.png"
            alt="Select CT"
            caption="CT Selection Menu."
          />
          
          <p>The user selects the destination LXC container (CT) to which the disk will be assigned.</p>
        </Steps.Step>
        <Steps.Step title="Disk Detection">
          <ImageWithCaption
            src="https://macrimi.github.io/ProxMenux/disk/disk-selection-ct.png"
            alt="Disk Selection Menu"
            caption="Disk Selection Menu"
          />
          <p>
            The script lists all physical disks, excluding those used by the system. It also displays metadata like ZFS,
            LVM, and RAID, and shows warnings if the disk is already in use.
          </p>
        </Steps.Step>
        <Steps.Step title="Disk Preparation">
          <p>The script performs the following actions:</p>
          <ul className="list-disc pl-6 space-y-1 mt-2">
            <li>Detects whether the disk has a supported filesystem (ext4, xfs, btrfs).</li>
            <li>Offers to format the disk if no valid filesystem is found.</li>
            <li>
              Prompts the user to define the mount point (e.g. <code>/mnt/disk_passthrough</code>).
            </li>
          </ul>
        </Steps.Step>
        <Steps.Step title="Assignment to CT">
        <ImageWithCaption
            src="https://macrimi.github.io/ProxMenux/disk/assignment-ct.png"
            alt="Assignment to CT"
            caption="Assignment to CT"
          />
          <p>
            The selected disk is mounted inside the container at the specified path, and permissions are set
            automatically.
          </p>
        </Steps.Step>
      </Steps>

      <h2 className="text-2xl font-semibold mt-8 mb-4">Expected Results</h2>
      <ul className="list-disc pl-6 space-y-2 mb-6">
        <li>The selected disk is successfully mounted and accessible within the specified container.</li>
        <li>The script shows a summary of the operation, including any warnings or errors.</li>
        <li>The container can use the assigned storage immediately.</li>
        <ImageWithCaption
            src="https://macrimi.github.io/ProxMenux/disk/result-point.png"
            alt="Mount point created successfully"
            caption="Mount point created successfully"
          />
      </ul>


      <h2 className="text-2xl font-semibold mt-8 mb-4">Important Considerations</h2>
      <div className="bg-yellow-100 border-l-4 border-yellow-500 text-yellow-700 p-4 mb-4">
        <p className="font-semibold">Important:</p>
        <p>
          The container must be <strong>privileged</strong> to allow direct read/write access to the physical disk.
        </p>
      </div>
      <ul className="list-disc pl-6 space-y-2 mb-6">
        <li>
          Only <strong>one disk</strong> can be assigned per script execution.
        </li>
        <li>Avoid assigning the same disk to multiple VMs or CTs that may run at the same time, as this can lead to data corruption or file loss.</li>
        <li>
          Clean any RAID, ZFS, or LVM metadata <strong>manually</strong> before assigning the disk.
        </li>
      </ul>
    </div>
  )
}
