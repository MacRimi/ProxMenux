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
  const t = await getTranslations({ locale, namespace: "docs.diskManager.smartDiskTest.meta" })
  return {
    title: t("title"),
    description: t("description"),
    openGraph: {
      title: t("ogTitle"),
      description: t("ogDescription"),
      type: "article",
      url: "https://macrimi.github.io/ProxMenux/docs/disk-manager/smart-disk-test",
    },
  }
}

type ActionRow = { action: string; what?: string; whatRich?: string; dur: string }
type StepData = { title: string; body?: string; bodyRich?: string; img?: string; alt?: string; caption?: string }
type RelatedItem = { href: string; label: string; tail?: string }

export default async function SmartDiskTestPage({
  params,
}: {
  params: Promise<{ locale: string }>
}) {
  const { locale } = await params
  setRequestLocale(locale)
  const t = await getTranslations({ locale, namespace: "docs.diskManager.smartDiskTest" })

  const messages = (await getMessages({ locale })) as unknown as {
    docs: { diskManager: { smartDiskTest: {
      actions: { rows: ActionRow[] }
      steps: { list: StepData[] }
      related: { items: RelatedItem[] }
    } } }
  }
  const actionRows = messages.docs.diskManager.smartDiskTest.actions.rows
  const stepList = messages.docs.diskManager.smartDiskTest.steps.list
  const relatedItems = messages.docs.diskManager.smartDiskTest.related.items

  const code = (chunks: React.ReactNode) => <code>{chunks}</code>
  const strong = (chunks: React.ReactNode) => <strong>{chunks}</strong>
  const em = (chunks: React.ReactNode) => <em>{chunks}</em>
  const br = () => <br />

  return (
    <div>
      <DocHeader
        title={t("header.title")}
        description={t("header.description")}
        section={t("header.section")}
        estimatedMinutes={10}
        scriptPath="storage/smart-disk-test.sh"
      />

      <Callout variant="info" title={t("intro.title")}>
        {t.rich("intro.body", { code })}
      </Callout>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("howRuns.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">{t("howRuns.body")}</p>

      <pre className="bg-gray-100 text-gray-800 p-4 rounded-md overflow-x-auto text-sm my-4 border border-gray-200 leading-snug">
{`        Detect dependencies (first run)
        ├─ smartctl  present? (smartmontools)
        └─ nvme      present? (nvme-cli)
        Any missing → apt-get install silently
                           │
                           ▼
        Enumerate disks on host (lsblk)
        (no safety filter — read-only tool,
         root / system disks are shown too)
                           │
                           ▼
        User picks a disk
                           │
                           ▼
        Detect disk class from path / TRAN
        ├─ /dev/nvme*      → NVMe
        └─ anything else   → SATA / SAS / SCSI
                           │
                           ▼
        Action menu (loop — stays open after
        each action so you can chain queries)
                           │
  ┌────────────────┬────────────────┬────────────────┬───────────────┐
  ▼                ▼                ▼                ▼               ▼
 Quick         Full             Short            Long             Check
 status        report           test             test             progress
 (instant)     (instant)        (~2 min)         (hours)          (instant)
  │             │                │                │                │
  │             │                │                │                │
  │             │                │ Long test only:                  │
  │             │                │ confirm "runs in background,     │
  │             │                │ result saved to JSON"            │
  │             │                │                │                │
  │             │                └───────┬────────┘                │
  │             │                        │                         │
  │             │               Queued on drive firmware:           │
  │             │               ├─ SATA/SAS: smartctl -t short|long │
  │             │               └─ NVMe:     nvme device-self-test  │
  │             │               Returns to menu while running       │
  │             │                                                  │
  ▼             ▼                                                  ▼
 Read:         Read:                                         Read status:
 SATA/SAS →    SATA/SAS →                                   SATA/SAS →
  smartctl -H   smartctl -x                                  smartctl -c
  smartctl -A                                                NVMe →
                                                             nvme self-test-log
 NVMe →        NVMe →
  nvme smart-   nvme smart-log
  log           + nvme id-ctrl
  │             │                                                  │
  └──────┬──────┴──────────────────────────────────────────────────┘
         │
         ▼
   Output to terminal (color-coded when applicable)
         +
   JSON export to:
   /usr/local/share/proxmenux/smart/<disk>/
       <YYYY-MM-DD_HHMMSS>_<action>.json
         │
         ▼
   Retention policy: oldest beyond the limit
   are trimmed automatically
         │
         ▼
   ProxMenux Monitor reads these files to
   render health trends per disk over time`}
      </pre>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("deps.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("deps.body", { code })}
      </p>
      <CopyableCode code={`apt-get install smartmontools nvme-cli`} />

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("actions.heading")}</h2>
      <div className="overflow-x-auto mb-4 rounded-md border border-gray-200">
        <table className="min-w-full text-sm">
          <thead className="bg-gray-50 text-left text-gray-700">
            <tr>
              <th className="px-4 py-2 font-semibold">{t("actions.headerAction")}</th>
              <th className="px-4 py-2 font-semibold">{t("actions.headerWhat")}</th>
              <th className="px-4 py-2 font-semibold">{t("actions.headerDur")}</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-200 text-gray-800">
            {actionRows.map((row, idx) => (
              <tr key={row.action}>
                <td className="px-4 py-2 font-semibold">{row.action}</td>
                <td className="px-4 py-2">
                  {row.whatRich ? t.rich(`actions.rows.${idx}.whatRich`, { code, br }) : row.what}
                </td>
                <td className="px-4 py-2">{row.dur}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <Callout variant="tip" title={t("actions.tipTitle")}>
        {t.rich("actions.tipBody", { em, strong })}
      </Callout>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("json.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("json.intro", { code })}
      </p>
      <pre className="bg-gray-100 p-3 rounded-md overflow-x-auto text-sm font-mono mb-4">
        <code>{`/usr/local/share/proxmenux/smart/
├── sda/
│   ├── 2026-04-23_145312_status.json
│   ├── 2026-04-23_180041_short.json
│   └── 2026-04-24_020015_long.json
└── nvme0n1/
    ├── 2026-04-23_145318_status.json
    └── 2026-04-24_021407_long.json`}</code>
      </pre>
      <p className="mb-4 text-gray-800 leading-relaxed">{t("json.outro")}</p>

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
              <p className="mb-4">{t.rich(`steps.list.${idx}.bodyRich`, { strong })}</p>
            ) : step.body && <p className="mb-4">{step.body}</p>}
          </div>
          {step.img && (
            <div className="flex flex-col items-center w-full max-w-[768px] mx-auto my-4">
              <div className="w-full overflow-hidden rounded-md border border-gray-200">
                <Image src={step.img} alt={step.alt || step.title} width={768} height={0} style={{ height: "auto" }} className="w-full object-contain" sizes="(max-width: 768px) 100vw, 768px" />
              </div>
              {step.caption && <span className="mt-2 text-sm text-gray-600">{step.caption}</span>}
            </div>
          )}
        </section>
      ))}

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("manual.heading")}</h2>
      <CopyableCode code={`# --- SATA / SAS drives (smartmontools) ---
# quick health
smartctl -H /dev/sdX
smartctl -A /dev/sdX           # attribute table

# full report
smartctl -x /dev/sdX

# self-tests
smartctl -t short    /dev/sdX
smartctl -t long     /dev/sdX
smartctl -c /dev/sdX | head    # current test progress

# --- NVMe drives (nvme-cli) ---
nvme smart-log   /dev/nvme0n1
nvme id-ctrl     /dev/nvme0n1
nvme self-test-log /dev/nvme0n1`} />

      <Callout variant="warning" title={t("manual.nvmeWarnTitle")}>
        {t.rich("manual.nvmeWarnBody", { code })}
      </Callout>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("troubleshoot.heading")}</h2>
      <Callout variant="troubleshoot" title={t("troubleshoot.noSmartTitle")}>
        {t.rich("troubleshoot.noSmartBody", { code })}
      </Callout>
      <Callout variant="troubleshoot" title={t("troubleshoot.longTitle")}>
        {t.rich("troubleshoot.longBody", { code })}
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
