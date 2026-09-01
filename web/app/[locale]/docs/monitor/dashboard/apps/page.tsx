import type { Metadata } from "next"
import type React from "react"
import { getMessages, getTranslations, setRequestLocale } from "next-intl/server"
import { Link } from "@/i18n/navigation"
import { Callout } from "@/components/ui/callout"
import { DocHeader } from "@/components/ui/doc-header"

export async function generateMetadata({
  params,
}: {
  params: Promise<{ locale: string }>
}): Promise<Metadata> {
  const { locale } = await params
  const t = await getTranslations({ locale, namespace: "docs.monitor.dashboard.apps.meta" })
  return { title: t("title"), description: t("description") }
}

type SourceRow = { source: string; appears: string; managedFrom: string }
type FieldRow = { field: string; required: string; purpose: string }
type ProblemRow = { problem: string; resolution: string }

export default async function AppsDashboardPage({
  params,
}: {
  params: Promise<{ locale: string }>
}) {
  const { locale } = await params
  setRequestLocale(locale)
  const t = await getTranslations({ locale, namespace: "docs.monitor.dashboard.apps" })
  const messages = (await getMessages({ locale })) as unknown as {
    docs: { monitor: { dashboard: { apps: {
      sources: { rows: SourceRow[] }
      cards: { items: string[] }
      toolbar: { items: string[] }
      customLinks: { steps: string[]; fields: FieldRow[] }
      categories: { items: string[] }
      persistence: { items: string[] }
      troubleshooting: { rows: ProblemRow[] }
      whereNext: { items: { label: string; href: string; tail: string }[] }
    } } } }
  }
  const a = messages.docs.monitor.dashboard.apps

  const strong = (chunks: React.ReactNode) => <strong>{chunks}</strong>
  const em = (chunks: React.ReactNode) => <em>{chunks}</em>
  const code = (chunks: React.ReactNode) => <code className="rounded bg-gray-100 px-1 text-sm">{chunks}</code>
  const appTabLink = (chunks: React.ReactNode) => (
    <Link href="/docs/monitor/dashboard/vms-lxcs/app" className="text-blue-600 hover:underline">{chunks}</Link>
  )
  const updatesLink = (chunks: React.ReactNode) => (
    <Link href="/docs/monitor/dashboard/vms-lxcs/updates" className="text-blue-600 hover:underline">{chunks}</Link>
  )
  const settingsLink = (chunks: React.ReactNode) => (
    <Link href="/docs/monitor/dashboard/settings#navigation-order" className="text-blue-600 hover:underline">{chunks}</Link>
  )
  const richList = (base: string, items: string[]) => (
    <ul className="mt-2 list-disc space-y-2 pl-6 text-gray-800">
      {items.map((_, idx) => (
        <li key={idx}>{t.rich(`${base}.${idx}`, { strong, em, code, appTabLink, updatesLink, settingsLink })}</li>
      ))}
    </ul>
  )

  return (
    <div className="mx-auto max-w-4xl px-4 py-8">
      <DocHeader
        title={t("header.title")}
        description={t("header.description")}
        section={t("header.section")}
        estimatedMinutes={6}
      />

      <Callout variant="info" title={t("intro.title")}>
        {t.rich("intro.body", { strong, appTabLink })}
      </Callout>

      <h2 className="mt-10 mb-4 text-2xl font-semibold text-gray-900">{t("sources.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">{t("sources.intro")}</p>
      <div className="my-4 overflow-x-auto">
        <table className="w-full border-collapse text-sm">
          <thead>
            <tr className="bg-gray-100">
              <th className="border border-gray-300 px-3 py-2 text-left">{t("sources.colSource")}</th>
              <th className="border border-gray-300 px-3 py-2 text-left">{t("sources.colAppears")}</th>
              <th className="border border-gray-300 px-3 py-2 text-left">{t("sources.colManagedFrom")}</th>
            </tr>
          </thead>
          <tbody>
            {a.sources.rows.map((row) => (
              <tr key={row.source}>
                <td className="border border-gray-300 px-3 py-2 font-medium">{row.source}</td>
                <td className="border border-gray-300 px-3 py-2">{row.appears}</td>
                <td className="border border-gray-300 px-3 py-2">{row.managedFrom}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <Callout variant="tip" title={t("sources.relationshipTitle")}>
        {t.rich("sources.relationshipBody", { strong, appTabLink })}
      </Callout>

      <h2 className="mt-10 mb-4 text-2xl font-semibold text-gray-900">{t("cards.heading")}</h2>
      <p className="text-gray-800">{t("cards.intro")}</p>
      {richList("cards.items", a.cards.items)}

      <h2 className="mt-10 mb-4 text-2xl font-semibold text-gray-900">{t("toolbar.heading")}</h2>
      <p className="text-gray-800">{t("toolbar.intro")}</p>
      {richList("toolbar.items", a.toolbar.items)}

      <h2 className="mt-10 mb-4 text-2xl font-semibold text-gray-900">{t("customLinks.heading")}</h2>
      <p className="text-gray-800">{t("customLinks.intro")}</p>
      <ol className="mt-2 list-decimal space-y-2 pl-6 text-gray-800">
        {a.customLinks.steps.map((_, idx) => (
          <li key={idx}>{t.rich(`customLinks.steps.${idx}`, { strong, em, code })}</li>
        ))}
      </ol>
      <div className="my-6 overflow-x-auto">
        <table className="w-full border-collapse text-sm">
          <thead>
            <tr className="bg-gray-100">
              <th className="border border-gray-300 px-3 py-2 text-left">{t("customLinks.colField")}</th>
              <th className="border border-gray-300 px-3 py-2 text-left">{t("customLinks.colRequired")}</th>
              <th className="border border-gray-300 px-3 py-2 text-left">{t("customLinks.colPurpose")}</th>
            </tr>
          </thead>
          <tbody>
            {a.customLinks.fields.map((row) => (
              <tr key={row.field}>
                <td className="border border-gray-300 px-3 py-2 font-medium">{row.field}</td>
                <td className="border border-gray-300 px-3 py-2">{row.required}</td>
                <td className="border border-gray-300 px-3 py-2">{row.purpose}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <Callout variant="warning" title={t("customLinks.editTitle")}>
        {t.rich("customLinks.editBody", { strong, appTabLink })}
      </Callout>

      <h2 className="mt-10 mb-4 text-2xl font-semibold text-gray-900">{t("categories.heading")}</h2>
      <p className="text-gray-800">{t("categories.intro")}</p>
      {richList("categories.items", a.categories.items)}

      <h2 className="mt-10 mb-4 text-2xl font-semibold text-gray-900">{t("persistence.heading")}</h2>
      <p className="text-gray-800">{t("persistence.intro")}</p>
      {richList("persistence.items", a.persistence.items)}

      <h2 className="mt-10 mb-4 text-2xl font-semibold text-gray-900">{t("troubleshooting.heading")}</h2>
      <div className="my-4 overflow-x-auto">
        <table className="w-full border-collapse text-sm">
          <thead>
            <tr className="bg-gray-100">
              <th className="border border-gray-300 px-3 py-2 text-left">{t("troubleshooting.colProblem")}</th>
              <th className="border border-gray-300 px-3 py-2 text-left">{t("troubleshooting.colResolution")}</th>
            </tr>
          </thead>
          <tbody>
            {a.troubleshooting.rows.map((row) => (
              <tr key={row.problem}>
                <td className="border border-gray-300 px-3 py-2 font-medium">{row.problem}</td>
                <td className="border border-gray-300 px-3 py-2">{row.resolution}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <h2 className="mt-10 mb-4 text-2xl font-semibold text-gray-900">{t("whereNext.heading")}</h2>
      <ul className="list-disc space-y-1 pl-6 text-gray-800">
        {a.whereNext.items.map((item) => (
          <li key={item.href}>
            <Link href={item.href} className="text-blue-600 hover:underline">{item.label}</Link>
            {item.tail}
          </li>
        ))}
      </ul>
    </div>
  )
}
