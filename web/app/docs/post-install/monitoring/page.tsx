import type { Metadata } from "next"
import { LineChart } from "lucide-react"
import CopyableCode from "@/components/CopyableCode"

export const metadata: Metadata = {
  title: "ProxMenux Post-Install: Monitoring Settings",
  description:
    "Guide to Monitoring Settings in the ProxMenux post-install script for enhancing your Proxmox VE monitoring capabilities.",
  openGraph: {
    title: "ProxMenux Post-Install: Monitoring Settings",
    description:
      "Guide to Monitoring Settings in the ProxMenux post-install script for enhancing your Proxmox VE monitoring capabilities.",
    type: "article",
    url: "https://macrimi.github.io/ProxMenux/docs/post-install/monitoring",
    images: [
      {
        url: "https://macrimi.github.io/ProxMenux/monitoring-settings-image.png",
        width: 1200,
        height: 630,
        alt: "ProxMenux Post-Install Monitoring Settings",
      },
    ],
  },
  twitter: {
    card: "summary_large_image",
    title: "ProxMenux Post-Install: Monitoring Settings",
    description:
      "Guide to Monitoring Settings in the ProxMenux post-install script for enhancing your Proxmox VE monitoring capabilities.",
    images: ["https://macrimi.github.io/ProxMenux/monitoring-settings-image.png"],
  },
}

function StepNumber({ number }: { number: number }) {
  return (
    <div className="inline-flex items-center justify-center w-8 h-8 mr-3 text-white bg-blue-500 rounded-full">
      <span className="text-sm font-bold">{number}</span>
    </div>
  )
}

export default function MonitoringSettingsPage() {
  return (
    <div className="container mx-auto px-4 py-8">
      <div className="flex items-center mb-6">
        <LineChart className="h-8 w-8 mr-2 text-blue-500" />
        <h1 className="text-3xl font-bold">Monitoring Settings</h1>
      </div>
      <p className="mb-4">
        The <strong>Monitoring Settings</strong> category focuses on enhancing the monitoring capabilities of your
        Proxmox VE installation. These settings are designed to provide better insights into your system's performance
        and health.
      </p>
      <h2 className="text-2xl font-semibold mt-8 mb-4">Available Optimizations</h2>

      <h3 className="text-xl font-semibold mt-16 mb-4 flex items-center">
        <StepNumber number={1} />
        Install OVH Real Time Monitoring (RTM)
      </h3>
      <p className="mb-4">
        This optimization detects if the server is hosted by OVH and installs the OVH Real Time Monitoring (RTM) tool if
        applicable.
      </p>
      <p className="mb-4">The following steps are performed:</p>
      <ul className="list-disc pl-5 mb-4">
        <li>Detects the server's public IP address</li>
        <li>Checks if the IP belongs to OVH using WHOIS information</li>
        <li>If it's an OVH server, installs the OVH RTM tool</li>
      </ul>
      <p className="mb-4">
        <strong>Note:</strong> This optimization is only applicable to servers hosted by OVH. If your server is not
        hosted by OVH, this step will be skipped.
      </p>
      <p className="text-lg mb-2">This adjustment automates the following commands:</p>
      <CopyableCode
        code={`
# Get the public IP and check if it belongs to OVH
public_ip=$(curl -s ipinfo.io/ip)
is_ovh=$(whois -h v4.whois.cymru.com " -t $public_ip" | tail -n 1 | cut -d'|' -f3 | grep -i "ovh")

if [ -n "$is_ovh" ]; then
    # Install OVH RTM
    wget -qO - https://last-public-ovh-infra-yak.snap.mirrors.ovh.net/yak/archives/apply.sh | OVH_PUPPET_MANIFEST=distribyak/catalog/master/puppet/manifests/common/rtmv2.pp bash
fi
      `}
      />

      <section className="mt-12 p-4 bg-blue-100 rounded-md">
        <h2 className="text-xl font-semibold mb-2">Automatic Application</h2>
        <p>
          This monitoring optimization is automatically applied when selected in the Monitoring section. The automation
          ensures that the OVH RTM tool is installed correctly if your server is hosted by OVH, enhancing your server's
          monitoring capabilities without manual intervention.
        </p>
      </section>
    </div>
  )
}

