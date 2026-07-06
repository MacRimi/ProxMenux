import type { Metadata } from "next"
import { getTranslations, getMessages, setRequestLocale } from "next-intl/server"
import { Link } from "@/i18n/navigation"
import { DocHeader } from "@/components/ui/doc-header"

export async function generateMetadata({
  params,
}: {
  params: Promise<{ locale: string }>
}): Promise<Metadata> {
  const { locale } = await params
  const t = await getTranslations({ locale, namespace: "docs.backupRestore.glossary.meta" })
  return {
    title: t("title"),
    description: t("description"),
    keywords: [
      "proxmenux backup glossary",
      "proxmox backup terminology",
      "pbs recovery envelope",
      "pbs keyfile passphrase",
      "backup vocabulary",
    ],
    alternates: { canonical: "https://proxmenux.com/docs/backup-restore/glossary" },
    openGraph: {
      title: t("ogTitle"),
      description: t("ogDescription"),
      type: "article",
      url: "https://proxmenux.com/docs/backup-restore/glossary",
    },
    twitter: {
      card: "summary_large_image",
      title: t("twitterTitle"),
      description: t("twitterDescription"),
    },
  }
}

type Entry = { id: string; term: string; also?: string; def: string }
type Group = { title: string; intro: string; entries: Entry[] }
type WhereNextItem = { label: string; href: string; tail: string }

export default async function GlossaryPage({
  params,
}: {
  params: Promise<{ locale: string }>
}) {
  const { locale } = await params
  setRequestLocale(locale)
  const t = await getTranslations({ locale, namespace: "docs.backupRestore.glossary" })

  const messages = (await getMessages({ locale })) as unknown as {
    docs: { backupRestore: { glossary: {
      groups: Group[]
      whereNext: { items: WhereNextItem[] }
    } } }
  }
  const gl = messages.docs.backupRestore.glossary
  const groups = gl.groups
  const whereNextItems = gl.whereNext.items

  return (
    <div>
      <DocHeader
        title={t("header.title")}
        description={t("header.description")}
        section={t("header.section")}
        estimatedMinutes={8}
      />

      <p className="mt-8 mb-8 text-gray-800 leading-relaxed">
        {t("intro.body")}
      </p>

      <nav
        className="mb-10 rounded-lg border border-gray-200 bg-gray-50 p-4"
        aria-label={t("header.title")}
      >
        <ul className="flex flex-wrap gap-x-4 gap-y-2 text-sm">
          {groups.map((group, idx) => (
            <li key={idx}>
              <a
                href={`#group-${idx}`}
                className="text-blue-600 hover:underline font-medium"
              >
                {group.title}
              </a>
            </li>
          ))}
        </ul>
      </nav>

      {groups.map((group, idx) => (
        <section key={idx} id={`group-${idx}`} className="mb-12 scroll-mt-24">
          <h2 className="text-2xl font-semibold mt-10 mb-3 text-gray-900">
            {group.title}
          </h2>
          <p className="mb-6 text-gray-800 leading-relaxed">
            {group.intro}
          </p>
          <dl className="space-y-6">
            {group.entries.map((entry) => (
              <div
                key={entry.id}
                id={entry.id}
                className="scroll-mt-24 border-l-4 border-blue-100 pl-4"
              >
                <dt className="mb-1">
                  <span className="font-semibold text-gray-900">{entry.term}</span>
                  {entry.also ? (
                    <span className="ml-2 text-sm text-gray-500 italic">
                      ({entry.also})
                    </span>
                  ) : null}
                </dt>
                <dd
                  className="text-gray-800 leading-relaxed [&_a]:text-blue-600 [&_a]:hover:underline [&_code]:bg-gray-100 [&_code]:px-1 [&_code]:py-0.5 [&_code]:rounded [&_code]:text-sm"
                  dangerouslySetInnerHTML={{ __html: entry.def }}
                />
              </div>
            ))}
          </dl>
        </section>
      ))}

      <h2 className="text-2xl font-semibold mt-12 mb-4 text-gray-900">
        {t("whereNext.heading")}
      </h2>

      <ul className="mb-6 space-y-2">
        {whereNextItems.map((item) => (
          <li key={item.href} className="text-gray-800 leading-relaxed">
            <Link href={item.href} className="text-blue-600 hover:underline font-medium">
              {item.label}
            </Link>
            <span>{item.tail}</span>
          </li>
        ))}
      </ul>
    </div>
  )
}
