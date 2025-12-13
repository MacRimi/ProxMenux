import type { Metadata } from "next"
import { HardDrive } from "lucide-react"
import CopyableCode from "@/components/CopyableCode"

export const metadata: Metadata = {
  title: "ProxMenux Post-Install: Storage Settings",
  description:
    "Comprehensive guide to Storage Settings in the ProxMenux post-install script for optimizing Proxmox VE storage performance and configuration.",
  openGraph: {
    title: "ProxMenux Post-Install: Storage Settings",
    description:
      "Comprehensive guide to Storage Settings in the ProxMenux post-install script for optimizing Proxmox VE storage performance and configuration.",
    type: "article",
    url: "https://macrimi.github.io/ProxMenux/docs/post-install/storage",
    images: [
      {
        url: "https://macrimi.github.io/ProxMenux/storage-settings-image.png",
        width: 1200,
        height: 630,
        alt: "ProxMenux Post-Install Storage Settings",
      },
    ],
  },
  twitter: {
    card: "summary_large_image",
    title: "ProxMenux Post-Install: Storage Settings",
    description:
      "Comprehensive guide to Storage Settings in the ProxMenux post-install script for optimizing Proxmox VE storage performance and configuration.",
    images: ["https://macrimi.github.io/ProxMenux/storage-settings-image.png"],
  },
}

function StepNumber({ number }: { number: number }) {
  return (
    <div className="inline-flex items-center justify-center w-8 h-8 mr-3 text-white bg-blue-500 rounded-full">
      <span className="text-sm font-bold">{number}</span>
    </div>
  )
}

export default function StorageSettingsPage() {
  return (
    <div className="container mx-auto px-4 py-8">
      <div className="flex items-center mb-6">
        <HardDrive className="h-8 w-8 mr-2 text-blue-500" />
        <h1 className="text-3xl font-bold">Storage Settings</h1>
      </div>
      <p className="mb-4">
        The <strong>Storage Settings</strong> category optimizes storage configuration and performance in Proxmox VE. 
        These optimizations are essential for efficient storage operations in virtualized environments where multiple VMs 
        and containers share storage resources.
      </p>
      <h2 className="text-2xl font-semibold mt-8 mb-4">Available Optimizations</h2>

      <h3 className="text-xl font-semibold mt-16 mb-4 flex items-center">
        <StepNumber number={1} />
        Increase vzdump Backup Speed
      </h3>
      <p className="mb-4">
      This optimization configures <strong>vzdump</strong> to enhance backup speed by adjusting bandwidth limits and I/O priority.
      </p>
      <p className="mb-4">
      <strong className="block">Why it's beneficial:</strong>
        Faster backups reduce the impact on system performance during backup
        operations and allow for more frequent backups, improving data protection. This is particularly important in
        environments with large amounts of data or tight backup windows.
      </p>
      <p className="text-lg mb-2">This adjustment automates the following commands:</p>
      <CopyableCode
        code={`
# Configure bandwidth limit
sed -i '/^#*bwlimit:/d' /etc/vzdump.conf
echo "bwlimit: 0" >> /etc/vzdump.conf

# Configure I/O priority
sed -i '/^#*ionice:/d' /etc/vzdump.conf
echo "ionice: 5" >> /etc/vzdump.conf
      `}
      />

      <h3 className="text-xl font-semibold mt-16 mb-4 flex items-center">
        <StepNumber number={2} />
        Install and Configure ZFS Auto-snapshot
      </h3>
      <p className="mb-4">
        This optimization installs the zfs-auto-snapshot package and configures automatic ZFS snapshots at various
        intervals.
      </p>
      <p className="mb-4">
      <strong className="block">Why it's beneficial:</strong>
        Automatic ZFS snapshots provide a robust and efficient method for
        point-in-time recovery, protecting against data loss or corruption. This is especially useful in virtualized
        environments where quick recovery options are crucial.
      </p>
      <p className="text-lg mb-2">This adjustment automates the following commands:</p>
      <CopyableCode
        code={`
# Install zfs-auto-snapshot
apt-get -y install zfs-auto-snapshot

# Configure snapshot schedules
sed -i 's|^\*/[0-9]*.*--keep=[0-9]*|*/15 * * * * root /usr/sbin/zfs-auto-snapshot --quiet --syslog --label=frequent --keep=4|' /etc/cron.d/zfs-auto-snapshot
sed -i 's|--keep=[0-9]*|--keep=1|g' /etc/cron.hourly/zfs-auto-snapshot
sed -i 's|--keep=[0-9]*|--keep=1|g' /etc/cron.daily/zfs-auto-snapshot
sed -i 's|--keep=[0-9]*|--keep=1|g' /etc/cron.weekly/zfs-auto-snapshot
sed -i 's|--keep=[0-9]*|--keep=1|g' /etc/cron.monthly/zfs-auto-snapshot
      `}
      />

      <h3 className="text-xl font-semibold mt-16 mb-4 flex items-center">
        <StepNumber number={3} />
        Optimize ZFS ARC Size
      </h3>
      <p className="mb-4">
        This optimization adjusts the ZFS Adaptive Replacement Cache (ARC) size based on the system's available memory.
      </p>
      <p className="mb-4">
      <strong className="block">Why it's beneficial:</strong>
        Properly tuned ZFS ARC can significantly improve storage performance by
        caching frequently accessed data in RAM. This optimization ensures that ZFS uses an appropriate amount of memory
        based on the system's resources, balancing between storage performance and leaving enough memory for other
        processes.
      </p>
      <p className="text-lg mb-2">This adjustment automates the following commands:</p>
      <CopyableCode
        code={`
# Calculate ZFS ARC sizes based on RAM
RAM_SIZE_GB=$(free -g | awk '/^Mem:/{print $2}')
if [[ "$RAM_SIZE_GB" -le 16 ]]; then
    MY_ZFS_ARC_MIN=536870911  # 512MB
    MY_ZFS_ARC_MAX=536870912  # 512MB
elif [[ "$RAM_SIZE_GB" -le 32 ]]; then
    MY_ZFS_ARC_MIN=1073741823  # 1GB
    MY_ZFS_ARC_MAX=1073741824  # 1GB
else
    MY_ZFS_ARC_MIN=$((RAM_SIZE_GB * 1073741824 / 16))
    MY_ZFS_ARC_MAX=$((RAM_SIZE_GB * 1073741824 / 8))
fi

# Apply ZFS tuning parameters
cat <<EOF > /etc/modprobe.d/99-zfsarc.conf
# ZFS tuning
options zfs zfs_arc_min=$MY_ZFS_ARC_MIN
options zfs zfs_arc_max=$MY_ZFS_ARC_MAX

# Enable prefetch method
options zfs l2arc_noprefetch=0

# Set max write speed to L2ARC (500MB)
options zfs l2arc_write_max=524288000
options zfs zfs_txg_timeout=60
EOF
      `}
      />

      <section className="mt-12 p-4 bg-blue-100 rounded-md">
        <h2 className="text-xl font-semibold mb-2">Automatic Application</h2>
        <p>
          All of these optimizations are automatically applied when selected in the Storage section. This automation
          ensures that these beneficial settings are applied consistently and correctly, saving time and reducing the
          potential for human error during manual configuration.
        </p>
      </section>
    </div>
  )
}

