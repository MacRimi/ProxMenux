import type { Metadata } from "next"
import { getTranslations, getMessages, setRequestLocale } from "next-intl/server"
import { Link } from "@/i18n/navigation"
import Image from "next/image"
import { DocHeader } from "@/components/ui/doc-header"
import { Callout } from "@/components/ui/callout"
import CopyableCode from "@/components/CopyableCode"

export async function generateMetadata({
  params,
}: {
  params: Promise<{ locale: string }>
}): Promise<Metadata> {
  const { locale } = await params
  const t = await getTranslations({ locale, namespace: "docs.storageShare.hostLocalDisk.meta" })
  return {
    title: t("title"),
    description: t("description"),
    openGraph: {
      title: t("ogTitle"),
      description: t("ogDescription"),
      type: "article",
      url: "https://macrimi.github.io/ProxMenux/docs/storage-share/host-local-disk",
    },
  }
}

type CompareRow = { label: string; dir?: string; zfs?: string; dirRich?: string; zfsRich?: string }
type StringItem = string
type PresetRow = { preset: string; content: string; use?: string; useRich?: string }
type RelatedItem = { href: string; label: string; tail?: string }

export default async function HostLocalDiskPage({
  params,
}: {
  params: Promise<{ locale: string }>
}) {
  const { locale } = await params
  setRequestLocale(locale)
  const t = await getTranslations({ locale, namespace: "docs.storageShare.hostLocalDisk" })

  const messages = (await getMessages({ locale })) as unknown as {
    docs: { storageShare: { hostLocalDisk: {
      compare: { rows: CompareRow[] }
      format: { items: StringItem[] }
      reuse: { items: StringItem[] }
      presets: { rows: PresetRow[] }
      troubleshoot: { noDisksItems: StringItem[] }
      related: { items: RelatedItem[] }
    } } }
  }
  const compareRows = messages.docs.storageShare.hostLocalDisk.compare.rows
  const formatItems = messages.docs.storageShare.hostLocalDisk.format.items
  const reuseItems = messages.docs.storageShare.hostLocalDisk.reuse.items
  const presetRows = messages.docs.storageShare.hostLocalDisk.presets.rows
  const noDisksItems = messages.docs.storageShare.hostLocalDisk.troubleshoot.noDisksItems
  const relatedItems = messages.docs.storageShare.hostLocalDisk.related.items

  const code = (chunks: React.ReactNode) => <code>{chunks}</code>
  const strong = (chunks: React.ReactNode) => <strong>{chunks}</strong>
  const em = (chunks: React.ReactNode) => <em>{chunks}</em>

  return (
    <div>
      <DocHeader
        title={t("header.title")}
        description={t("header.description")}
        section={t("header.section")}
        estimatedMinutes={10}
        scriptPath="share/disk_host.sh"
      />

      <Callout variant="info" title={t("intro.title")}>
        {t.rich("intro.body", { em, strong })}
      </Callout>

      <Callout variant="danger" title={t("destructive.title")}>
        {t.rich("destructive.body", { em, strong, code })}
      </Callout>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("compare.heading")}</h2>
      <div className="overflow-x-auto mb-4 rounded-md border border-gray-200">
        <table className="min-w-full text-sm">
          <thead className="bg-gray-50 text-left text-gray-700">
            <tr>
              <th className="px-4 py-2 font-semibold">&nbsp;</th>
              <th className="px-4 py-2 font-semibold">{t("compare.headerDir")}</th>
              <th className="px-4 py-2 font-semibold">{t("compare.headerZfs")}</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-200 text-gray-800">
            {compareRows.map((row, idx) => (
              <tr key={row.label}>
                <td className="px-4 py-2 font-semibold">{row.label}</td>
                <td className="px-4 py-2">{row.dirRich ? t.rich(`compare.rows.${idx}.dirRich`, { code }) : row.dir}</td>
                <td className="px-4 py-2">{row.zfsRich ? t.rich(`compare.rows.${idx}.zfsRich`, { code }) : row.zfs}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("opening.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("opening.body", { strong })}
      </p>

      <Image
        src="/share/host-local-disk-menu.png"
        alt={t("opening.imageAlt")}
        width={900}
        height={500}
        className="rounded shadow-lg my-6"
      />

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("howRuns.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">{t("howRuns.body")}</p>

      <pre className="bg-gray-100 text-gray-800 p-4 rounded-md overflow-x-auto text-sm my-4 border border-gray-200 leading-snug">
{`┌─────────────────────────────────────────────┐
│  PHASE 1 — Detect, inspect, plan            │
│  (nothing touched yet)                      │
└──────────────────┬──────────────────────────┘
                   ▼
      Dependency check
      └─ parted / mkfs.ext4 / mkfs.xfs / blkid /
         lsblk / sgdisk present?
         If any missing → apt-get install
             parted e2fsprogs util-linux
             xfsprogs gdisk btrfs-progs
                   │
                   ▼
      Disk detection (lsblk -dn -e 7,11)
                   │
                   ▼
      Safety filter
      ├─ Hidden: type != "disk" (skip partitions)
      ├─ Hidden: read-only (ro=1)
      ├─ Hidden: /dev/zd* (ZFS volumes, not disks)
      ├─ Hidden: used by host storage
      │         (root pool, mounted paths, ZFS/LVM)
      └─ Hidden: referenced by any VM/LXC config
                   │
                   ▼
      User selects a disk
      (menu shows disk path + size + model)
                   │
                   ▼
      Disk inspection (blkid / lsblk)
      ├─ Has data → offer 2 actions:
      │      ├─ Format disk (ERASE all)
      │      └─ Use existing filesystem
      └─ Empty     → only "Format disk"
                   │
                   ▼
      If "Format" was chosen:
      Filesystem picker
      ├─ ext4   → dir storage (recommended general use)
      ├─ xfs    → dir storage (large files / VMs)
      ├─ btrfs  → dir storage (snapshots / compression)
      └─ zfs    → ZFS POOL storage (different path)
                   │
                   ▼
      Storage ID  (default: "disk-<device>")
      Mount path  (default: "/mnt/<storage-id>")
      Content types  (4 presets + custom):
      ├─ 1. VM Storage     → images,backup
      ├─ 2. Standard NAS   → backup,iso,vztmpl
      ├─ 3. All types      → images,backup,iso,vztmpl,snippets
      └─ 4. Custom         → free CSV input
                   │
   ┌──────── Cancel   OR   Confirm ────┐
   ▼                                   ▼
Exit, nothing        ┌─────────────────┴─────────────────┐
was changed          │  PHASE 2 — Execute                 │
                     └─────────────────┬─────────────────┘
                                       ▼
                       FORMAT PATH (destructive):
                       ├─ Final "ERASE confirmation" dialog
                       │   → Cancel exits here
                       ├─ wipefs + sgdisk --zap-all
                       ├─ parted/sgdisk: create partition
                       ├─ ZFS pre-flight:
                       │   • zpool command present?
                       │   • pool name not already in use?
                       ├─ mkfs.<fs> / zpool create
                       │   (mkfs.ext4 / xfs / btrfs / zfs pool)
                       ├─ Non-ZFS: mount -t <fs> + UUID
                       │     entry in /etc/fstab with
                       │     defaults,nofail
                       └─ ZFS: zpool manages its own mount
                                       ▼
                       REUSE PATH (existing fs):
                       ├─ blkid detects filesystem type
                       ├─ mkdir mount point
                       ├─ mount <disk> <path>
                       └─ UUID entry in /etc/fstab
                                       ▼
                       Register in Proxmox:
                       ├─ filesystem == zfs →
                       │    pvesm add zfspool <id> \\
                       │         --pool <id> \\
                       │         --content <csv>
                       └─ otherwise →
                            pvesm add dir <id> \\
                                --path <mount-path> \\
                                --content <csv>
                                       ▼
                       Summary + "visible in Datacenter →
                       Storage" confirmation`}
      </pre>

      <h2 className="text-2xl font-semibold mt-12 mb-4 text-gray-900">{t("format.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">{t("format.intro")}</p>
      <ol className="list-decimal pl-6 mb-4 text-gray-800 leading-relaxed space-y-2">
        {formatItems.map((_, idx) => (
          <li key={idx}>{t.rich(`format.items.${idx}`, { code, strong })}</li>
        ))}
      </ol>

      <Callout variant="tip" title={t("format.tipTitle")}>
        {t.rich("format.tipBody", { code })}
      </Callout>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("reuse.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">{t("reuse.intro")}</p>
      <ol className="list-decimal pl-6 mb-4 text-gray-800 leading-relaxed space-y-2">
        {reuseItems.map((_, idx) => (
          <li key={idx}>{t.rich(`reuse.items.${idx}`, { code, strong })}</li>
        ))}
      </ol>

      <Callout variant="warning" title={t("reuse.warnTitle")}>
        {t.rich("reuse.warnBody", { em, code })}
      </Callout>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("presets.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">{t.rich("presets.intro", { code })}</p>
      <div className="overflow-x-auto mb-4 rounded-md border border-gray-200">
        <table className="min-w-full text-sm">
          <thead className="bg-gray-50 text-left text-gray-700">
            <tr>
              <th className="px-4 py-2 font-semibold">{t("presets.headerPreset")}</th>
              <th className="px-4 py-2 font-semibold">{t("presets.headerContent")}</th>
              <th className="px-4 py-2 font-semibold">{t("presets.headerUse")}</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-200 text-gray-800">
            {presetRows.map((row, idx) => (
              <tr key={row.preset}>
                <td className="px-4 py-2 font-semibold">{row.preset}</td>
                <td className="px-4 py-2 font-mono">{row.content}</td>
                <td className="px-4 py-2">
                  {row.useRich ? t.rich(`presets.rows.${idx}.useRich`, { code }) : row.use}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <Callout variant="info" title={t("presets.zfsTitle")}>
        {t.rich("presets.zfsBody", { strong, code })}
      </Callout>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("manual.heading")}</h2>
      <p className="mb-3 text-gray-800 leading-relaxed">{t("manual.extIntro")}</p>
      <CopyableCode code={`# 1. prerequisites (one-time)
apt-get install -y parted e2fsprogs xfsprogs gdisk btrfs-progs

# 2. wipe + partition
wipefs -af /dev/sdX
sgdisk --zap-all /dev/sdX
sgdisk -n 1:0:0 -t 1:8300 /dev/sdX

# 3. format
mkfs.ext4 -L mydisk /dev/sdX1

# 4. mount + fstab (by UUID, nofail)
mkdir -p /mnt/mydisk
UUID=$(blkid -s UUID -o value /dev/sdX1)
echo "UUID=$UUID  /mnt/mydisk  ext4  defaults,nofail  0  2" >> /etc/fstab
mount /mnt/mydisk

# 5. register in Proxmox
pvesm add dir mydisk \\
  --path /mnt/mydisk \\
  --content images,backup`} />

      <p className="mb-3 mt-6 text-gray-800 leading-relaxed">{t("manual.zfsIntro")}</p>
      <CopyableCode code={`# 1. create the pool on the raw disk (no partition step needed)
zpool create -o ashift=12 tank /dev/sdX

# 2. register in Proxmox
pvesm add zfspool tank \\
  --pool tank \\
  --content images,rootdir

pvesm status tank`} />

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("view.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">{t.rich("view.body", { code })}</p>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("remove.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">{t.rich("remove.body", { code, strong })}</p>

      <Callout variant="warning" title={t("remove.warnTitle")}>
        {t("remove.warnBody")}
      </Callout>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("list.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">{t.rich("list.body", { code })}</p>

      <h2 className="text-2xl font-semibold mt-12 mb-4 text-gray-900">{t("troubleshoot.heading")}</h2>

      <Callout variant="troubleshoot" title={t("troubleshoot.noDisksTitle")}>
        {t("troubleshoot.noDisksIntro")}
        <ul className="mt-2 list-disc list-inside space-y-1">
          {noDisksItems.map((_, idx) => (
            <li key={idx}>{t(`troubleshoot.noDisksItems.${idx}`)}</li>
          ))}
        </ul>
        {t.rich("troubleshoot.noDisksOutro", { em, code })}
      </Callout>

      <Callout variant="troubleshoot" title={t("troubleshoot.mountedTitle")}>
        {t.rich("troubleshoot.mountedBody", { code })}
      </Callout>

      <Callout variant="troubleshoot" title={t("troubleshoot.zpoolTitle")}>
        {t.rich("troubleshoot.zpoolBody", { code })}
      </Callout>

      <Callout variant="troubleshoot" title={t("troubleshoot.inactiveTitle")}>
        {t.rich("troubleshoot.inactiveBody", { code })}
      </Callout>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("related.heading")}</h2>
      <ul className="list-disc pl-6 mb-4 text-gray-800 leading-relaxed space-y-1">
        {relatedItems.map((item) => (
          <li key={item.href}>
            <Link href={item.href} className="text-blue-600 hover:underline">
              {item.label}
            </Link>
            {item.tail}
          </li>
        ))}
      </ul>
    </div>
  )
}
