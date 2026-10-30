import type { Metadata } from "next"
import { getTranslations, getMessages, setRequestLocale } from "next-intl/server"
import { Link } from "@/i18n/navigation"
import { DocHeader } from "@/components/ui/doc-header"
import { Callout } from "@/components/ui/callout"
import CopyableCode from "@/components/CopyableCode"

export async function generateMetadata({
  params,
}: {
  params: Promise<{ locale: string }>
}): Promise<Metadata> {
  const { locale } = await params
  const t = await getTranslations({ locale, namespace: "docs.diskManager.formatDisk.meta" })
  return {
    title: t("title"),
    description: t("description"),
    openGraph: {
      title: t("ogTitle"),
      description: t("ogDescription"),
      type: "article",
      url: "https://macrimi.github.io/ProxMenux/docs/disk-manager/format-disk",
    },
  }
}

type StringItem = string
type ModeRow = { mode: string; part: string; data: string; useCase: string }
type StepData = { title: string; body?: string; bodyRich?: string }
type RelatedItem = { href: string; label: string; tail?: string }

export default async function FormatDiskPage({
  params,
}: {
  params: Promise<{ locale: string }>
}) {
  const { locale } = await params
  setRequestLocale(locale)
  const t = await getTranslations({ locale, namespace: "docs.diskManager.formatDisk" })

  const messages = (await getMessages({ locale })) as unknown as {
    docs: { diskManager: { formatDisk: {
      visibility: { items: StringItem[]; safetyItems: StringItem[] }
      modes: { rows: ModeRow[]; fullFormatItems: StringItem[] }
      steps: { list: StepData[] }
      related: { items: RelatedItem[] }
    } } }
  }
  const visItems = messages.docs.diskManager.formatDisk.visibility.items
  const safetyItems = messages.docs.diskManager.formatDisk.visibility.safetyItems
  const modeRows = messages.docs.diskManager.formatDisk.modes.rows
  const fullFormatItems = messages.docs.diskManager.formatDisk.modes.fullFormatItems
  const stepList = messages.docs.diskManager.formatDisk.steps.list
  const relatedItems = messages.docs.diskManager.formatDisk.related.items

  const code = (chunks: React.ReactNode) => <code>{chunks}</code>
  const strong = (chunks: React.ReactNode) => <strong>{chunks}</strong>
  const em = (chunks: React.ReactNode) => <em>{chunks}</em>

  return (
    <div>
      <DocHeader
        title={t("header.title")}
        description={t("header.description")}
        section={t("header.section")}
        estimatedMinutes={5}
        scriptPath="storage/format-disk.sh"
      />

      <Callout variant="danger" title={t("danger.title")}>
        {t("danger.body")}
      </Callout>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("howRuns.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">{t("howRuns.body")}</p>

      <pre className="bg-gray-100 text-gray-800 p-4 rounded-md overflow-x-auto text-sm my-4 border border-gray-200 leading-snug">
{`┌─────────────────────────────────────────────┐
│  PHASE 1 — Filter, choose, confirm          │
│  (nothing touched yet)                      │
└──────────────────┬──────────────────────────┘
                   ▼
      Detect disks on host (lsblk)
                   │
                   ▼
      Visibility filter
      ├─ Hidden: system mount / swap / root pool
      ├─ Shown, blocked: used by a running VM/CT
      └─ Shown with warning: stopped guest ref,
         data mounts, ZFS / LVM / RAID members
                   │
                   ▼
      User picks a disk
                   │
                   ▼
      Operation mode
      ├─ 1. Wipe all         (partitions + sigs)
      ├─ 2. Remove FS labels (data preserved)
      ├─ 3. Zero all data    (partitions kept)
      └─ 4. Full format      (new GPT + mkfs)
                   │
                   ▼
      ╔════════════════════════════════════╗
      ║  Double confirmation gate           ║
      ║  (1) yes/no dialog with summary     ║
      ║  (2) type the full disk path exactly║
      ║      (e.g. /dev/sdc)                ║
      ║  Any mismatch → abort               ║
      ╚══════════════════╤═════════════════╝
                         │
  ┌──────── Cancel   OR   Confirm ────┐
  ▼                                   ▼
Exit, nothing             Mode = 4? → Filesystem:
was changed               ext4 / xfs / exfat / btrfs / zfs
                          (zfs → also asks the pool name)
                                      │
                     ┌────────────────┴──────────────────┐
                     │  PHASE 2 — Execute                 │
                     └─────────────────┬─────────────────┘
                                       ▼
                       Mode 4: install exfatprogs if
                       mkfs.exfat is missing; abort if
                       mkfs.btrfs is missing
                                       │
                                       ▼
                       Pre-execution re-validation
                       (state may have changed since
                        Phase 1 — user just confirmed)
                       ├─ Disk now hosts system mount?
                       │    → hard block, abort
                       ├─ Disk now in root ZFS pool?
                       │    → hard block, abort
                       ├─ Disk has active swap?
                       │    → hard block, abort
                       ├─ Data partitions still mounted?
                       │    → auto-unmount; abort if fails
                       ├─ Active ZFS pool on the disk?
                       │    → zpool export
                       └─ Used by a running VM/CT?
                            → hard block, abort
                                       │
                                       ▼
                       Run the selected mode:
                       ┌─────────────────────────────────┐
                       │ 1. Wipe all                     │
                       │    wipefs -af each partition    │
                       │    sgdisk --zap-all <disk>      │
                       │    blkdiscard (if supported)    │
                       │    zero first + last 16 MiB     │
                       ├─────────────────────────────────┤
                       │ 2. Remove FS labels             │
                       │    wipefs -af --types <fs/raid> │
                       │      <disk> + each partition    │
                       │    (partition table PRESERVED)  │
                       ├─────────────────────────────────┤
                       │ 3. Zero all data                │
                       │    For each partition:          │
                       │      dd if=/dev/zero of=<part>  │
                       │         bs=4M                   │
                       │    (partition table PRESERVED)  │
                       ├─────────────────────────────────┤
                       │ 4. Full format                  │
                       │    same wipe as mode 1          │
                       │    parted mklabel gpt           │
                       │    parted mkpart 1MiB 100%      │
                       │    mkfs.<fs> <disk>1            │
                       │    (zfs: zpool create <pool>)   │
                       └─────────────────────────────────┘`}
      </pre>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("visibility.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">{t("visibility.intro")}</p>
      <ul className="list-disc pl-6 mb-4 text-gray-800 leading-relaxed space-y-1">
        {visItems.map((_, idx) => (
          <li key={idx}>{t.rich(`visibility.items.${idx}`, { strong, em })}</li>
        ))}
      </ul>

      <Callout variant="warning" title={t("visibility.safetyTitle")}>
        <ul className="mt-2 list-disc list-inside space-y-1">
          {safetyItems.map((_, idx) => (
            <li key={idx}>{t.rich(`visibility.safetyItems.${idx}`, { strong, em })}</li>
          ))}
        </ul>
      </Callout>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("modes.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">{t("modes.intro")}</p>
      <div className="overflow-x-auto mb-4 rounded-md border border-gray-200">
        <table className="min-w-full text-sm">
          <thead className="bg-gray-50 text-left text-gray-700">
            <tr>
              <th className="px-4 py-2 font-semibold">{t("modes.headerMode")}</th>
              <th className="px-4 py-2 font-semibold">{t("modes.headerPart")}</th>
              <th className="px-4 py-2 font-semibold">{t("modes.headerData")}</th>
              <th className="px-4 py-2 font-semibold">{t("modes.headerUseCase")}</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-200 text-gray-800">
            {modeRows.map((row) => (
              <tr key={row.mode}>
                <td className="px-4 py-2 font-semibold">{row.mode}</td>
                <td className="px-4 py-2">{row.part}</td>
                <td className="px-4 py-2">{row.data}</td>
                <td className="px-4 py-2">{row.useCase}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <p className="mb-4 text-gray-800 leading-relaxed">{t.rich("modes.fullFormatOutro", { strong })}</p>
      <ul className="list-disc pl-6 mb-4 text-gray-800 leading-relaxed space-y-1">
        {fullFormatItems.map((_, idx) => (
          <li key={idx}>{t.rich(`modes.fullFormatItems.${idx}`, { strong, code })}</li>
        ))}
      </ul>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("steps.heading")}</h2>

      {stepList.map((step, idx) => (
        <section key={idx} className="mt-8 border-b border-gray-200 pb-8">
          <div className="flex items-center gap-3 mb-3">
            <span className="inline-flex items-center rounded-full border border-blue-200 bg-blue-50 px-2.5 py-0.5 text-xs font-semibold text-blue-800">
              {t("steps.stepLabel")} {idx + 1}
            </span>
            <h3 className="text-lg font-semibold text-gray-900 m-0">{step.title}</h3>
          </div>
          <div className="mb-4 text-gray-800 leading-relaxed">
            {step.bodyRich ? (
              <p>{t.rich(`steps.list.${idx}.bodyRich`, { strong, code })}</p>
            ) : step.body && <p>{step.body}</p>}
          </div>
        </section>
      ))}

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("manual.heading")}</h2>
      <p className="mb-3 text-gray-800 leading-relaxed">{t("manual.body")}</p>
      <CopyableCode code={`# --- mode 1: wipe all (partition table + signatures) ---
wipefs -af /dev/sdX
sgdisk --zap-all /dev/sdX

# --- mode 2: remove FS labels only (keep partitions + data) ---
# --types limits wipefs to filesystem/RAID signatures; without it,
# wipefs -af on the disk would also erase the partition table
types=$(blkid -k | paste -sd,)
wipefs -af --types "$types" /dev/sdX /dev/sdX?*

# --- mode 3: zero all data (keep partition table) ---
for p in /dev/sdX?*; do
  dd if=/dev/zero of="$p" bs=4M status=progress || true
done

# --- mode 4: full format (new GPT + filesystem) ---
wipefs -af /dev/sdX
sgdisk --zap-all /dev/sdX
parted -s /dev/sdX mklabel gpt mkpart primary 1MiB 100%   # one partition
mkfs.ext4 /dev/sdX1                        # pick the fs you want`} />

      <Callout variant="troubleshoot" title={t("troubleshoot.notListedTitle")}>
        {t.rich("troubleshoot.notListedBody", { code })}
      </Callout>
      <Callout variant="troubleshoot" title={t("troubleshoot.busyTitle")}>
        {t.rich("troubleshoot.busyBody", { code })}
      </Callout>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("related.heading")}</h2>
      <ul className="list-disc pl-6 text-gray-800 leading-relaxed space-y-1">
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
