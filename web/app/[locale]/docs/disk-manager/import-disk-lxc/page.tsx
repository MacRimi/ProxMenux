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
  const t = await getTranslations({ locale, namespace: "docs.diskManager.importDiskLxc.meta" })
  return {
    title: t("title"),
    description: t("description"),
    openGraph: {
      title: t("ogTitle"),
      description: t("ogDescription"),
      type: "article",
      url: "https://macrimi.github.io/ProxMenux/docs/disk-manager/import-disk-lxc",
    },
  }
}

type StepData = {
  title: string
  body?: string
  bodyRich?: string
  intro?: string
  items?: string[]
  img?: string
  caption?: string
  extraImg?: string
  extraAlt?: string
  extraCaption?: string
}
type StringItem = string
type RelatedItem = { href: string; label: string; tail?: string }

export default async function ImportDiskLXCPage({
  params,
}: {
  params: Promise<{ locale: string }>
}) {
  const { locale } = await params
  setRequestLocale(locale)
  const t = await getTranslations({ locale, namespace: "docs.diskManager.importDiskLxc" })

  const messages = (await getMessages({ locale })) as unknown as {
    docs: { diskManager: { importDiskLxc: {
      prereqs: { items: StringItem[] }
      steps: { list: StepData[] }
      important: { items: StringItem[] }
      related: { items: RelatedItem[] }
    } } }
  }
  const prereqItems = messages.docs.diskManager.importDiskLxc.prereqs.items
  const stepList = messages.docs.diskManager.importDiskLxc.steps.list
  const importantItems = messages.docs.diskManager.importDiskLxc.important.items
  const relatedItems = messages.docs.diskManager.importDiskLxc.related.items

  const code = (chunks: React.ReactNode) => <code>{chunks}</code>
  const strong = (chunks: React.ReactNode) => <strong>{chunks}</strong>
  const em = (chunks: React.ReactNode) => <em>{chunks}</em>
  const wipeLink = (chunks: React.ReactNode) => (
    <a href="/docs/disk-manager/format-disk" className="text-blue-600 hover:underline">{chunks}</a>
  )

  return (
    <div>
      <DocHeader
        title={t("header.title")}
        description={t("header.description")}
        section={t("header.section")}
        estimatedMinutes={8}
        scriptPath="storage/disk-passthrough_ct.sh"
      />

      <Callout variant="info" title={t("intro.title")}>
        {t.rich("intro.body", { strong, em })}
      </Callout>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("howRuns.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">{t("howRuns.body")}</p>

      <pre className="bg-gray-100 text-gray-800 p-4 rounded-md overflow-x-auto text-sm my-4 border border-gray-200 leading-snug">
{`┌─────────────────────────────────────────────┐
│  PHASE 1 — Pick CT, detect disk, plan       │
│  (nothing touched yet)                      │
└──────────────────┬──────────────────────────┘
                   ▼
      pct list — user picks target CT
                   │
                   ▼
      Privileged check
      ├─ unprivileged: 1 in config
      │    → offer to convert now
      │      (edits /etc/pve/lxc/<CTID>.conf,
      │       writes unprivileged: 0)
      │      ├─ accept   → continue
      │      └─ cancel   → abort
      └─ privileged → continue
                   │
                   ▼
      Detect disks on host (lsblk)
                   │
                   ▼
      Visibility filter
      ├─ Hidden: root / swap / system-mounted
      ├─ Hidden: active ZFS / LVM / RAID members
      ├─ Hidden: already in any VM/CT config
      ├─ Shown: free disks
      └─ Shown with ⚠ label: stale metadata
                   │
                   ▼
      User selects ONE disk
      (only a single disk per run)
                   │
                   ▼
      Filesystem probe on the first partition
      ├─ ext4 / xfs / btrfs  → reuse as-is
      │                        (data is preserved)
      └─ empty / unsupported → offer to format
                               ├─ pick fs: ext4 / xfs / btrfs
                               └─ mkfs.<fs> will run in Phase 2
                   │
                   ▼
      User types mount point path
      (e.g. /mnt/data  /mnt/disk_passthrough)
                   │
                   ▼
      Summary: disk → mount point
                   │
   ┌──────── Cancel   OR   Confirm ────┐
   ▼                                   ▼
Exit, nothing        ┌─────────────────┴─────────────────┐
was changed          │  PHASE 2 — Apply                   │
                     └─────────────────┬─────────────────┘
                                       ▼
                       If conversion was accepted:
                       └─ rewrite CT config line:
                          unprivileged: 1  →  0
                                       │
                                       ▼
                       If formatting was chosen:
                       └─ mkfs.<fs> /dev/disk/by-id/…-part1
                                       │
                                       ▼
                       Resolve best persistent partition
                       path (/dev/disk/by-id/...-partN)
                                       │
                                       ▼
                       Find next free mpN index
                       (scans pct config output)
                                       │
                                       ▼
                       pct set <CTID> -mpN \\
                          <persistent-part-path>, \\
                          mp=<mount-point>, \\
                          backup=0,ro=0[,acl=1]
                                       │
                                       ▼
                       Verify: pct config <CTID> shows
                       the new mpN entry
                                       │
                                       ▼
                       Container sees the directory at
                       the chosen mount point path`}
      </pre>
      <p className="mb-4 text-gray-800 leading-relaxed">{t("howRuns.summary")}</p>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("prereqs.heading")}</h2>
      <ul className="list-disc pl-6 mb-4 text-gray-800 leading-relaxed space-y-1">
        {prereqItems.map((_, idx) => (
          <li key={idx}>{t.rich(`prereqs.items.${idx}`, { strong })}</li>
        ))}
      </ul>

      <Callout variant="warning" title={t("prereqs.warnTitle")}>
        {t.rich("prereqs.warnBody", { strong, code })}
      </Callout>

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
              <p>{t.rich(`steps.list.${idx}.bodyRich`, { code, strong, em })}</p>
            ) : step.intro ? (
              <>
                <p>{step.intro}</p>
                {step.items && (
                  <ul className="list-disc pl-6 mt-2 space-y-1">
                    {step.items.map((_, i) => (
                      <li key={i}>{t(`steps.list.${idx}.items.${i}`)}</li>
                    ))}
                  </ul>
                )}
              </>
            ) : (
              step.body && <p>{step.body}</p>
            )}
          </div>
          {step.img && (
            <div className="flex flex-col items-center">
              <div className="w-full max-w-[768px] overflow-hidden rounded-md border border-gray-200">
                <Image src={step.img} alt={step.caption || step.title} width={768} height={0} style={{ height: "auto" }} className="w-full object-contain" sizes="(max-width: 768px) 100vw, 768px" />
              </div>
              {step.caption && <span className="mt-2 text-sm text-gray-600">{step.caption}</span>}
            </div>
          )}
          {step.extraImg && (
            <div className="mt-4 flex flex-col items-center">
              <div className="w-full max-w-[768px] overflow-hidden rounded-md border border-gray-200">
                <Image src={step.extraImg} alt={step.extraAlt || step.title} width={768} height={0} style={{ height: "auto" }} className="w-full object-contain" sizes="(max-width: 768px) 100vw, 768px" />
              </div>
              {step.extraCaption && <span className="mt-2 text-sm text-gray-600">{step.extraCaption}</span>}
            </div>
          )}
        </section>
      ))}

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("manual.heading")}</h2>
      <p className="mb-3 text-gray-800 leading-relaxed">{t.rich("manual.body", { code })}</p>
      <CopyableCode code={`# find the partition's persistent path
ls -l /dev/disk/by-id | grep part1 | grep sdb

# format (only if the disk is new or unreadable)
mkfs.ext4 /dev/disk/by-id/ata-WDC_WD40EFAX-68JH4N0_WD-WX11D1234567-part1

# attach to CT 101 as mp0 at /mnt/data
pct set 101 -mp0 /dev/disk/by-id/ata-WDC_WD40EFAX-68JH4N0_WD-WX11D1234567-part1,mp=/mnt/data,backup=0,ro=0

# verify
pct config 101 | grep -E '^mp[0-9]+:'`} />

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("important.heading")}</h2>
      <ul className="list-disc pl-6 mb-4 text-gray-800 leading-relaxed space-y-1">
        {importantItems.map((_, idx) => (
          <li key={idx}>{t.rich(`important.items.${idx}`, { strong, code, wipeLink })}</li>
        ))}
      </ul>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("troubleshoot.heading")}</h2>
      <Callout variant="troubleshoot" title={t("troubleshoot.unprivTitle")}>
        {t.rich("troubleshoot.unprivBody", { code })}
      </Callout>
      <Callout variant="troubleshoot" title={t("troubleshoot.permsTitle")}>
        {t.rich("troubleshoot.permsBody", { code })}
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
