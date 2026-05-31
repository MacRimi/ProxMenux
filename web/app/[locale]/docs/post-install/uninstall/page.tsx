import type { Metadata } from "next"
import { getTranslations, getMessages, setRequestLocale } from "next-intl/server"
import { Link } from "@/i18n/navigation"
import Image from "next/image"
import { DocHeader } from "@/components/ui/doc-header"
import { Callout } from "@/components/ui/callout"
import { Steps } from "@/components/ui/steps"
import CopyableCode from "@/components/CopyableCode"

export async function generateMetadata({
  params,
}: {
  params: Promise<{ locale: string }>
}): Promise<Metadata> {
  const { locale } = await params
  const t = await getTranslations({ locale, namespace: "docs.postInstall.uninstall.meta" })
  return { title: t("title"), description: t("description") }
}

type Step = {
  title: string
  body1: string
  body2?: string
  items?: string[]
}
type ReversibleItem = { tool: string; restores: string }
type ReversibleGroup = { title: string; items: ReversibleItem[] }
type RelatedItem = { label: string; href: string; tail: string }

export default async function UninstallOptimizationsPage({
  params,
}: {
  params: Promise<{ locale: string }>
}) {
  const { locale } = await params
  setRequestLocale(locale)
  const t = await getTranslations({ locale, namespace: "docs.postInstall.uninstall" })

  const messages = (await getMessages({ locale })) as unknown as {
    docs: { postInstall: { uninstall: {
      howWorks: { steps: Step[] }
      reversible: { groups: ReversibleGroup[] }
      related: { items: RelatedItem[] }
    } } }
  }
  const steps = messages.docs.postInstall.uninstall.howWorks.steps
  const groups = messages.docs.postInstall.uninstall.reversible.groups
  const relatedItems = messages.docs.postInstall.uninstall.related.items

  const code = (chunks: React.ReactNode) => <code>{chunks}</code>
  const strong = (chunks: React.ReactNode) => <strong>{chunks}</strong>
  const em = (chunks: React.ReactNode) => <em>{chunks}</em>
  const postInstallLink = (chunks: React.ReactNode) => (
    <Link href="/docs/post-install" className="text-blue-700 hover:underline">{chunks}</Link>
  )

  return (
    <div>
      <DocHeader
        title={t("header.title")}
        description={t("header.description")}
        section={t("header.section")}
      />

      <Callout variant="info" title={t("intro.title")}>
        {t.rich("intro.body", { strong, code })}
      </Callout>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("openMenu.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("openMenu.body", { strong, em })}
      </p>

      <Image
        src="/post-install/post-install-uninstall.png"
        alt={t("openMenu.imageAlt")}
        width={900}
        height={500}
        className="rounded shadow-lg my-6"
      />

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("howWorks.heading")}</h2>

      <Steps>
        {steps.map((step, idx) => (
          <Steps.Step key={idx} title={step.title}>
            <p className="mb-3 text-gray-800">
              {t.rich(`howWorks.steps.${idx}.body1`, { code, em, strong })}
            </p>
            {step.items && (
              <ul className="list-disc pl-6 space-y-1 text-gray-800 mb-3">
                {step.items.map((_, iIdx) => (
                  <li key={iIdx}>{t.rich(`howWorks.steps.${idx}.items.${iIdx}`, { strong, code })}</li>
                ))}
              </ul>
            )}
            {step.body2 && (
              <p className="text-gray-800">
                {t.rich(`howWorks.steps.${idx}.body2`, { code })}
              </p>
            )}
          </Steps.Step>
        ))}
      </Steps>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("reversible.heading")}</h2>
      <p className="mb-6 text-gray-800 leading-relaxed">{t("reversible.intro")}</p>

      {groups.map((group) => (
        <div key={group.title} className="mb-6">
          <h3 className="text-lg font-semibold text-gray-900 mb-2">{group.title}</h3>
          <dl className="divide-y divide-gray-200 border border-gray-200 rounded-md overflow-hidden">
            {group.items.map((item) => (
              <div key={item.tool} className="grid grid-cols-1 sm:grid-cols-3 gap-2 px-4 py-3 bg-white">
                <dt className="font-medium text-gray-900 text-sm">{item.tool}</dt>
                <dd className="sm:col-span-2 text-sm text-gray-700 leading-relaxed m-0">{item.restores}</dd>
              </div>
            ))}
          </dl>
        </div>
      ))}

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("edge.heading")}</h2>

      <Callout variant="warning" title={t("edge.packageTitle")}>
        {t.rich("edge.packageBody", { strong, code })}
      </Callout>

      <Callout variant="warning" title={t("edge.rebootTitle")}>
        {t.rich("edge.rebootBody", { code, em })}
      </Callout>

      <Callout variant="tip" title={t("edge.perItemTitle")}>
        {t.rich("edge.perItemBody", { em })}
      </Callout>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("inspect.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">{t("inspect.intro")}</p>
      <CopyableCode code={`cat /usr/local/share/proxmenux/installed_tools.json | jq`} className="my-4" />
      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("inspect.outro", { code })}
      </p>

      <Callout variant="info" title={t("inspect.reinstallTitle")}>
        {t.rich("inspect.reinstallBody", { link: postInstallLink })}
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
