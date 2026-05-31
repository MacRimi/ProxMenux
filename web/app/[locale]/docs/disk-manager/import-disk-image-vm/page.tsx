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
  const t = await getTranslations({ locale, namespace: "docs.diskManager.importDiskImageVm.meta" })
  return {
    title: t("title"),
    description: t("description"),
    openGraph: {
      title: t("ogTitle"),
      description: t("ogDescription"),
      type: "article",
      url: "https://macrimi.github.io/ProxMenux/docs/disk-manager/import-disk-image-vm",
    },
  }
}

type StepData = { title: string; body?: string; bodyRich?: string; intro?: string; items?: string[] }
type StringItem = string
type RelatedItem = { href: string; label: string; tail?: string }

export default async function ImportDiskImageVMPage({
  params,
}: {
  params: Promise<{ locale: string }>
}) {
  const { locale } = await params
  setRequestLocale(locale)
  const t = await getTranslations({ locale, namespace: "docs.diskManager.importDiskImageVm" })

  const messages = (await getMessages({ locale })) as unknown as {
    docs: { diskManager: { importDiskImageVm: {
      prereqs: { items: StringItem[] }
      steps: { list: StepData[] }
      related: { items: RelatedItem[] }
    } } }
  }
  const prereqItems = messages.docs.diskManager.importDiskImageVm.prereqs.items
  const stepList = messages.docs.diskManager.importDiskImageVm.steps.list
  const relatedItems = messages.docs.diskManager.importDiskImageVm.related.items

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
        scriptPath="storage/import-disk-image.sh"
      />

      <Callout variant="info" title={t("intro.title")}>
        {t.rich("intro.body", { em, strong })}
      </Callout>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("howRuns.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("howRuns.body", { code })}
      </p>

      <pre className="bg-gray-100 text-gray-800 p-4 rounded-md overflow-x-auto text-sm my-4 border border-gray-200 leading-snug">
{`┌─────────────────────────────────────────────┐
│  PHASE 1 — Collect every decision           │
│  (nothing touched yet)                      │
└──────────────────┬──────────────────────────┘
                   ▼
      qm list — user picks target VM
      (target VM should be powered off)
                   │
                   ▼
      pvesm status -content images
      ├─ 0 candidates → abort
      │   "no storage for disk images"
      ├─ 1 candidate  → auto-select, skip dialog
      └─ 2+           → user picks
                   │
                   ▼
      Source directory
      ├─ default: /var/lib/vz/template/iso
      └─ custom:  user types absolute path
          └─ not a directory → abort
                   │
                   ▼
      Scan the directory (maxdepth 1)
      for *.img *.qcow2 *.vmdk *.raw
      ├─ 0 results → abort
      │   "no compatible disk images found"
      └─ N results → continue
                   │
                   ▼
      User selects one or several images
      (checklist — multiple allowed)
                   │
                   ▼
      For each image, user picks:
      ├─ Bus:   scsi (default) / virtio / sata / ide
      ├─ SSD emulation (ssd=1)
      │   └─ offered only when bus ≠ virtio
      └─ Bootable? (adds to boot order in Phase 2)
                   │
                   ▼
      Summary of everything Phase 2 will do
                   │
   ┌──────── Cancel   OR   Confirm ────┐
   ▼                                   ▼
Exit, nothing        ┌─────────────────┴─────────────────┐
was changed          │  PHASE 2 — Import and attach       │
                     └─────────────────┬─────────────────┘
                                       ▼
                       For each selected image:
                       ├─ qm importdisk <VMID> \\
                       │      <source-file> \\
                       │      <target-storage>
                       │    (format conversion is transparent:
                       │     qcow2/vmdk/img → raw when the
                       │     target cannot hold the source
                       │     format natively — LVM, ZFS, …)
                       │
                       ├─ Find next free {bus}N slot
                       │   (scans qm config)
                       │
                       └─ qm set <VMID> -{bus}N \\
                             <storage>:vm-<VMID>-disk-N[,ssd=1]
                                       │
                                       ▼
                       If any image was marked bootable:
                       └─ qm set <VMID> --boot order={bus}N
                          (first bootable wins; others can be
                           reordered later in the Proxmox UI)
                                       │
                                       ▼
                       Verify: qm config <VMID> shows the
                       new slot(s) and, if applicable, the
                       new boot order
                                       │
                                       ▼
                       Source image file on the host is
                       kept unchanged (copied, not moved)`}
      </pre>

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
            ) : step.intro ? (
              <>
                <p>{step.intro}</p>
                {step.items && (
                  <ul className="list-disc pl-6 mt-2 space-y-2">
                    {step.items.map((_, i) => (
                      <li key={i}>{t.rich(`steps.list.${idx}.items.${i}`, { strong, code })}</li>
                    ))}
                  </ul>
                )}
              </>
            ) : (
              step.body && <p>{step.body}</p>
            )}
          </div>
        </section>
      ))}

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("manual.heading")}</h2>
      <p className="mb-3 text-gray-800 leading-relaxed">
        {t.rich("manual.body", { code })}
      </p>
      <CopyableCode code={`# 1. import the image file into the target storage (here: local-lvm)
qm importdisk 101 /var/lib/vz/template/iso/server.qcow2 local-lvm

# 2. attach the imported disk as scsi1 with SSD emulation
qm set 101 -scsi1 local-lvm:vm-101-disk-1,ssd=1

# 3. (optional) make it the primary boot device
qm set 101 --boot order=scsi1`} />

      <Callout variant="warning" title={t("manual.warnTitle")}>
        {t.rich("manual.warnBody", { code })}
      </Callout>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("troubleshoot.heading")}</h2>
      <Callout variant="troubleshoot" title={t("troubleshoot.noImagesTitle")}>
        {t.rich("troubleshoot.noImagesBody", { code })}
      </Callout>
      <Callout variant="troubleshoot" title={t("troubleshoot.slowTitle")}>
        {t("troubleshoot.slowBody")}
      </Callout>
      <Callout variant="troubleshoot" title={t("troubleshoot.uefiTitle")}>
        {t("troubleshoot.uefiBody")}
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
