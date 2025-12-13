import type { Metadata } from "next"
import { Zap } from "lucide-react"
import CopyableCode from "@/components/CopyableCode"

export const metadata: Metadata = {
  title: "ProxMenux Post-Install: Performance Settings",
  description:
    "Guide to Performance Settings in the ProxMenux post-install script for optimizing your Proxmox VE system performance.",
  openGraph: {
    title: "ProxMenux Post-Install: Performance Settings",
    description:
      "Guide to Performance Settings in the ProxMenux post-install script for optimizing your Proxmox VE system performance.",
    type: "article",
    url: "https://macrimi.github.io/ProxMenux/docs/post-install/performance",
    images: [
      {
        url: "https://macrimi.github.io/ProxMenux/performance-settings-image.png",
        width: 1200,
        height: 630,
        alt: "ProxMenux Post-Install Performance Settings",
      },
    ],
  },
  twitter: {
    card: "summary_large_image",
    title: "ProxMenux Post-Install: Performance Settings",
    description:
      "Guide to Performance Settings in the ProxMenux post-install script for optimizing your Proxmox VE system performance.",
    images: ["https://macrimi.github.io/ProxMenux/performance-settings-image.png"],
  },
}

function StepNumber({ number }: { number: number }) {
  return (
    <div className="inline-flex items-center justify-center w-8 h-8 mr-3 text-white bg-blue-500 rounded-full">
      <span className="text-sm font-bold">{number}</span>
    </div>
  )
}

export default function PerformanceSettingsPage() {
  return (
    <div className="container mx-auto px-4 py-8">
      <div className="flex items-center mb-6">
        <Zap className="h-8 w-8 mr-2 text-blue-500" />
        <h1 className="text-3xl font-bold">Performance Settings</h1>
      </div>
      <p className="mb-4">
        The <strong>Performance Settings</strong> category focuses on optimizing various aspects of your Proxmox VE
        system to enhance overall performance. These settings are designed to improve system efficiency and speed up
        certain operations.
      </p>
      <h2 className="text-2xl font-semibold mt-8 mb-4">Available Optimizations</h2>



    <h3 className="text-xl font-semibold mt-16 mb-4 flex items-center">
      <StepNumber number={1} />
      Configure pigz for Faster gzip Compression
    </h3>

    <p className="mb-4">
      This optimization replaces the default <strong>gzip</strong> compression with 
      <strong>pigz</strong>, a parallelized version that speeds up compression by 
      utilizing multiple CPU cores.
    </p>

    <h4 className="text-lg font-semibold mt-4">What does this configuration do?</h4>
    <ul className="list-disc pl-5 mb-4">
      <li><strong>Forces pigz usage</strong> in vzdump backups to accelerate Proxmox VE backup compression.</li>
      <li><strong>Ensures pigz is installed</strong> before applying optimizations.</li>
      <li><strong>Creates a pigz wrapper script</strong> to enforce compression behavior.</li>
      <li><strong>Replaces gzip with the pigz wrapper</strong>, making pigz the system-wide default compressor.</li>
    </ul>

    <h4 className="text-lg font-semibold mt-4">How is pigz configured?</h4>

    <p className="text-lg mb-2">This automation executes the following commands:</p>

    <CopyableCode
      code={`
    # Force pigz usage in vzdump configuration (for Proxmox backups)
    sed -i "s/#pigz:.*/pigz: 1/" /etc/vzdump.conf

    # Install pigz package
    apt-get -y install pigz

    # Create a pigz wrapper script
    cat <<EOF > /bin/pigzwrapper
    #!/bin/sh
    PATH=/bin:\$PATH
    GZIP="-1"
    exec /usr/bin/pigz "\$@"
    EOF
    chmod +x /bin/pigzwrapper

    # Replace gzip with pigz wrapper (backup original gzip binary)
    if [ ! -f /bin/gzip.original ]; then
        mv -f /bin/gzip /bin/gzip.original
        cp -f /bin/pigzwrapper /bin/gzip
        chmod +x /bin/gzip
    fi
      `}
    />

    <h4 className="text-lg font-semibold mt-6">How to Verify pigz is Active</h4>

    <p className="mb-4">
      You can confirm that <strong>pigz</strong> is being used by running the following command:
    </p>

    <CopyableCode
      code={`
    # Check if gzip now points to pigz
    gzip --version
      `}
    />

    <p className="mb-4">
      If the output mentions <code>pigz</code>, the replacement was successful.
    </p>


    <p className="mt-4">
      With this optimization, vzdump backups and all gzip compression tasks benefit from parallel processing,
      reducing execution time considerably.
    </p>



      <section className="mt-12 p-4 bg-blue-100 rounded-md">
        <h2 className="text-xl font-semibold mb-2">Automatic Application</h2>
        <p>
          This performance optimization is automatically applied when selected in the Performance section. The
          automation ensures that pigz is correctly configured and integrated into your system, potentially improving
          the speed of compression operations without requiring manual intervention.
        </p>
      </section>
    </div>
  )
}
