import type { Metadata } from "next"
import { getTranslations, getMessages, setRequestLocale } from "next-intl/server"
import { Link } from "@/i18n/navigation"
import { DocHeader } from "@/components/ui/doc-header"
import { Callout } from "@/components/ui/callout"

export async function generateMetadata({
  params,
}: {
  params: Promise<{ locale: string }>
}): Promise<Metadata> {
  const { locale } = await params
  const t = await getTranslations({ locale, namespace: "docs.network.backupRestore.meta" })
  return {
    title: t("title"),
    description: t("description"),
    openGraph: {
      title: t("ogTitle"),
      description: t("ogDescription"),
      type: "article",
      url: "https://macrimi.github.io/ProxMenux/docs/network/backup-restore",
    },
  }
}

type Step = { title: string; body: string; tone: "blue" | "amber" | "emerald" }
type RelatedItem = { label: string; href: string; tail?: string; tailRich?: string }

const TONE_CLASSES: Record<string, string> = {
  blue: "border-blue-400 bg-blue-50",
  amber: "border-amber-400 bg-amber-50",
  emerald: "border-emerald-400 bg-emerald-50",
}

export default async function BackupRestorePage({
  params,
}: {
  params: Promise<{ locale: string }>
}) {
  const { locale } = await params
  setRequestLocale(locale)
  const t = await getTranslations({ locale, namespace: "docs.network.backupRestore" })

  const messages = (await getMessages({ locale })) as unknown as {
    docs: { network: { backupRestore: {
      restore: { steps: Step[] }
      restart: { warnItems: string[] }
      related: { items: RelatedItem[] }
    } } }
  }
  const restoreSteps = messages.docs.network.backupRestore.restore.steps
  const warnItems = messages.docs.network.backupRestore.restart.warnItems
  const relatedItems = messages.docs.network.backupRestore.related.items

  const code = (chunks: React.ReactNode) => <code>{chunks}</code>
  const strong = (chunks: React.ReactNode) => <strong>{chunks}</strong>
  const em = (chunks: React.ReactNode) => <em>{chunks}</em>
  const bridgeLink = (chunks: React.ReactNode) => (
    <Link href="/docs/network/bridge-analysis" className="text-blue-600 hover:underline">{chunks}</Link>
  )
  const configLink = (chunks: React.ReactNode) => (
    <Link href="/docs/network/config-analysis" className="text-blue-600 hover:underline">{chunks}</Link>
  )

  return (
    <div>
      <DocHeader
        title={t("header.title")}
        description={t("header.description")}
        section={t("header.section")}
        estimatedMinutes={4}
        scriptPath="menus/network_menu.sh"
      />

      <Callout variant="info" title={t("intro.title")}>
        {t.rich("intro.body", { code })}
      </Callout>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("shared.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">{t("shared.intro")}</p>
      <pre className="rounded-md bg-gray-100 p-4 overflow-x-auto text-xs font-mono text-gray-800 leading-relaxed border border-gray-200">{`/var/backups/proxmenux/
├── interfaces_backup_2026-04-26_14-30-12   ← from a guided repair
├── interfaces_backup_2026-04-26_15-08-44   ← from "Create Network Backup" (this page)
├── interfaces_backup_2026-04-26_18-22-09   ← auto-taken before a restore
└── …`}</pre>
      <p className="mt-4 mb-6 text-gray-800 leading-relaxed">{t("shared.outro")}</p>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("show.heading")}</h2>
      <p className="mb-6 text-gray-800 leading-relaxed">
        {t.rich("show.body", { code })}
      </p>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("create.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("create.body", { code })}
      </p>
      <Callout variant="tip" title={t("create.whenTitle")}>
        {t.rich("create.whenBody", { code, em })}
      </Callout>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("restore.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("restore.intro", { code })}
      </p>
      <div className="space-y-4 mb-6">
        {restoreSteps.map((step, idx) => (
          <div key={idx} className={`border-l-4 ${TONE_CLASSES[step.tone]} p-4 rounded-r-md`}>
            <div className="font-semibold text-gray-900 mb-1">{step.title}</div>
            <p className="text-sm text-gray-800 m-0">{t.rich(`restore.steps.${idx}.body`, { code, strong })}</p>
          </div>
        ))}
      </div>

      <Callout variant="warning" title={t("restore.autoBackupTitle")}>
        {t.rich("restore.autoBackupBody", { em, code })}
      </Callout>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("restart.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("restart.body", { code })}
      </p>
      <Callout variant="danger" title={t("restart.warnTitle")}>
        {t.rich("restart.warnBody", { code })}
        <ul className="list-disc pl-6 mt-2 mb-0 space-y-1">
          {warnItems.map((_, idx) => (
            <li key={idx}>{t.rich(`restart.warnItems.${idx}`, { em })}</li>
          ))}
        </ul>
      </Callout>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("manualRollback.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">{t("manualRollback.intro")}</p>
      <pre className="rounded-md bg-gray-100 p-4 overflow-x-auto text-xs font-mono text-gray-800 leading-relaxed border border-gray-200">{`ls -lt /var/backups/proxmenux/interfaces_backup_*  # newest first
cp /var/backups/proxmenux/interfaces_backup_<TIMESTAMP> /etc/network/interfaces
systemctl restart networking`}</pre>
      <p className="mt-4 mb-6 text-gray-800 leading-relaxed">
        {t.rich("manualRollback.outro", { em, code })}
      </p>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("troubleshoot.heading")}</h2>

      <Callout variant="troubleshoot" title={t("troubleshoot.noneTitle")}>
        {t.rich("troubleshoot.noneBody", { code, em })}
      </Callout>

      <Callout variant="troubleshoot" title={t("troubleshoot.unreachTitle")}>
        {t.rich("troubleshoot.unreachBody", { bridgeLink, configLink })}
      </Callout>

      <Callout variant="troubleshoot" title={t("troubleshoot.emptyTitle")}>
        {t.rich("troubleshoot.emptyBody", { em })}
      </Callout>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("related.heading")}</h2>
      <ul className="list-disc pl-6 text-gray-800 leading-relaxed space-y-1">
        {relatedItems.map((item, idx) => (
          <li key={item.href}>
            <Link href={item.href} className="text-blue-600 hover:underline">
              {item.label}
            </Link>
            {item.tailRich ? t.rich(`related.items.${idx}.tailRich`, { code }) : item.tail}
          </li>
        ))}
      </ul>
    </div>
  )
}
