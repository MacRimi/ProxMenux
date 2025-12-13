import { Steps } from "@/components/ui/steps"
import CopyableCode from "@/components/CopyableCode"

export const metadata = {
  title: "Disk Passthrough to a VM | ProxMenux Documentation",
  description: "Step-by-step guide to configure disk passthrough to a virtual machine in Proxmox VE using ProxMenux.",
}

export default function DiskPassthroughVM() {
  return (
    <div className="max-w-3xl mx-auto">
      <h1 className="text-3xl font-bold mb-6">Disk Passthrough to a VM</h1>
      
      <p className="mb-4">
        This guide explains how to assign physical disks to virtual machines (VMs) in <strong>Proxmox VE</strong> using <strong>ProxMenux</strong>.
        Disk passthrough allows a VM to have direct access to a physical disk, providing improved performance and compatibility for certain applications.
      </p>
      
      <h2 className="text-2xl font-semibold mt-8 mb-4">Overview</h2>
      <p className="mb-4">The script automates the following steps:</p>
      <ol className="list-decimal pl-6 space-y-2 mb-6">
        <li>Lists available physical disks on the Proxmox host, excluding the system disk.</li>
        <li>Displays a list of available virtual machines (VMs) for selection.</li>
        <li>Allows the user to select multiple disks to assign to a VM.</li>
        <li>Ensures selected disks are not already in use by another VM.</li>
        <li>Configures the selected disks for passthrough to the chosen VM.</li>
      </ol>
      
      <h2 className="text-2xl font-semibold mt-8 mb-4">Implementation Steps</h2>
      <Steps>
        <Steps.Step title="Disk Selection">
          <img src="https://macrimi.github.io/ProxMenux/disk/disk-selection.png" alt="Disk Selection Menu" className="mt-4 rounded shadow-lg" />
          <p>The script scans the system and displays a list of available physical disks, excluding the system disk.</p>
        </Steps.Step>
        <Steps.Step title="VM Selection">
          <p>The user selects the virtual machine (VM) to which the disk(s) will be assigned.</p>
        </Steps.Step>
        <Steps.Step title="Disk Assignment">
          <img src="https://macrimi.github.io/ProxMenux/disk/disk-assigment.png" alt="Disk Assigment Menu" className="mt-4 rounded shadow-lg" />
          <p>The script performs the following actions:</p>
          <ul className="list-disc pl-6 space-y-1 mt-2">
            <li>Ensures the selected disk is not in use by another VM.</li>
            <li>Provides an interface choice (SATA, SCSI, VirtIO, or IDE).</li>
            <li>Automatically configures the disk passthrough and assigns it to the VM.</li>
          </ul>
        </Steps.Step>
        <Steps.Step title="Confirmation & Finalization">
          <p>The script verifies the operation and confirms the successful disk passthrough.</p>
        </Steps.Step>
      </Steps>
      
      <h2 className="text-2xl font-semibold mt-8 mb-4">Expected Results</h2>
      <ul className="list-disc pl-6 space-y-2 mb-6">
        <li>The selected physical disk(s) are successfully assigned to the specified VM.</li>
        <li>Users are provided with a confirmation of the disk assignment.</li>
        <li>The VM is configured to recognize the disk(s) upon startup.</li>
      </ul>
      
      <h2 className="text-2xl font-semibold mt-8 mb-4">Important Considerations</h2>
      <ul className="list-disc pl-6 space-y-2 mb-6">
        <li>Ensure the selected disk is not already in use by another VM.</li>
        <li>VMs must be powered off before adding disks to prevent data corruption.</li>
        <li>Using disk passthrough limits certain VM features, such as live migration.</li>
      </ul>
      

    </div>
  )
}
