import type { Metadata } from "next"
import { getTranslations, getMessages, setRequestLocale } from "next-intl/server"
import { Link } from "@/i18n/navigation"
import { ExternalLink } from "lucide-react"
import { DocHeader } from "@/components/ui/doc-header"
import { Callout } from "@/components/ui/callout"
import CopyableCode from "@/components/CopyableCode"

export async function generateMetadata({
  params,
}: {
  params: Promise<{ locale: string }>
}): Promise<Metadata> {
  const { locale } = await params
  const t = await getTranslations({ locale, namespace: "docs.postInstall.performance.meta" })
  return { title: t("title"), description: t("description") }
}

type RelatedItem = { label: string; href: string; tail?: string; tailRich?: string }

export default async function PostInstallPerformancePage({
  params,
}: {
  params: Promise<{ locale: string }>
}) {
  const { locale } = await params
  setRequestLocale(locale)
  const t = await getTranslations({ locale, namespace: "docs.postInstall.performance" })

  const messages = (await getMessages({ locale })) as unknown as {
    docs: { postInstall: { performance: {
      pigz: { doesItems: string[] }
      related: { items: RelatedItem[] }
    } } }
  }
  const doesItems = messages.docs.postInstall.performance.pigz.doesItems
  const relatedItems = messages.docs.postInstall.performance.related.items

  const code = (chunks: React.ReactNode) => <code>{chunks}</code>
  const strong = (chunks: React.ReactNode) => <strong>{chunks}</strong>
  const em = (chunks: React.ReactNode) => <em>{chunks}</em>
  const pigzAnchor = (chunks: React.ReactNode) => (
    <a href="https://zlib.net/pigz/" target="_blank" rel="noopener noreferrer" className="text-blue-600 hover:underline inline-flex items-center gap-1">
      {chunks}
      <ExternalLink className="w-3 h-3" />
    </a>
  )

  return (
    <div>
      <DocHeader
        title={t("header.title")}
        description={t("header.description")}
        section={t("header.section")}
      />

      <Callout variant="info" title={t("intro.title")}>
        {t.rich("intro.body", { em })}
      </Callout>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("pigz.heading")}</h2>

      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("pigz.intro", { code, strong, a: pigzAnchor })}
      </p>

      <h3 className="text-lg font-semibold mt-6 mb-2 text-gray-900">{t("pigz.doesTitle")}</h3>
      <p className="mb-3 text-gray-800 leading-relaxed">{t("pigz.doesIntro")}</p>
      <ol className="list-decimal pl-6 space-y-2 text-gray-800 mb-4">
        {doesItems.map((_, idx) => (
          <li key={idx}>{t.rich(`pigz.doesItems.${idx}`, { code, em })}</li>
        ))}
      </ol>

      <CopyableCode
        code={`# What ProxMenux runs under the hood
sed -i "s/#pigz:.*/pigz: 1/" /etc/vzdump.conf
apt-get -y install pigz

cat > /bin/pigzwrapper <<'EOF'
#!/bin/sh
PATH=/bin:$PATH
GZIP="-1"
exec /usr/bin/pigz "$@"
EOF
chmod +x /bin/pigzwrapper

# Only replaces gzip if not already replaced (idempotent)
[ ! -f /bin/gzip.original ] && mv /bin/gzip /bin/gzip.original \\
  && cp /bin/pigzwrapper /bin/gzip && chmod +x /bin/gzip`}
        className="my-4"
      />

      <Callout variant="warning" title={t("pigz.replacesTitle")}>
        {t.rich("pigz.replacesBody", { code })}
      </Callout>

      <Callout variant="danger" title={t("pigz.revertTitle")}>
        {t.rich("pigz.revertBody", { strong })}
      </Callout>

      <CopyableCode
        code={`# Manual rollback of pigz
mv /bin/gzip.original /bin/gzip    # restore original binary
rm /bin/pigzwrapper
sed -i 's/^pigz: 1/#pigz: 1/' /etc/vzdump.conf
# Optional: remove the package
apt purge pigz`}
        className="my-4"
      />

      <h3 className="text-lg font-semibold mt-6 mb-2 text-gray-900">{t("pigz.verifyTitle")}</h3>
      <p className="mb-3 text-gray-800 leading-relaxed">
        {t.rich("pigz.verifyBody", { code })}
      </p>
      <CopyableCode
        code={`# Confirm gzip now points to pigz
gzip --version
# Expected first line: "pigz 2.x … by Mark Adler"

# Compare throughput (create a 1GB file of random data and compress it)
dd if=/dev/urandom of=/tmp/test.bin bs=1M count=1024 status=none
time gzip -k /tmp/test.bin       # uses pigz — parallel
rm /tmp/test.bin.gz

time /bin/gzip.original -k /tmp/test.bin   # original single-threaded gzip
rm /tmp/test.bin /tmp/test.bin.gz`}
        className="my-4"
      />

      <Callout variant="tip" title={t("pigz.whenTitle")}>
        {t.rich("pigz.whenBody", { strong })}
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
