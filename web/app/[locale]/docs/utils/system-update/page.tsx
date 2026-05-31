import type { Metadata } from "next"
import { getTranslations, getMessages, setRequestLocale } from "next-intl/server"
import { Link } from "@/i18n/navigation"
import Image from "next/image"
import { DocHeader } from "@/components/ui/doc-header"
import { Callout } from "@/components/ui/callout"
import { DataFlowDiagram } from "@/components/ui/data-flow-diagram"
import CopyableCode from "@/components/CopyableCode"

export async function generateMetadata({
  params,
}: {
  params: Promise<{ locale: string }>
}): Promise<Metadata> {
  const { locale } = await params
  const t = await getTranslations({ locale, namespace: "docs.utils.systemUpdate.meta" })
  return {
    title: t("title"),
    description: t("description"),
    openGraph: {
      title: t("ogTitle"),
      description: t("ogDescription"),
      type: "article",
      url: "https://macrimi.github.io/ProxMenux/docs/utils/system-update",
    },
  }
}

type StringItem = string
type TroubleItem = { title: string; body: string }
type RelatedItem = { href: string; label: string; tail?: string }

export default async function SystemUpdatePage({
  params,
}: {
  params: Promise<{ locale: string }>
}) {
  const { locale } = await params
  setRequestLocale(locale)
  const t = await getTranslations({ locale, namespace: "docs.utils.systemUpdate" })

  const messages = (await getMessages({ locale })) as unknown as {
    docs: { utils: { systemUpdate: {
      onTop: { items: StringItem[] }
      worker: { items: StringItem[] }
      post: { items: StringItem[] }
      noSub: { items: StringItem[] }
      doesnt: { items: StringItem[] }
      troubleshooting: { items: TroubleItem[] }
      related: { items: RelatedItem[] }
    } } }
  }
  const block = messages.docs.utils.systemUpdate
  const onTopItems = block.onTop.items
  const workerItems = block.worker.items
  const postItems = block.post.items
  const noSubItems = block.noSub.items
  const doesntItems = block.doesnt.items
  const troubleItems = block.troubleshooting.items
  const relatedItems = block.related.items

  const code = (chunks: React.ReactNode) => <code>{chunks}</code>
  const strong = (chunks: React.ReactNode) => <strong>{chunks}</strong>
  const em = (chunks: React.ReactNode) => <em>{chunks}</em>
  const kbd = (chunks: React.ReactNode) => <kbd>{chunks}</kbd>
  const linkUpgrade = (chunks: React.ReactNode) => (
    <Link href="/docs/utils/upgrade-pve8-pve9" className="text-blue-700 hover:underline">{chunks}</Link>
  )
  const linkUpgrade2 = (chunks: React.ReactNode) => (
    <Link href="/docs/utils/upgrade-pve8-pve9" className="text-blue-600 hover:underline">{chunks}</Link>
  )

  return (
    <div>
      <DocHeader
        title={t("header.title")}
        description={t("header.description")}
        section={t("header.section")}
        estimatedMinutes={5}
        scriptPath="utilities/proxmox_update.sh"
      />

      <Callout variant="info" title={t("calloutWhat.title")}>
        {t.rich("calloutWhat.body", { strong, link: linkUpgrade })}
      </Callout>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("official.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">{t("official.intro")}</p>
      <CopyableCode code={t.raw("official.code") as string} language="bash" />
      <p className="mb-4 text-gray-800 leading-relaxed">{t("official.outro")}</p>

      <h3 className="text-lg font-semibold mt-6 mb-2 text-gray-900">{t("onTop.heading")}</h3>
      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("onTop.intro", { strong, code })}
      </p>
      <ul className="list-disc pl-6 mb-6 text-gray-800 leading-relaxed space-y-1">
        {onTopItems.map((_, idx) => (
          <li key={idx}>{t.rich(`onTop.items.${idx}`, { strong, code })}</li>
        ))}
      </ul>
      <Callout variant="info" title={t("calloutOneSentence.title")}>
        {t("calloutOneSentence.body")}
      </Callout>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("confirm.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">{t("confirm.intro")}</p>

      <Image
        src="/utils/system-update-confirm.png"
        alt={t("confirm.imageAlt")}
        width={900}
        height={500}
        className="rounded shadow-lg my-6"
      />

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("routes.heading")}</h2>

      <DataFlowDiagram
        nodes={[
          {
            label: t("routes.nodes.source.label"),
            detail: t("routes.nodes.source.detail"),
            variant: "source",
          },
          {
            label: t("routes.nodes.bridge.label"),
            detail: t("routes.nodes.bridge.detail"),
            variant: "bridge",
          },
          {
            label: t("routes.nodes.target.label"),
            detail: t("routes.nodes.target.detail"),
            variant: "target",
          },
        ]}
      />

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("worker.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("worker.intro", { code })}
      </p>
      <ol className="list-decimal pl-6 mb-6 text-gray-800 leading-relaxed space-y-2">
        {workerItems.map((_, idx) => (
          <li key={idx}>{t.rich(`worker.items.${idx}`, { strong, code })}</li>
        ))}
      </ol>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("post.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">{t("post.intro")}</p>
      <pre className="rounded-md bg-gray-100 p-4 overflow-x-auto text-xs font-mono text-gray-800 leading-relaxed border border-gray-200">{t.raw("post.code") as string}</pre>
      <p className="mt-4 mb-4 text-gray-800 leading-relaxed">{t("post.afterCode")}</p>
      <ul className="list-disc pl-6 mb-6 text-gray-800 leading-relaxed space-y-1">
        {postItems.map((_, idx) => (
          <li key={idx}>{t.rich(`post.items.${idx}`, { code })}</li>
        ))}
      </ul>
      <p className="mb-6 text-gray-800 leading-relaxed">
        {t.rich("post.outro", { em })}
      </p>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("end.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">{t("end.intro")}</p>

      <Image
        src="/utils/system-update-result.png"
        alt={t("end.imageAlt")}
        width={900}
        height={500}
        className="rounded shadow-lg my-6"
      />

      <Callout variant="warning" title={t("calloutDeclineReboot.title")}>
        {t.rich("calloutDeclineReboot.body", { code })}
      </Callout>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("noSub.heading")}</h2>
      <p className="mb-6 text-gray-800 leading-relaxed">
        {t.rich("noSub.intro", { code })}
      </p>
      <ol className="list-decimal pl-6 mb-6 text-gray-800 leading-relaxed space-y-1">
        {noSubItems.map((_, idx) => (
          <li key={idx}>{t.rich(`noSub.items.${idx}`, { code })}</li>
        ))}
      </ol>
      <p className="mb-6 text-gray-800 leading-relaxed">{t("noSub.outro")}</p>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("cluster.heading")}</h2>
      <Callout variant="warning" title={t("cluster.calloutTitle")}>
        {t.rich("cluster.calloutBody", { strong })}
      </Callout>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("doesnt.heading")}</h2>
      <ul className="list-disc pl-6 mb-6 text-gray-800 leading-relaxed space-y-1">
        {doesntItems.map((_, idx) => (
          <li key={idx}>{t.rich(`doesnt.items.${idx}`, { strong, link: linkUpgrade2 })}</li>
        ))}
      </ul>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("troubleshooting.heading")}</h2>

      {troubleItems.map((_, idx) => (
        <Callout key={idx} variant="troubleshoot" title={t(`troubleshooting.items.${idx}.title`)}>
          {t.rich(`troubleshooting.items.${idx}.body`, { code, kbd })}
        </Callout>
      ))}

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("files.heading")}</h2>
      <pre className="rounded-md bg-gray-100 p-4 overflow-x-auto text-xs font-mono text-gray-800 leading-relaxed border border-gray-200">{t.raw("files.code") as string}</pre>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("related.heading")}</h2>
      <ul className="list-disc pl-6 text-gray-800 leading-relaxed space-y-1">
        {relatedItems.map((item, idx) => (
          <li key={idx}>
            <Link href={item.href} className="text-blue-600 hover:underline">{item.label}</Link>
            {item.tail}
          </li>
        ))}
      </ul>
    </div>
  )
}
