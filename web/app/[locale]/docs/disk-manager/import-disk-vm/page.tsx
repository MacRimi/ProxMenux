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
  const t = await getTranslations({ locale, namespace: "docs.diskManager.importDiskVm.meta" })
  return {
    title: t("title"),
    description: t("description"),
    openGraph: {
      title: t("ogTitle"),
      description: t("ogDescription"),
      type: "article",
      url: "https://macrimi.github.io/ProxMenux/docs/disk-manager/import-disk-vm",
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
}
type StringItem = string
type RelatedItem = { href: string; label: string; tail?: string }

export default async function ImportDiskVMPage({
  params,
}: {
  params: Promise<{ locale: string }>
}) {
  const { locale } = await params
  setRequestLocale(locale)
  const t = await getTranslations({ locale, namespace: "docs.diskManager.importDiskVm" })

  const messages = (await getMessages({ locale })) as unknown as {
    docs: { diskManager: { importDiskVm: {
      prereqs: { items: StringItem[] }
      steps: { list: StepData[] }
      troubleshoot: { noDisksItems: StringItem[] }
      related: { items: RelatedItem[] }
    } } }
  }
  const prereqItems = messages.docs.diskManager.importDiskVm.prereqs.items
  const stepList = messages.docs.diskManager.importDiskVm.steps.list
  const noDisksItems = messages.docs.diskManager.importDiskVm.troubleshoot.noDisksItems
  const relatedItems = messages.docs.diskManager.importDiskVm.related.items

  const code = (chunks: React.ReactNode) => <code>{chunks}</code>
  const strong = (chunks: React.ReactNode) => <strong>{chunks}</strong>
  const em = (chunks: React.ReactNode) => <em>{chunks}</em>
  const winLink = (chunks: React.ReactNode) => (
    <a href="/docs/create-vm/system-windows" className="text-blue-600 hover:underline">{chunks}</a>
  )

  return (
    <div>
      <DocHeader
        title={t("header.title")}
        description={t("header.description")}
        section={t("header.section")}
        estimatedMinutes={5}
        scriptPath="storage/disk-passthrough.sh"
      />

      <Callout variant="info" title={t("intro.title")}>
        {t.rich("intro.body", { code })}
      </Callout>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("howRuns.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">{t("howRuns.body")}</p>

      <pre className="bg-gray-100 text-gray-800 p-4 rounded-md overflow-x-auto text-sm my-4 border border-gray-200 leading-snug">
{`┌─────────────────────────────────────────────┐
│  PHASE 1 — Pick VM, detect disks, select    │
│  (nothing touched yet)                      │
└──────────────────┬──────────────────────────┘
                   ▼
      qm list — user picks target VM
                   │
                   ▼
      VM status check
      ├─ running → abort (power off first)
      └─ stopped → continue
                   │
                   ▼
      Detect disks on host (lsblk)
                   │
                   ▼
      Visibility filter
      ├─ Hidden: root / swap / system-mounted
      ├─ Hidden: active ZFS / LVM / RAID members
      ├─ Hidden: already in this VM's config
      ├─ Shown: free disks
      └─ Shown with ⚠ label: stale ZFS/LVM/RAID
                             signatures (not active)
                   │
                   ▼
      User selects disk(s) via checklist
      + picks bus interface:
      SATA  /  SCSI  /  VirtIO  /  IDE
                   │
                   ▼
      Per-disk cross-check
      ├─ Assigned to a RUNNING VM/CT? → skip disk
      ├─ Assigned to stopped VM/CT?   → ask
      │   "continue anyway?" yes/no
      └─ NVMe detected?                → suggest
          using "Add Controller / NVMe"
          (user can still add as disk)
                   │
                   ▼
      Summary of disks to process
                   │
   ┌──────── Cancel   OR   Confirm ────┐
   ▼                                   ▼
Exit, nothing        ┌─────────────────┴─────────────────┐
was changed          │  PHASE 2 — Attach                  │
                     └─────────────────┬─────────────────┘
                                       ▼
                       For each selected disk:
                       ├─ Resolve best persistent path
                       │   preferred order:
                       │   1. /dev/disk/by-id/ata-*
                       │   2. /dev/disk/by-id/nvme-*
                       │   3. /dev/disk/by-id/scsi-*
                       │   4. /dev/disk/by-id/wwn-*
                       │   fallback: raw /dev/sdX
                       ├─ Find next free {bus}N slot
                       │   (scans qm config output)
                       └─ qm set <VMID> -{bus}N <path>
                                       │
                                       ▼
                       Verify: qm config <VMID> shows
                       the new slot(s)
                                       │
                                       ▼
                       Guest sees each disk as a native
                       block device under its bus
                       (e.g. /dev/sda, /dev/nvme0n1)`}
      </pre>
      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("howRuns.summary", { em })}
      </p>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("prereqs.heading")}</h2>
      <ul className="list-disc pl-6 mb-4 text-gray-800 leading-relaxed space-y-1">
        {prereqItems.map((_, idx) => (
          <li key={idx}>{t.rich(`prereqs.items.${idx}`, { code, strong })}</li>
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
              <p>{t.rich(`steps.list.${idx}.bodyRich`, { code, strong })}</p>
            ) : (
              <>
                {step.body && <p>{step.body}</p>}
                {step.intro && (
                  <>
                    <p>{step.intro}</p>
                    {step.items && (
                      <ul className="list-disc pl-6 mt-2 space-y-1">
                        {step.items.map((_, i) => (
                          <li key={i}>{t.rich(`steps.list.${idx}.items.${i}`, { strong })}</li>
                        ))}
                      </ul>
                    )}
                  </>
                )}
              </>
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
        </section>
      ))}

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("manual.heading")}</h2>
      <p className="mb-3 text-gray-800 leading-relaxed">
        {t.rich("manual.body", { code })}
      </p>
      <CopyableCode code={`# find the persistent path
ls -l /dev/disk/by-id | grep -v part | grep sdb

# attach to VM 101 as scsi1
qm set 101 -scsi1 /dev/disk/by-id/ata-WDC_WD40EFAX-68JH4N0_WD-WX11D1234567

# verify
qm config 101 | grep -E '^scsi[0-9]+:'`} />

      <Callout variant="warning" title={t("manual.migrationTitle")}>
        {t.rich("manual.migrationBody", { strong, code })}
      </Callout>

      <Callout variant="warning" title={t("manual.shareTitle")}>
        {t.rich("manual.shareBody", { code })}
      </Callout>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("troubleshoot.heading")}</h2>
      <Callout variant="troubleshoot" title={t("troubleshoot.noDisksTitle")}>
        {t("troubleshoot.noDisksIntro")}
        <ul className="mt-2 list-disc list-inside space-y-1">
          {noDisksItems.map((_, idx) => (
            <li key={idx}>{t(`troubleshoot.noDisksItems.${idx}`)}</li>
          ))}
        </ul>
        {t.rich("troubleshoot.noDisksOutro", { code })}
      </Callout>
      <Callout variant="troubleshoot" title={t("troubleshoot.noVisibleTitle")}>
        {t.rich("troubleshoot.noVisibleBody", { strong, winLink })}
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
