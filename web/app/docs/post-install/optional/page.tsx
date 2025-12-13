import type { Metadata } from "next"
import { Plus } from "lucide-react"
import CopyableCode from "@/components/CopyableCode"

export const metadata: Metadata = {
  title: "ProxMenux Post-Install: Optional Settings",
  description:
    "Guide to Optional Settings in the ProxMenux post-install script for additional Proxmox VE features and optimizations.",
  openGraph: {
    title: "ProxMenux Post-Install: Optional Settings",
    description:
      "Guide to Optional Settings in the ProxMenux post-install script for additional Proxmox VE features and optimizations.",
    type: "article",
    url: "https://macrimi.github.io/ProxMenux/docs/post-install/optional",
    images: [
      {
        url: "https://macrimi.github.io/ProxMenux/optional-settings-image.png",
        width: 1200,
        height: 630,
        alt: "ProxMenux Post-Install Optional Settings",
      },
    ],
  },
  twitter: {
    card: "summary_large_image",
    title: "ProxMenux Post-Install: Optional Settings",
    description:
      "Guide to Optional Settings in the ProxMenux post-install script for additional Proxmox VE features and optimizations.",
    images: ["https://macrimi.github.io/ProxMenux/optional-settings-image.png"],
  },
}

function StepNumber({ number }: { number: number }) {
  return (
    <div className="inline-flex items-center justify-center w-8 h-8 mr-3 text-white bg-blue-500 rounded-full">
      <span className="text-sm font-bold">{number}</span>
    </div>
  )
}

export default function OptionalSettingsPage() {
  return (
    <div className="container mx-auto px-4 py-8">
      <div className="flex items-center mb-6">
        <Plus className="h-8 w-8 mr-2 text-blue-500" />
        <h1 className="text-3xl font-bold">Optional Settings</h1>
      </div>
      <p className="mb-4">
        The <strong>Optional Settings</strong> category provides additional features and optimizations that you can
        choose to apply to your Proxmox VE installation. These settings are not essential but can enhance your system's
        capabilities in specific scenarios.
      </p>
      <h2 className="text-2xl font-semibold mt-8 mb-4">Available Optional Features</h2>

      <h3 className="text-xl font-semibold mt-16 mb-4 flex items-center">
        <StepNumber number={1} />
        Add Latest Ceph Support
      </h3>
      <p className="mb-4">
        This option installs the latest Ceph storage system support for Proxmox VE. Ceph is a distributed storage system
        that provides high performance, reliability, and scalability.
      </p>
      <p className="mb-4">What it does:</p>
      <ul className="list-disc pl-5 mb-4">
        <li>Adds the Ceph repository to your system</li>
        <li>Updates package lists</li>
        <li>Installs Ceph packages using the 'pveceph install' command</li>
        <li>Verifies the installation</li>
      </ul>
      <p className="mb-4">
        How to use: After installation, you can configure and manage Ceph storage using the Proxmox VE web interface or
        command-line tools.
      </p>
      <p className="text-lg mb-2">This adjustment automates the following commands:</p>
      <CopyableCode
        code={`
# Add Ceph repository
echo "deb https://download.proxmox.com/debian/ceph-squid $(lsb_release -cs) no-subscription" > /etc/apt/sources.list.d/ceph-squid.list

# Update package lists
apt-get update

# Install Ceph
pveceph install

# Verify installation
pveceph status
      `}
      />

      <h3 className="text-xl font-semibold mt-16 mb-4 flex items-center">
        <StepNumber number={2} />
        Apply AMD CPU Fixes
      </h3>
      <p className="mb-4">
        This option applies specific fixes for AMD EPYC and Ryzen CPUs to improve stability and compatibility.
      </p>
      <p className="mb-4">What it does:</p>
      <ul className="list-disc pl-5 mb-4">
        <li>Detects if an AMD EPYC or Ryzen CPU is present</li>
        <li>Applies kernel parameter 'idle=nomwait' to prevent random crashes</li>
        <li>Configures KVM to ignore certain MSRs (Model Specific Registers) for better Windows guest compatibility</li>
        <li>Installs the latest Proxmox VE kernel</li>
      </ul>
      <p className="mb-4">
        How to use: These fixes are applied automatically and require a system reboot to take effect.
      </p>
      <p className="text-lg mb-2">This adjustment automates the following commands:</p>
      <CopyableCode
        code={`
# Set kernel parameter
sed -i 's/GRUB_CMDLINE_LINUX_DEFAULT="/GRUB_CMDLINE_LINUX_DEFAULT="idle=nomwait /g' /etc/default/grub
update-grub

# Configure KVM
echo "options kvm ignore_msrs=Y" >> /etc/modprobe.d/kvm.conf
echo "options kvm report_ignored_msrs=N" >> /etc/modprobe.d/kvm.conf

# Install latest Proxmox VE kernel
apt-get install pve-kernel-$(uname -r | cut -d'-' -f1-2)
      `}
      />

      <h3 className="text-xl font-semibold mt-16 mb-4 flex items-center">
        <StepNumber number={3} />
        Enable High Availability Services
      </h3>
      <p className="mb-4">
        This option enables High Availability (HA) services in Proxmox VE, allowing for automatic failover of VMs and
        containers in case of node failure.
      </p>
      <p className="mb-4">What it does:</p>
      <ul className="list-disc pl-5 mb-4">
        <li>Enables and starts the pve-ha-lrm (Local Resource Manager) service</li>
        <li>Enables and starts the pve-ha-crm (Cluster Resource Manager) service</li>
        <li>Enables and starts the corosync service for cluster communication</li>
      </ul>
      <p className="mb-4">
        How to use: After enabling these services, you can configure HA groups and resources in the Proxmox VE web
        interface.
      </p>
      <p className="text-lg mb-2">This adjustment automates the following commands:</p>
      <CopyableCode
        code={`
systemctl enable --now pve-ha-lrm pve-ha-crm corosync
      `}
      />


    <h3 className="text-xl font-semibold mt-16 mb-4 flex items-center">
      <StepNumber number={4} />
      Enable Proxmox Testing Repository
    </h3>
    <p className="mb-4">
      This option enables the Proxmox testing repository, allowing access to the latest, potentially unstable versions of Proxmox VE packages.
    </p>
    <p className="mb-4">What it does:</p>
    <ul className="list-disc pl-5 mb-4">
      <li>Adds the Proxmox testing repository to the system's package sources</li>
      <li>Creates a new file in /etc/apt/sources.list.d/ for the testing repository</li>
      <li>Updates the package lists to include packages from the new repository</li>
    </ul>
    <p className="mb-4">
      How to use: After enabling this repository, you can update and upgrade your system to get the latest testing versions of Proxmox VE packages. Use with caution as these versions may be unstable.
    </p>
    <p className="text-lg mb-2">To manually add the Proxmox testing repository, you can use these commands:</p>
    <CopyableCode
      code={`
    # Add Proxmox testing repository
    echo "deb http://download.proxmox.com/debian/pve $(lsb_release -cs) pvetest" | sudo tee /etc/apt/sources.list.d/pve-testing-repo.list

    # Update package lists
    sudo apt update
      `}
    />
    <p className="mt-4 text-sm text-gray-600">
      Note: $(lsb_release -cs) automatically detects your Proxmox VE version codename (e.g., bullseye).
    </p>
    <p className="mt-4 text-yellow-600">
      Warning: Enabling the testing repository may lead to system instability. It's recommended for testing environments only.
    </p>


    <h3 className="text-xl font-semibold mt-16 mb-4 flex items-center">
      <StepNumber number={5} />
      Install and Configure Fastfetch
    </h3>

    <p className="mb-4">
      This option silently installs and configures Fastfetch, a system information tool that displays system specs and a
      custom logo at login.
    </p>

    <p className="mb-4">
      <strong>What it does:</strong>
    </p>
    <ul className="list-disc pl-5 mb-4">
      <li>Silently downloads and installs the latest version of Fastfetch</li>
      <li>
        Allows you to choose a custom logo (
        <strong>ProxMenux, Proxmox, Helper-Scripts, Home-Labs-Club, Proxmology</strong>, or a custom one)
      </li>
      <li>
        Configures Fastfetch to display <em>"System optimised by ProxMenux"</em>
      </li>
      <li>Sets up Fastfetch to run automatically at console login</li>
    </ul>

    <div className="bg-yellow-100 border-l-4 border-yellow-500 text-yellow-700 p-4 mb-4">
      <p className="font-semibold">Important:</p>
      <p>
        If you connect to Proxmox via SSH, you should select the <strong>Proxmox</strong> logo or create a custom one
        using <code>jp2a</code> or <code>img2txt</code>. The other logos are generated using <code>chafa</code> and may
        not display correctly in a standard SSH session.
      </p>
    </div>

    <div className="bg-blue-100 border-l-4 border-blue-500 text-blue-700 p-4 mb-4">
      <p className="font-semibold">Custom Logos:</p>
      <p>
        To use a custom logo, place your ASCII art text file in: <code>/usr/local/share/fastfetch/logos/</code>
      </p>
      <p>
        You can create custom logos using tools like <code>chafa</code>, <code>jp2a</code>, or <code>img2txt</code>.</p>
      <p>
        For best results:
      </p>
      <ul className="list-disc pl-5 mt-2">
        <li>Keep the logo height to 35 lines or less to maintain proportions and fit in the terminal</li>
        <li>
          Use <code>chafa</code> for color logos (may not display correctly in SSH sessions)
        </li>
        <li>
          Use <code>jp2a</code> or <code>img2txt</code> for SSH-compatible logos
        </li>
      </ul>
    </div>

    <p className="mb-4">
      <strong>Example Logos:</strong>
    </p>

    <div className="grid grid-cols-2 md:grid-cols-3 gap-4">
      <div>
        <p className="font-semibold text-center">ProxMenux</p>
        <img
          src="/images/design-mode/proxmenux.png"
          alt="ProxMenux Logo"
          className="rounded shadow-lg"
        />
      </div>
      <div>
        <p className="font-semibold text-center">Proxmox</p>
        <img
          src="/images/design-mode/proxmox.png"
          alt="Proxmox Logo"
          className="rounded shadow-lg"
        />
      </div>
      <div>
        <p className="font-semibold text-center">Helper-Scripts</p>
        <img
          src="/images/design-mode/helper-scripts.png"
          alt="Helper-Scripts Logo"
          className="rounded shadow-lg"
        />
      </div>
      <div>
        <p className="font-semibold text-center">Home-Labs-Club</p>
        <img
          src="/images/design-mode/home-labs-club.png"
          alt="Home-Labs-Club Logo"
          className="rounded shadow-lg"
        />
      </div>
      <div>
        <p className="font-semibold text-center">Proxmology</p>
        <img
          src="/images/design-mode/proxmology.png"
          alt="Proxmology Logo"
          className="rounded shadow-lg"
        />
      </div>
    </div>

    <p className="text-lg mb-2">This adjustment automates the following commands:</p>
    <CopyableCode
      code={`
# Download and install the latest version of Fastfetch
FASTFETCH_URL=$(curl -s https://api.github.com/repos/fastfetch-cli/fastfetch/releases/latest | grep "browser_download_url.*fastfetch-linux-amd64.deb" | cut -d '"' -f 4)
wget -q -O /tmp/fastfetch.deb "$FASTFETCH_URL"
dpkg -i /tmp/fastfetch.deb 
apt-get install -f -y 

# Configure Fastfetch (logo selection remains interactive)
# The configuration is done through a series of jq commands

# Set Fastfetch to run at login
echo "clear && fastfetch" >> ~/.bashrc
      `}
    />

    
	<h3 className="text-xl font-semibold mt-16 mb-4 flex items-center">
        <StepNumber number={6} />
        Install and Configure Figurine
      </h3>

      <p className="mb-4">
        This option installs and configures Figurine, a tool that creates stylish ASCII text banners for your terminal,
        displaying your hostname in a visually appealing 3D format.
      </p>

      <p className="mb-4">
        <strong>What it does:</strong>
      </p>
      <ul className="list-disc pl-5 mb-4">
        <li>Downloads and installs Figurine v1.3.0 from GitHub</li>
        <li>Creates a welcome message that displays your hostname in 3D ASCII art when you log in</li>
        <li>Automatically removes any previous Figurine installation if present</li>
        <li>Sets up the welcome message to run automatically at login</li>
      </ul>

      <div className="bg-blue-100 border-l-4 border-blue-500 text-blue-700 p-4 mb-4">
        <p className="font-semibold">Practical Use:</p>
        <p>
          When managing multiple Proxmox nodes in a cluster, Figurine provides an immediate visual indication of which
          node you're currently logged into. This helps prevent accidental commands on the wrong node and improves your
          workflow when managing multiple servers.
        </p>
      </div>

      <p className="mb-4">
        <strong>Example Output:</strong>
      </p>

      <div className="mb-6 flex justify-center">
        <img
          src="/images/design-mode/figurine.png"
          alt="Figurine Example Output"
          className="rounded-md shadow-lg border border-gray-200"
          style={{ maxWidth: "100%" }}
        />
      </div>

      <p className="text-lg mb-2">This adjustment automates the following process:</p>
      <CopyableCode
        code={`
# Check for previous installation and remove if found
if command -v figurine &> /dev/null; then
  rm -f "/usr/local/bin/figurine"
fi

# Download and install Figurine
version="1.3.0"
file="figurine_linux_amd64_v\${version}.tar.gz"
url="https://github.com/arsham/figurine/releases/download/v\${version}/\${file}"
wget -qO "/tmp/\${file}" "\${url}"
tar -xf "/tmp/\${file}" -C "/tmp"
mv "/tmp/deploy/figurine" "/usr/local/bin/figurine"
chmod +x "/usr/local/bin/figurine"

# Create welcome message script
cat << 'EOF' > "/etc/profile.d/figurine.sh"
/usr/local/bin/figurine -f "3d.flf" $(hostname)
EOF
chmod +x "/etc/profile.d/figurine.sh"
  `}
     />

      <p className="mt-4">
        After installation, you'll see your hostname displayed in 3D ASCII art each time you log in, making it
        immediately clear which Proxmox node you're working on.
      </p>
	

      <section className="mt-12 p-4 bg-blue-100 rounded-md">
        <h2 className="text-xl font-semibold mb-2">Automatic Application</h2>
        <p>
          These optional features are applied only when specifically selected during the post-install process. Each
          feature can be individually chosen based on your specific needs and preferences.
        </p>
      </section>
    </div>
  )
}
