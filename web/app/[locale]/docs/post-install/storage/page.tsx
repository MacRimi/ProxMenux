import type { Metadata } from "next"
import { getTranslations, getMessages, setRequestLocale } from "next-intl/server"
import { Link } from "@/i18n/navigation"
import { ExternalLink } from "lucide-react"
import { DocHeader } from "@/components/ui/doc-header"
import { Callout } from "@/components/ui/callout"
import CopyableCode from "@/components/CopyableCode"

export async function generateMetadata({
  params,
}: {
  params: Promise<{ locale: string }>
}): Promise<Metadata> {
  const { locale } = await params
  const t = await getTranslations({ locale, namespace: "docs.postInstall.storage.meta" })
  return { title: t("title"), description: t("description") }
}

type ArcRow = { ram: string; min: string; max: string }
type SnapRow = { label: string; runs: string; kept: string }
type RelatedItem = { label: string; href: string; tail: string }

export default async function PostInstallStoragePage({
  params,
}: {
  params: Promise<{ locale: string }>
}) {
  const { locale } = await params
  setRequestLocale(locale)
  const t = await getTranslations({ locale, namespace: "docs.postInstall.storage" })

  const messages = (await getMessages({ locale })) as unknown as {
    docs: { postInstall: { storage: {
      arc: { rows: ArcRow[] }
      autoSnap: { rows: SnapRow[] }
      autotrim: {
        practicalItems: string[]
        whenSkipItems: string[]
      }
      related: { items: RelatedItem[] }
    } } }
  }
  const arcRows = messages.docs.postInstall.storage.arc.rows
  const snapRows = messages.docs.postInstall.storage.autoSnap.rows
  const practicalItems = messages.docs.postInstall.storage.autotrim.practicalItems
  const whenSkipItems = messages.docs.postInstall.storage.autotrim.whenSkipItems
  const relatedItems = messages.docs.postInstall.storage.related.items

  const code = (chunks: React.ReactNode) => <code>{chunks}</code>
  const strong = (chunks: React.ReactNode) => <strong>{chunks}</strong>
  const em = (chunks: React.ReactNode) => <em>{chunks}</em>
  const zfsAutoAnchor = (chunks: React.ReactNode) => (
    <a href="https://github.com/zfsonlinux/zfs-auto-snapshot" target="_blank" rel="noopener noreferrer" className="text-blue-600 hover:underline inline-flex items-center gap-1">
      {chunks}
      <ExternalLink className="w-3 h-3" />
    </a>
  )

  return (
    <div>
      <DocHeader
        title={t("header.title")}
        section={t("header.section")}
      />

      <Callout variant="info" title={t("intro.title")}>
        {t.rich("intro.body", { strong })}
      </Callout>

      <Callout variant="warning" title={t("notTrackedTitle")}>
        {t.rich("notTrackedBody", { strong })}
      </Callout>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("arc.heading")}</h2>

      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("arc.intro", { strong })}
      </p>

      <h3 className="text-lg font-semibold mt-6 mb-2 text-gray-900">{t("arc.sizingTitle")}</h3>
      <div className="my-4 overflow-x-auto">
        <table className="min-w-full border border-gray-200 text-sm">
          <thead className="bg-gray-100">
            <tr>
              <th className="border border-gray-200 px-3 py-2 text-left text-gray-900">{t("arc.headerRam")}</th>
              <th className="border border-gray-200 px-3 py-2 text-left text-gray-900">{t("arc.headerMin")}</th>
              <th className="border border-gray-200 px-3 py-2 text-left text-gray-900">{t("arc.headerMax")}</th>
            </tr>
          </thead>
          <tbody className="text-gray-800">
            {arcRows.map((row) => (
              <tr key={row.ram}>
                <td className="border border-gray-200 px-3 py-2">{row.ram}</td>
                <td className="border border-gray-200 px-3 py-2">{row.min}</td>
                <td className="border border-gray-200 px-3 py-2">{row.max}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("arc.after", { code })}
      </p>

      <Callout variant="warning" title={t("arc.rebootTitle")}>
        {t.rich("arc.rebootBody", { code, strong })}
      </Callout>

      <Callout variant="tip" title={t("arc.safeTitle")}>
        {t.rich("arc.safeBody", { code })}
      </Callout>

      <h3 className="text-lg font-semibold mt-6 mb-2 text-gray-900">{t("arc.verifyTitle")}</h3>
      <CopyableCode
        code={`# Check the config file is in place
cat /etc/modprobe.d/99-zfsarc.conf

# After reboot, check actual ARC limits (in bytes)
cat /sys/module/zfs/parameters/zfs_arc_min
cat /sys/module/zfs/parameters/zfs_arc_max

# Manual rollback
rm /etc/modprobe.d/99-zfsarc.conf
update-initramfs -u -k all
# (reboot for ZFS to load with defaults again)`}
        className="my-4"
      />

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("autoSnap.heading")}</h2>

      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("autoSnap.intro", { a: zfsAutoAnchor })}
      </p>

      <h3 className="text-lg font-semibold mt-6 mb-2 text-gray-900">{t("autoSnap.cadenceTitle")}</h3>
      <div className="my-4 overflow-x-auto">
        <table className="min-w-full border border-gray-200 text-sm">
          <thead className="bg-gray-100">
            <tr>
              <th className="border border-gray-200 px-3 py-2 text-left text-gray-900">{t("autoSnap.headerLabel")}</th>
              <th className="border border-gray-200 px-3 py-2 text-left text-gray-900">{t("autoSnap.headerRuns")}</th>
              <th className="border border-gray-200 px-3 py-2 text-left text-gray-900">{t("autoSnap.headerKept")}</th>
            </tr>
          </thead>
          <tbody className="text-gray-800">
            {snapRows.map((row) => (
              <tr key={row.label}>
                <td className="border border-gray-200 px-3 py-2">{row.label}</td>
                <td className="border border-gray-200 px-3 py-2">{row.runs}</td>
                <td className="border border-gray-200 px-3 py-2">{row.kept}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <Callout variant="tip" title={t("autoSnap.conservativeTitle")}>
        {t.rich("autoSnap.conservativeBody", { code })}
      </Callout>

      <Callout variant="warning" title={t("autoSnap.onlyZfsTitle")}>
        {t("autoSnap.onlyZfsBody")}
      </Callout>

      <h3 className="text-lg font-semibold mt-6 mb-2 text-gray-900">{t("autoSnap.verifyTitle")}</h3>
      <CopyableCode
        code={`# List existing auto-snapshots across all ZFS datasets
zfs list -t snapshot | grep zfs-auto-snap

# Check the schedules
grep . /etc/cron.d/zfs-auto-snapshot /etc/cron.hourly/zfs-auto-snapshot \\
       /etc/cron.daily/zfs-auto-snapshot /etc/cron.weekly/zfs-auto-snapshot \\
       /etc/cron.monthly/zfs-auto-snapshot

# Manual rollback (removes the package + destroys no snapshots)
apt purge zfs-auto-snapshot
# Existing snapshots remain on your pools unless you destroy them explicitly`}
        className="my-4"
      />

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("autotrim.heading")}</h2>

      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("autotrim.intro", { code })}
      </p>

      <h3 className="text-lg font-semibold mt-6 mb-2 text-gray-900">{t("autotrim.trimTitle")}</h3>
      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("autotrim.trimBody1", { strong })}
      </p>
      <p className="mb-4 text-gray-800 leading-relaxed">
        {t("autotrim.trimBody2")}
      </p>
      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("autotrim.trimBody3", { code })}
      </p>

      <h3 className="text-lg font-semibold mt-6 mb-2 text-gray-900">{t("autotrim.practicalTitle")}</h3>
      <ul className="list-disc pl-6 mb-4 text-gray-800 leading-relaxed space-y-1">
        {practicalItems.map((_, idx) => (
          <li key={idx}>{t.rich(`autotrim.practicalItems.${idx}`, { strong, code })}</li>
        ))}
      </ul>

      <h3 className="text-lg font-semibold mt-6 mb-2 text-gray-900">{t("autotrim.whenTitle")}</h3>
      <ul className="list-disc pl-6 mb-4 text-gray-800 leading-relaxed space-y-1">
        <li>
          {t.rich("autotrim.whenIntro1", { strong })}
        </li>
        <li>
          {t.rich("autotrim.whenIntro2", { strong })}
          <ul className="list-disc pl-6 mt-1">
            {whenSkipItems.map((_, idx) => (
              <li key={idx}>{t.rich(`autotrim.whenSkipItems.${idx}`, { code })}</li>
            ))}
          </ul>
        </li>
        <li>
          {t.rich("autotrim.whenIntro3", { strong })}
        </li>
      </ul>

      <Callout variant="info" title={t("autotrim.recordedTitle")}>
        {t.rich("autotrim.recordedBody", { code })}
      </Callout>

      <h3 className="text-lg font-semibold mt-6 mb-2 text-gray-900">{t("autotrim.manualTitle")}</h3>
      <p className="mb-4 text-gray-800 leading-relaxed">{t("autotrim.manualIntro")}</p>
      <CopyableCode
        code={`# 1. List your ZFS pools
zpool list -H -o name

# 2. Check the current autotrim setting on a pool
zpool get autotrim <pool>

# 3. Verify the pool is backed by SSD/NVMe with TRIM support
#    For each vdev (use the device path you see in 'zpool status -P <pool>'):
DEV=sda      # replace with the actual short name (sda, nvme0n1, ...)
cat /sys/block/\${DEV}/queue/rotational           # must be 0 (SSD/NVMe, not HDD)
cat /sys/block/\${DEV}/queue/discard_granularity  # must be > 0 (TRIM supported)

# 4. Turn it on
zpool set autotrim=on <pool>

# 5. Confirm
zpool get autotrim <pool>`}
        className="my-4"
      />

      <h3 className="text-lg font-semibold mt-6 mb-2 text-gray-900">{t("autotrim.verifyTitle")}</h3>
      <CopyableCode
        code={`# Verify autotrim is active on every pool ProxMenux touched
cat /usr/local/share/proxmenux/zfs_autotrim_pools
while read -r p; do
  zpool get autotrim "$p"
done < /usr/local/share/proxmenux/zfs_autotrim_pools

# Manual rollback — disable autotrim on a specific pool
zpool set autotrim=off <pool>

# Or revert all pools ProxMenux changed (manual equivalent of the Uninstall option)
while read -r p; do
  zpool set autotrim=off "$p"
done < /usr/local/share/proxmenux/zfs_autotrim_pools`}
        className="my-4"
      />

      <Callout variant="tip" title={t("autotrim.oneShotTitle")}>
        {t.rich("autotrim.oneShotBody", { code })}
      </Callout>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("vzdump.heading")}</h2>

      <p className="mb-4 text-gray-800 leading-relaxed">{t("vzdump.intro")}</p>

      <h3 className="text-lg font-semibold mt-6 mb-2 text-gray-900">{t("vzdump.changedTitle")}</h3>
      <CopyableCode
        code={`bwlimit: 0      # No bandwidth limit (was capped by default)
ionice:  5      # Lower I/O priority (5 = best-effort class, lowest priority in that class)`}
        className="my-4"
      />

      <Callout variant="warning" title={t("vzdump.noBackupTitle")}>
        {t.rich("vzdump.noBackupBody", { strong, code, em })}
      </Callout>

      <Callout variant="tip" title={t("vzdump.skipTitle")}>
        {t.rich("vzdump.skipBody", { code })}
      </Callout>

      <h3 className="text-lg font-semibold mt-6 mb-2 text-gray-900">{t("vzdump.verifyTitle")}</h3>
      <CopyableCode
        code={`# Check current vzdump config
grep -E "^(bwlimit|ionice):" /etc/vzdump.conf

# Manual rollback (comment out the two lines — restores Proxmox defaults)
sed -i 's/^bwlimit: 0/#bwlimit: KBPS/' /etc/vzdump.conf
sed -i 's/^ionice: 5/#ionice: PRI/' /etc/vzdump.conf`}
        className="my-4"
      />

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
