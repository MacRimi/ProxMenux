import { Steps } from "@/components/ui/steps"
import CopyableCode from "@/components/CopyableCode"
import Image from "next/image"

export const metadata = {
  title: "Enable iGPU Acceleration in LXC | ProxMenux Documentation",
  description: "Step-by-step guide to enable Intel iGPU acceleration in an LXC container using ProxMenux.",
}

export default function IGPUAccelerationLXC() {
  return (
    <div className="max-w-3xl mx-auto">
      <h1 className="text-3xl font-bold mb-6">Enable Intel iGPU Acceleration in an LXC</h1>
      
      <p className="mb-4">
        This guide explains how to configure Intel Integrated GPU (iGPU) acceleration for LXC containers in Proxmox VE
        using <strong>ProxMenux</strong>. Enabling iGPU support allows containers to use the host’s GPU for hardware acceleration
        in applications such as video transcoding and rendering.
      </p>
      
      <h2 className="text-2xl font-semibold mt-8 mb-4">Overview of the Process</h2>
      <p className="mb-4">When you run this script in ProxMenux, it performs the following steps:</p>
      <ol className="list-decimal pl-6 space-y-2 mb-6">
        <li>Prompts you to select an existing LXC container.</li>
        <li>Checks if the container is privileged and adjusts its settings accordingly.</li>
        <li>Modifies the container’s configuration to allow GPU access.</li>
        <li>Installs the required Intel GPU drivers inside the container.</li>
      </ol>
      
      <h2 className="text-2xl font-semibold mt-8 mb-4">Step-by-Step Guide</h2>
      <Steps>
        <Steps.Step title="Select an LXC Container">
          <p>You will be presented with a list of your LXC containers to choose from.</p>
          <Image src="https://macrimi.github.io/ProxMenux/igpu/select-container.png" alt="Select LXC Container" width={800} height={400} className="rounded shadow-lg" />
        </Steps.Step>
        <Steps.Step title="Modify Container Configuration">
          <p>The script applies the following changes to your container:</p>
          <ul className="list-disc pl-6 space-y-1 mt-2">
            <li>Switches to privileged mode if required.</li>
            <li>Enables the nesting feature.</li>
            <li>Grants permissions for GPU access.</li>
            <li>Configures necessary device mounts.</li>
          </ul>
        </Steps.Step>
        <Steps.Step title="Install Intel GPU Drivers">
          <p>Inside the container, the following GPU-related packages will be installed:</p>
          <ul className="list-disc pl-6 space-y-1 mt-2">
            <li><strong>va-driver-all</strong> - Video acceleration drivers</li>
            <li><strong>ocl-icd-libopencl1</strong> - OpenCL runtime</li>
            <li><strong>intel-opencl-icd</strong> - Intel OpenCL implementation</li>
            <li><strong>vainfo</strong> - Tool to verify VAAPI support</li>
            <li><strong>intel-gpu-tools</strong> - Intel GPU debugging tools</li>
          </ul>
        </Steps.Step>
      </Steps>
      
      <h2 className="text-2xl font-semibold mt-8 mb-4">Expected Outcome</h2>
      <ul className="list-disc pl-6 space-y-2 mb-6">
        <li>Your LXC container will be configured for Intel iGPU acceleration.</li>
        <li>The required GPU drivers and tools will be installed inside the container.</li>
        <li>The container will briefly stop and restart as part of the setup.</li>
        <li>After completion, applications inside the container will be able to leverage the GPU for acceleration.</li>
      </ul>
      
      <h2 className="text-2xl font-semibold mt-8 mb-4">Important Notes</h2>
      <ul className="list-disc pl-6 space-y-2 mb-6">
        <li>This script is designed specifically for Intel iGPUs.</li>
        <li>Some applications inside the container may need additional setup to use the GPU.</li>
      </ul>
      
    </div>
  )
}
