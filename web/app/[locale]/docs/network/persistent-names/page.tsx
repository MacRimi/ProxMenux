import type { Metadata } from "next"
import { getTranslations, getMessages, setRequestLocale } from "next-intl/server"
import { Link } from "@/i18n/navigation"
import { DocHeader } from "@/components/ui/doc-header"
import { Callout } from "@/components/ui/callout"
import { DataFlowDiagram } from "@/components/ui/data-flow-diagram"

export async function generateMetadata({
  params,
}: {
  params: Promise<{ locale: string }>
}): Promise<Metadata> {
  const { locale } = await params
  const t = await getTranslations({ locale, namespace: "docs.network.persistentNames.meta" })
  return {
    title: t("title"),
    description: t("description"),
    openGraph: {
      title: t("ogTitle"),
      description: t("ogDescription"),
      type: "article",
      url: "https://macrimi.github.io/ProxMenux/docs/network/persistent-names",
    },
  }
}

type ScopeRow = { type: string; behaviour: string; why: string }
type RelatedItem = { label: string; href: string; tail?: string; tailRich?: string }

export default async function PersistentNamesPage({
  params,
}: {
  params: Promise<{ locale: string }>
}) {
  const { locale } = await params
  setRequestLocale(locale)
  const t = await getTranslations({ locale, namespace: "docs.network.persistentNames" })

  const messages = (await getMessages({ locale })) as unknown as {
    docs: { network: { persistentNames: {
      problem: { items: string[] }
      scope: { rows: ScopeRow[] }
      afterReboot: { items: string[] }
      related: { items: RelatedItem[] }
    } } }
  }
  const problemItems = messages.docs.network.persistentNames.problem.items
  const scopeRows = messages.docs.network.persistentNames.scope.rows
  const afterRebootItems = messages.docs.network.persistentNames.afterReboot.items
  const relatedItems = messages.docs.network.persistentNames.related.items

  const code = (chunks: React.ReactNode) => <code>{chunks}</code>
  const em = (chunks: React.ReactNode) => <em>{chunks}</em>

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
        {t.rich("intro.body", { code, em })}
      </Callout>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("problem.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("problem.intro", { code, em })}
      </p>
      <ul className="list-disc pl-6 mb-4 text-gray-800 leading-relaxed space-y-1">
        {problemItems.map((_, idx) => (
          <li key={idx}>{t.rich(`problem.items.${idx}`, { code })}</li>
        ))}
      </ul>
      <p className="mb-6 text-gray-800 leading-relaxed">
        {t.rich("problem.outro", { code, em })}
      </p>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("howWorks.heading")}</h2>

      <DataFlowDiagram
        nodes={[
          { label: t("howWorks.nodes.detectLabel"), detail: t("howWorks.nodes.detectDetail"), variant: "source" },
          { label: t("howWorks.nodes.readLabel"), detail: t("howWorks.nodes.readDetail"), variant: "bridge" },
          { label: t("howWorks.nodes.writeLabel"), detail: t("howWorks.nodes.writeDetail"), variant: "target" },
        ]}
        arrowLabel={t("howWorks.arrowLabel")}
      />

      <p className="mt-6 mb-4 text-gray-800 leading-relaxed">{t("howWorks.minimalIntro")}</p>
      <pre className="rounded-md bg-gray-100 p-4 overflow-x-auto text-xs font-mono text-gray-800 leading-relaxed border border-gray-200">{`# /etc/systemd/network/10-eno1.link
[Match]
MACAddress=aa:bb:cc:dd:ee:ff

[Link]
Name=eno1`}</pre>
      <p className="mt-4 mb-6 text-gray-800 leading-relaxed">
        {t.rich("howWorks.minimalOutro", { em, code })}
      </p>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("scope.heading")}</h2>
      <div className="overflow-x-auto mb-6">
        <table className="w-full text-sm border border-gray-200 rounded-md">
          <thead className="bg-gray-50 text-gray-900">
            <tr>
              <th className="text-left px-3 py-2 border-b border-gray-200">{t("scope.headerType")}</th>
              <th className="text-left px-3 py-2 border-b border-gray-200">{t("scope.headerBehaviour")}</th>
              <th className="text-left px-3 py-2 border-b border-gray-200">{t("scope.headerWhy")}</th>
            </tr>
          </thead>
          <tbody className="text-gray-800">
            {scopeRows.map((row, idx) => (
              <tr key={row.type} className={idx < scopeRows.length - 1 ? "border-b border-gray-100" : ""}>
                <td className="px-3 py-2 align-top whitespace-nowrap"><strong>{row.type}</strong></td>
                <td className="px-3 py-2 align-top">{t.rich(`scope.rows.${idx}.behaviour`, { code })}</td>
                <td className="px-3 py-2 align-top">{t.rich(`scope.rows.${idx}.why`, { code })}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("safety.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("safety.intro", { code })}
      </p>
      <pre className="rounded-md bg-gray-100 p-4 overflow-x-auto text-xs font-mono text-gray-800 leading-relaxed border border-gray-200">{`/etc/systemd/network/backup-20260426-143012/
├── 10-eno1.link    (previous version)
└── 10-enp3s0.link  (previous version)`}</pre>
      <p className="mt-4 mb-6 text-gray-800 leading-relaxed">{t("safety.outro")}</p>

      <Callout variant="warning" title={t("safety.rebootTitle")}>
        {t.rich("safety.rebootBody", { code, em })}
      </Callout>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("afterReboot.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">{t("afterReboot.intro")}</p>
      <ol className="list-decimal pl-6 mb-6 text-gray-800 leading-relaxed space-y-2">
        {afterRebootItems.map((_, idx) => (
          <li key={idx}>{t.rich(`afterReboot.items.${idx}`, { code })}</li>
        ))}
      </ol>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("troubleshoot.heading")}</h2>

      <Callout variant="troubleshoot" title={t("troubleshoot.emptyTitle")}>
        {t.rich("troubleshoot.emptyBody", { code })}
      </Callout>

      <Callout variant="troubleshoot" title={t("troubleshoot.noChangeTitle")}>
        {t.rich("troubleshoot.noChangeBody", { code })}
      </Callout>

      <Callout variant="troubleshoot" title={t("troubleshoot.undoTitle")}>
        {t.rich("troubleshoot.undoBody", { code })}
      </Callout>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("related.heading")}</h2>
      <ul className="list-disc pl-6 text-gray-800 leading-relaxed space-y-1">
        {relatedItems.map((item, idx) => (
          <li key={item.href}>
            <Link href={item.href} className="text-blue-600 hover:underline">
              {item.label}
            </Link>
            {item.tailRich ? t.rich(`related.items.${idx}.tailRich`, { em }) : item.tail}
          </li>
        ))}
      </ul>
    </div>
  )
}
