import type { Metadata } from "next"
import { Settings } from "lucide-react"
import CopyableCode from "@/components/CopyableCode"

export const metadata: Metadata = {
  title: "ProxMenux Post-Install: Basic Settings",
  description:
    "Detailed guide to the Basic Settings category in the ProxMenux post-install script for Proxmox VE optimization.",
  openGraph: {
    title: "ProxMenux Post-Install: Basic Settings",
    description:
      "Detailed guide to the Basic Settings category in the ProxMenux post-install script for Proxmox VE optimization.",
    type: "article",
    url: "https://macrimi.github.io/ProxMenux/docs/post-install/basic-settings",
    images: [
      {
        url: "https://macrimi.github.io/ProxMenux/basic-settings-image.png",
        width: 1200,
        height: 630,
        alt: "ProxMenux Post-Install Basic Settings",
      },
    ],
  },
  twitter: {
    card: "summary_large_image",
    title: "ProxMenux Post-Install: Basic Settings",
    description:
      "Detailed guide to the Basic Settings category in the ProxMenux post-install script for Proxmox VE optimization.",
    images: ["https://macrimi.github.io/ProxMenux/basic-settings-image.png"],
  },
}

function StepNumber({ number }: { number: number }) {
  return (
    <div className="inline-flex items-center justify-center w-8 h-8 mr-3 text-white bg-blue-500 rounded-full">
      <span className="text-sm font-bold">{number}</span>
    </div>
  )
}

export default function BasicSettingsPage() {
  return (
    <div className="container mx-auto px-4 py-8">
      <div className="flex items-center mb-6">
        <Settings className="h-8 w-8 mr-2 text-blue-500" />
        <h1 className="text-3xl font-bold">Basic Settings</h1>
      </div>
      <p className="mb-4">
        The <strong>Basic Settings</strong> category focuses on foundational configurations for your Proxmox VE
        installation, including installing essential utilities, adding repositories, managing packages, and keeping the
        system up to date.
      </p>
      <h2 className="text-2xl font-semibold mt-8 mb-4">Available Optimizations</h2>

      <h3 className="text-xl font-semibold mt-16 mb-4 flex items-center">
        <StepNumber number={1} />
        Select and Install System Utilities
      </h3>
      <p className="mb-4">
        This option presents a menu where you can select which system utilities to install based on your needs.
      </p>

      
      <div className="mb-6">
        <img
          src="https://macrimi.github.io/ProxMenux/basic/menu_utilities.png"
          alt="System Utilities Selection Menu"
          className="rounded shadow-lg border border-gray-200"
        />
        <p className="text-sm text-gray-600 mt-2 text-center">The utilities selection menu allows you to choose which tools to install</p>
      </div>
      
      <h4 className="text-lg font-semibold mb-2">Available utilities:</h4>
      <ul className="list-disc pl-5 mb-4 space-y-12">

      <li>
        <strong>axel</strong>: A light command-line download accelerator
        <p className="mt-2">Example usage:</p>
        <code className="block bg-gray-100 p-2 rounded">axel -n 10 http://example.com/largefile.zip</code>
      </li>
      <li>
        <strong>dialog</strong>: A tool for creating TUI interfaces
        <p className="mt-2">Example usage:</p>
        <code className="block bg-gray-100 p-2 rounded">dialog --title "Hello" --msgbox "Hello, World!" 10 20</code>
        <img
          src="https://macrimi.github.io/ProxMenux/basic/dialog.png"
          alt="Dialog Example"
          className="mt-2 rounded shadow-lg"
        />
      </li>
      <li>
        <strong>dos2unix</strong>: Text file format converter to remove Windows-style line endings.
        <p className="mt-2">Example usage:</p>
        <code className="block bg-gray-100 p-2 rounded">dos2unix file.txt</code>
      </li>
      <li>
        <strong>grc</strong>: Generic colouriser for everything
        <p className="mt-2">Example usage (colorize ping output):</p>
        <code className="block bg-gray-100 p-2 rounded">grc ping example.com</code>
      </li>
      <li>
        <strong>htop</strong>: An interactive process viewer
        <p className="mt-2">To start htop, simply type:</p>
        <code className="block bg-gray-100 p-2 rounded">htop</code>
        <img
          src="https://macrimi.github.io/ProxMenux/basic/htop.png"
          alt="htop Example"
          className="mt-2 rounded shadow-lg"
        />
      </li>
      <li>
        <strong>btop</strong>: A resource monitor that shows usage and stats for processor, memory, disks, network and processes
        <p className="mt-2">To start btop, type:</p>
        <code className="block bg-gray-100 p-2 rounded">btop</code>
        <img
          src="https://macrimi.github.io/ProxMenux/basic/btop.png"
          alt="btop Example"
          className="mt-2 rounded shadow-lg"
        />
      </li>
     <li>
        <strong>iftop</strong>: A tool to display bandwidth usage on an interface
        <p className="mt-2">To start iftop (requires root):</p>
        <code className="block bg-gray-100 p-2 rounded">iftop</code>
        <img
          src="https://macrimi.github.io/ProxMenux/basic/iftop.png"
          alt="iftop Example"
          className="mt-2 rounded shadow-lg"
        />
      </li>
      <li>
        <strong>iotop</strong>: A tool to display I/O usage by processes
        <p className="mt-2">To start iotop (requires root):</p>
        <code className="block bg-gray-100 p-2 rounded">siotop</code>
        <img
          src="https://macrimi.github.io/ProxMenux/basic/iotop.png"
          alt="iotop Example"
          className="mt-2 rounded shadow-lg"
        />
      </li>
      <li>
        <strong>iperf3</strong>: A tool for active measurements of the maximum achievable bandwidth on IP networks
        <p className="mt-2">Example usage (server mode):</p>
        <code className="block bg-gray-100 p-2 rounded">iperf3 -s</code>
        <p className="mt-2">Example usage (client mode):</p>
        <code className="block bg-gray-100 p-2 rounded">iperf3 -c server_ip</code>
      </li>
      <li>
        <strong>ipset</strong>: A tool to manage IP sets in the Linux kernel
        <p className="mt-2">Example usage (create a new set):</p>
        <code className="block bg-gray-100 p-2 rounded">ipset create myset hash:ip</code>
      </li>
      <li>
        <strong>iptraf-ng</strong>: An interactive colorful IP LAN monitor
        <p className="mt-2">To start iptraf-ng:</p>
        <code className="block bg-gray-100 p-2 rounded">iptraf-ng</code>
        <img
          src="https://macrimi.github.io/ProxMenux/basic/iptraf-ng.png"
          alt="iptraf-ng Example"
          className="mt-2 rounded shadow-lg"
        />
      </li>
     <li>
        <strong>mlocate</strong>: A tool to find files by name quickly
        <p className="mt-2">Example usage:</p>
        <code className="block bg-gray-100 p-2 rounded">locate filename</code>
      </li>
      <li>
        <strong>msr-tools</strong>: Tools for accessing CPU model-specific registers
        <p className="mt-2">Example usage (read MSR):</p>
        <code className="block bg-gray-100 p-2 rounded">rdmsr 0x1a0</code>
      </li>
      <li>
        <strong>net-tools</strong>: A collection of programs that form the base set of the NET-3 networking distribution for the Linux operating system
        <p className="mt-2">Example usage (show network interfaces):</p>
        <code className="block bg-gray-100 p-2 rounded">ifconfig</code>
      </li>
      <li>
        <strong>sshpass</strong>: A tool for non-interactive SSH password authentication.
        <p className="mt-2">Example usage:</p>
        <code className="block bg-gray-100 p-2 rounded">sshpass -p 'password' ssh user@hostname</code>
      </li>
      <li>
        <strong>tmux</strong>: A terminal multiplexer that allows managing multiple sessions in a single terminal.
        <p className="mt-2">To start a new tmux session:</p>
        <code className="block bg-gray-100 p-2 rounded">tmux</code>
        <p className="mt-2">In tmux, most commands are executed using <strong>Ctrl + b</strong>, followed by another key:</p>
        <table className="table-auto border-collapse border border-gray-300 mt-2">
          <thead>
            <tr>
              <th className="border border-gray-300 p-2">Action</th>
              <th className="border border-gray-300 p-2">Shortcut</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td className="border border-gray-300 p-2">Detach session (leave it running)</td>
              <td className="border border-gray-300 p-2">Ctrl + b, then d</td>
            </tr>
            <tr>
              <td className="border border-gray-300 p-2">List active sessions</td>
              <td className="border border-gray-300 p-2">tmux ls</td>
            </tr>
            <tr>
              <td className="border border-gray-300 p-2">Reattach a session</td>
              <td className="border border-gray-300 p-2">tmux attach -t session_name</td>
            </tr>
            <tr>
              <td className="border border-gray-300 p-2">Exit session</td>
              <td className="border border-gray-300 p-2">exit or Ctrl + d</td>
            </tr>
          </tbody>
        </table>
        <img
          src="https://macrimi.github.io/ProxMenux/basic/tmux.png"
          alt="tmux Example"
          className="mt-2 rounded shadow-lg"
        />
      </li>
      <li>
        <strong>unzip</strong>: A tool for extracting and viewing files in .zip archives
        <p className="mt-2">Example usage:</p>
        <code className="block bg-gray-100 p-2 rounded">unzip file.zip</code>
      </li>
      <li>
        <strong>whois</strong>: A client for the whois directory service
        <p className="mt-2">Example usage:</p>
        <code className="block bg-gray-100 p-2 rounded">whois example.com</code>
      </li>
      <li>
        <strong>zip</strong>: A compression and file packaging utility
        <p className="mt-2">Example usage:</p>
        <code className="block bg-gray-100 p-2 rounded">zip archive.zip file1 file2 file3</code>
      </li>
      <li>
        <strong>libguestfs-tools</strong>: A set of tools for accessing and modifying virtual machine disk images.
        <p className="mt-2">Example usage (list files in a VM disk image):</p>
        <code className="block bg-gray-100 p-2 rounded">guestfish -a disk.img -m /dev/sda1 ls /</code>
      </li>

      </ul>
      <p className="text-lg mt-12 mb-2">This option automatically installs these utilities by running this command:</p>
      <CopyableCode
        code={`
# Update package lists
sudo apt-get update

# Install common system utilities
sudo apt-get install -y axel dialog dos2unix grc htop btop iftop iotop iperf3 ipset iptraf-ng mlocate msr-tools net-tools omping sshpass tmux unzip zip libguestfs-tools

        `}
      />

      <h3 className="text-xl font-semibold mt-16 mb-4 flex items-center">
        <StepNumber number={2} />
        Skip Downloading Additional Languages
      </h3>
      <p className="mb-4">
        This optimization configures APT to skip downloading additional language packages, which can save disk space and
        speed up package operations.
      </p>
      <p className="mb-4">
      <strong className="block">Why it's beneficial:</strong>
        By skipping unnecessary language packages, you can reduce disk usage and
        improve the speed of package management operations. This is particularly useful in server environments where
        multiple language support is often not required.
      </p>
      <p className="text-lg mb-2">This adjustment automates the following command:</p>
      <CopyableCode
        code={`
# Configure APT to skip downloading additional languages
echo 'Acquire::Languages "none";' | sudo tee /etc/apt/apt.conf.d/99-disable-translations
        `}
      />

      <h3 className="text-xl font-semibold mt-16 mb-4 flex items-center">
        <StepNumber number={3} />
        Synchronize Time Automatically
      </h3>
      <p className="mb-4">
        This optimization configures the system to automatically synchronize its time, ensuring accurate timekeeping.
      </p>
      <p className="mb-4">
      <strong className="block">Why it's beneficial:</strong>
        Accurate timekeeping is crucial for many system operations, log
        consistency, and proper functioning of time-sensitive applications. Automatic synchronization ensures your
        Proxmox VE system maintains the correct time without manual intervention.
      </p>
      <p className="text-lg mb-2">This adjustment automates the following command:</p>
      <CopyableCode
        code={`
# Note: To set timezone automatically based on IP, you can use:
IP=$(dig +short myip.opendns.com @resolver1.opendns.com)
TIMEZONE=$(curl -s "https://ipapi.co/$IP/timezone")
sudo timedatectl set-timezone "$TIMEZONE"
        `}
      />

<h3 className="text-xl font-semibold mt-16 mb-4 flex items-center">
        <StepNumber number={4} />
        Update and Upgrade System
      </h3>
      <p className="mb-4">
        This optimization updates the system's package lists, upgrades installed packages, and configures Proxmox
        repositories. It also includes additional steps to properly set up Debian repositories, disable certain
        warnings, and perform safety checks after the update process.
      </p>
      <p className="mb-4">
      <strong className="block">Why it's beneficial:</strong>
        Keeping your system up-to-date is essential for security, stability, and
        performance. This optimization ensures you have the latest patches and features, while also configuring the
        correct repositories for Proxmox VE, enabling access to necessary updates and tools. The disk metadata check helps prevent potential issues with storage devices that may have been modified by virtual machines.
      </p>
      <h4 className="text-lg font-semibold mb-2">Repository changes:</h4>
      <ul className="list-disc pl-5 mb-4 space-y-2">
        <li>
          <strong>Disabled:</strong> Enterprise Proxmox repository (pve-enterprise.list) - This repository is for users
          with a paid subscription.
        </li>
        <li>
          <strong>Disabled:</strong> Enterprise Proxmox Ceph repository (ceph.list) - This repository is for enterprise
          Ceph storage solutions.
        </li>
        <li>
          <strong>Added:</strong> Free public Proxmox repository (pve-public-repo.list) - This provides access to free
          Proxmox VE updates and packages.
        </li>
        <li>
          <strong>Configured:</strong> Main Debian repositories - These provide access to the core Debian packages and
          security updates.
        </li>
      </ul>
      <p className="text-lg mb-2">This adjustment automates the following command:</p>
      <CopyableCode
        code={`
# Disable enterprise Proxmox repository
if [ -f /etc/apt/sources.list.d/pve-enterprise.list ]; then
  sudo sed -i 's/^deb/#deb/g' /etc/apt/sources.list.d/pve-enterprise.list
fi

# Disable enterprise Proxmox Ceph repository
if [ -f /etc/apt/sources.list.d/ceph.list ]; then
  sudo sed -i 's/^deb/#deb/g' /etc/apt/sources.list.d/ceph.list
fi

# Enable free public Proxmox repository
echo "deb http://download.proxmox.com/debian/pve $(lsb_release -cs) pve-no-subscription" | sudo tee /etc/apt/sources.list.d/pve-public-repo.list


# Configure main Debian repositories
cat <<EOF | sudo tee /etc/apt/sources.list
deb http://deb.debian.org/debian $(lsb_release -cs) main contrib non-free non-free-firmware
deb http://deb.debian.org/debian $(lsb_release -cs)-updates main contrib non-free non-free-firmware
deb http://security.debian.org/debian-security $(lsb_release -cs)-security main contrib non-free non-free-firmware
EOF

# Disable non-free firmware warnings
echo 'APT::Get::Update::SourceListWarnings::NonFreeFirmware "false";' | sudo tee /etc/apt/apt.conf.d/no-bookworm-firmware.conf

# Update and upgrade
sudo apt-get update
sudo apt-get dist-upgrade -y

# Update PVE application manager
pveam update

# Install additional packages
sudo apt-get install -y zfsutils-linux proxmox-backup-restore-image chrony
  `}
/>
<div className="mt-6 p-4 bg-blue-50 border-l-4 border-blue-500 rounded-md">
        <h4 className="text-lg font-semibold mb-2 text-black">Post-Update Safety Check</h4>
        <p className="text-gray-700 mb-2">
          After updating the system, the script performs an important safety check to detect disks with old PV (Physical Volume) headers that might have been modified by virtual machines.
        </p>
        <p className="text-gray-700 mb-2">
          <strong>Why this matters:</strong> When VMs have direct access to disks through passthrough, they can sometimes modify the disk metadata. This can cause issues with storage management on the host system, potentially leading to data access problems or errors when using LVM (Logical Volume Manager).
        </p>
        <p className="text-gray-700">
          If any issues are detected, the script will display a warning message and suggest running the <code className="bg-gray-100 px-1 py-0.5 rounded text-black">pvs</code> command to identify the affected disks. This early detection helps prevent potential storage problems before they impact your system.
        </p>
      </div>
    </div>
  )
}

