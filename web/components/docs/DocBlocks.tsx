import type { ReactNode } from "react"
import Image from "next/image"
import { getMessages, getTranslations } from "next-intl/server"
import {
  Archive,
  Boxes,
  Braces,
  CheckCircle2,
  Cpu,
  Database,
  Download,
  ExternalLink,
  FileText,
  FolderTree,
  HardDrive,
  Layers3,
  Network,
  RefreshCw,
  ShieldCheck,
  SquareTerminal,
  Waypoints,
} from "lucide-react"
import { Link } from "@/i18n/navigation"
import { Callout } from "@/components/ui/callout"
import { DataFlowDiagram } from "@/components/ui/data-flow-diagram"
import { DocHeader } from "@/components/ui/doc-header"
import { Mermaid } from "@/components/ui/mermaid"
import { STACK_DEPENDENCY_HOOK_SOURCE } from "@/components/oci/stackDependencyHookSource"

/*
 * A documentation page described entirely by its message file.
 *
 * The page JSON holds `header` and an ordered list of `sections`, each with
 * an optional title and intro and a list of blocks. A block is an object
 * with a single key naming its kind ({"p": "..."}, {"table": {...}}), so no
 * structural value is ever a translatable string. Values the translation
 * pipeline must leave alone live under keys it copies verbatim: `code`,
 * `chartCode`, `icon`, `src`, `href`, `id`.
 *
 * Prose goes through t.rich, so it may use <code>, <strong>, <em> and the
 * link tags the page declares.
 */

type Rich = (chunks: ReactNode) => ReactNode
type Json = Record<string, any>

const ICONS: Record<string, ReactNode> = {
  archive: <Archive className="h-5 w-5" />,
  boxes: <Boxes className="h-5 w-5" />,
  braces: <Braces className="h-5 w-5" />,
  cpu: <Cpu className="h-5 w-5" />,
  database: <Database className="h-5 w-5" />,
  fileText: <FileText className="h-5 w-5" />,
  folderTree: <FolderTree className="h-5 w-5" />,
  hardDrive: <HardDrive className="h-5 w-5" />,
  layers: <Layers3 className="h-5 w-5" />,
  network: <Network className="h-5 w-5" />,
  refresh: <RefreshCw className="h-5 w-5" />,
  shield: <ShieldCheck className="h-5 w-5" />,
  terminal: <SquareTerminal className="h-5 w-5" />,
  waypoints: <Waypoints className="h-5 w-5" />,
}

const CALLOUTS = {
  calloutInfo: "info",
  calloutTip: "tip",
  calloutWarning: "warning",
  calloutDanger: "danger",
} as const

const SNIPPETS: Record<string, string> = {
  stackDependencyHook: STACK_DEPENDENCY_HOOK_SOURCE,
}

function at(root: Json, path: string): any {
  return path.split(".").reduce((node, key) => (node == null ? undefined : node[key]), root as any)
}

export async function DocPage({
  locale,
  namespace,
  minutes,
  links = {},
}: {
  locale: string
  namespace: string
  minutes: number
  links?: Record<string, string>
}) {
  const t = await getTranslations({ locale, namespace })
  const messages = (await getMessages({ locale })) as Json
  const page = at(messages, namespace) as Json

  const tags: Record<string, Rich> = {
    code: (chunks) => <code>{chunks}</code>,
    strong: (chunks) => <strong>{chunks}</strong>,
    em: (chunks) => <em>{chunks}</em>,
  }
  for (const [name, href] of Object.entries(links)) {
    tags[name] = href.startsWith("http")
      ? (chunks) => (
          <a href={href} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1 text-blue-600 hover:underline">
            {chunks}
            <ExternalLink className="h-3.5 w-3.5" />
          </a>
        )
      : (chunks) => <Link href={href} className="text-blue-600 hover:underline">{chunks}</Link>
  }
  const rich = (key: string) => t.rich(key, tags)

  const block = (key: string, value: Json, index: number): ReactNode => {
    const [kind] = Object.keys(value)
    const base = `${key}.${kind}`
    const data = value[kind]
    switch (kind) {
      case "p":
        return <p key={index} className="mb-4 text-gray-800 leading-relaxed">{rich(base)}</p>

      case "calloutInfo":
      case "calloutTip":
      case "calloutWarning":
      case "calloutDanger":
        return (
          <Callout key={index} variant={CALLOUTS[kind]} title={t(`${base}.title`)}>
            {rich(`${base}.body`)}
          </Callout>
        )

      case "list":
        return (
          <ul key={index} className="mb-6 space-y-2 text-gray-800">
            {data.items.map((_: string, i: number) => (
              <li key={i} className="flex gap-3 leading-relaxed">
                <CheckCircle2 className="mt-1 h-4 w-4 shrink-0 text-blue-600" />
                <span>{rich(`${base}.items.${i}`)}</span>
              </li>
            ))}
          </ul>
        )

      case "steps":
        return (
          <ol key={index} className="mb-6 space-y-3">
            {data.items.map((_: Json, i: number) => (
              <li key={i} className="grid grid-cols-[2.25rem_1fr] gap-4 rounded-lg border border-gray-200 bg-gray-50 p-4">
                <span className="flex h-9 w-9 items-center justify-center rounded-full bg-blue-700 text-sm font-bold text-white">{i + 1}</span>
                <div>
                  <h3 className="font-semibold text-gray-900">{t(`${base}.items.${i}.title`)}</h3>
                  <p className="mt-1 text-sm leading-6 text-gray-700">{rich(`${base}.items.${i}.body`)}</p>
                </div>
              </li>
            ))}
          </ol>
        )

      case "cards":
        return (
          <div key={index} className="mb-6 grid gap-4 md:grid-cols-2">
            {data.items.map((item: Json, i: number) => (
              <article key={i} className="rounded-lg border border-gray-200 bg-white p-5">
                {item.icon && ICONS[item.icon] && (
                  <div className="mb-3 inline-flex rounded-lg border border-blue-100 bg-blue-50 p-2 text-blue-700">{ICONS[item.icon]}</div>
                )}
                <h3 className="font-semibold text-gray-900">{t(`${base}.items.${i}.title`)}</h3>
                <p className="mt-2 text-sm leading-6 text-gray-700">{rich(`${base}.items.${i}.body`)}</p>
              </article>
            ))}
          </div>
        )

      case "table":
        return (
          <div key={index} className="mb-6 overflow-x-auto">
            <table className="w-full text-sm border border-gray-200 rounded-md">
              <thead className="bg-gray-50 text-gray-900">
                <tr>
                  {data.headers.map((_: string, i: number) => (
                    <th key={i} className="text-left px-3 py-2 border-b border-gray-200 font-semibold">{t(`${base}.headers.${i}`)}</th>
                  ))}
                </tr>
              </thead>
              <tbody className="text-gray-800">
                {data.rows.map((row: string[], r: number) => (
                  <tr key={r} className={r < data.rows.length - 1 ? "border-b border-gray-100" : ""}>
                    {row.map((_: string, c: number) => (
                      <td key={c} className={`px-3 py-2 align-top leading-6 ${c === 0 ? "font-medium text-gray-900" : ""}`}>
                        {rich(`${base}.rows.${r}.${c}`)}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )

      case "flow":
        return (
          <DataFlowDiagram
            key={index}
            className="mb-6"
            nodes={data.nodes.map((_: Json, i: number) => ({
              label: t(`${base}.nodes.${i}.label`),
              detail: data.nodes[i].detail ? t(`${base}.nodes.${i}.detail`) : undefined,
              variant: i === 0 ? "source" : i === data.nodes.length - 1 ? "target" : "bridge",
            }))}
            caption={data.caption ? t(`${base}.caption`) : undefined}
          />
        )

      case "code":
        return (
          <div key={index} className="mb-6 overflow-hidden rounded-lg border border-gray-200">
            {data.title && <div className="border-b border-gray-200 bg-gray-50 px-4 py-2 text-sm font-semibold text-gray-900">{t(`${base}.title`)}</div>}
            <pre className="overflow-x-auto bg-white p-4 text-xs leading-6 text-gray-800">{data.code}</pre>
          </div>
        )

      case "codeGrid":
        return (
          <div key={index} className="mb-6 grid gap-4 lg:grid-cols-2">
            {data.items.map((item: Json, i: number) => (
              <div key={i} className="overflow-hidden rounded-lg border border-gray-200">
                <div className="border-b border-gray-200 bg-gray-50 px-4 py-2 text-sm font-semibold text-gray-900">{t(`${base}.items.${i}.title`)}</div>
                <pre className="overflow-x-auto bg-white p-4 text-xs leading-6 text-gray-800">{item.code}</pre>
              </div>
            ))}
          </div>
        )

      case "shell":
        return (
          <pre key={index} className="mb-6 overflow-x-auto rounded-lg bg-gray-950 p-4 text-xs leading-6 text-gray-100">{data.code}</pre>
        )

      case "mermaid": {
        let chart: string = data.chartCode
        for (const name of Object.keys(data.labels ?? {})) {
          chart = chart.split(`{{${name}}}`).join(t(`${base}.labels.${name}`).replace(/"/g, "'"))
        }
        return <div key={index} className="mb-6"><Mermaid chart={chart} /></div>
      }

      case "figure":
        return (
          <figure key={index} className="my-6">
            <Image
              src={data.src}
              alt={t(`${base}.alt`)}
              width={data.width ?? 1600}
              height={data.height ?? 1000}
              className="rounded-lg border border-gray-200 shadow-sm w-full h-auto"
            />
            {data.caption && (
              <figcaption className="text-sm text-gray-500 mt-2 text-center italic">{rich(`${base}.caption`)}</figcaption>
            )}
          </figure>
        )

      case "snippet":
        return (
          <details key={index} className="group mb-6 overflow-hidden rounded-lg border border-blue-200 bg-white">
            <summary className="flex cursor-pointer list-none items-center justify-between gap-4 bg-blue-50 px-5 py-3 font-semibold text-gray-900 marker:content-none">
              <span>{t(`${base}.summary`)}</span>
              <code className="text-xs font-normal text-gray-600">{data.pathCode}</code>
            </summary>
            <pre className="max-h-[42rem] overflow-auto border-t border-blue-200 bg-gray-950 p-5 text-xs leading-6 text-gray-100">
              <code>{SNIPPETS[data.snippetCode] ?? ""}</code>
            </pre>
          </details>
        )

      case "downloads":
        return (
          <div key={index} className="mb-6 space-y-4">
            {data.items.map((item: Json, i: number) => (
              <article key={i} className="overflow-hidden rounded-lg border border-gray-200 bg-white">
                <div className="flex items-start gap-4 border-b border-gray-200 bg-gray-50 px-4 py-3">
                  <div className="min-w-0 flex-1">
                    <h3 className="font-semibold text-gray-900">{t(`${base}.items.${i}.title`)}</h3>
                    <p className="mt-1 text-sm leading-6 text-gray-700">{rich(`${base}.items.${i}.body`)}</p>
                  </div>
                  <a href={item.href} target="_blank" rel="noopener noreferrer" className="inline-flex shrink-0 items-center gap-2 rounded-md border border-blue-200 bg-blue-50 px-3 py-2 text-sm font-medium text-blue-800 hover:bg-blue-100">
                    <Download className="h-4 w-4" />PDF
                  </a>
                </div>
                <dl className="grid text-sm md:grid-cols-[11rem_1fr]">
                  {(item.facts ?? []).map((_: Json, f: number) => (
                    <div key={f} className="contents">
                      <dt className="border-t border-gray-200 bg-white px-4 py-2 font-semibold text-gray-900">{t(`${base}.items.${i}.facts.${f}.label`)}</dt>
                      <dd className="border-t border-gray-200 bg-white px-4 py-2 leading-6 text-gray-700">{rich(`${base}.items.${i}.facts.${f}.value`)}</dd>
                    </div>
                  ))}
                </dl>
              </article>
            ))}
          </div>
        )

      case "next":
        return (
          <ul key={index} className="mb-6 list-disc pl-6 space-y-1 text-gray-800">
            {data.items.map((item: Json, i: number) => (
              <li key={i}>
                <Link href={item.href} className="text-blue-600 hover:underline">{t(`${base}.items.${i}.label`)}</Link>
                {item.tail ? <> — {t(`${base}.items.${i}.tail`)}</> : null}
              </li>
            ))}
          </ul>
        )

      default:
        return null
    }
  }

  return (
    <div className="pb-16">
      <DocHeader
        title={t("header.title")}
        description={t("header.description")}
        section={t("header.section")}
        estimatedMinutes={minutes}
      />
      {(page.sections as Json[]).map((section, s) => (
        <section key={s} id={section.id} className="scroll-mt-24">
          {section.title && <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t(`sections.${s}.title`)}</h2>}
          {section.intro && <p className="mb-4 text-gray-800 leading-relaxed">{rich(`sections.${s}.intro`)}</p>}
          {(section.blocks as Json[]).map((value, b) => block(`sections.${s}.blocks.${b}`, value, b))}
        </section>
      ))}
    </div>
  )
}
