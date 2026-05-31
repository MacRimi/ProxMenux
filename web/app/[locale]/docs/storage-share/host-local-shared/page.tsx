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
  const t = await getTranslations({ locale, namespace: "docs.storageShare.hostLocalShared.meta" })
  return {
    title: t("title"),
    description: t("description"),
    openGraph: {
      title: t("ogTitle"),
      description: t("ogDescription"),
      type: "article",
      url: "https://macrimi.github.io/ProxMenux/docs/storage-share/host-local-shared",
    },
  }
}

type StringItem = string
type BitsRow = { bit: string; effect: string; why: string }
type RelatedItem = { href: string; label: string; tail?: string; tailRich?: string }

export default async function HostLocalSharedPage({
  params,
}: {
  params: Promise<{ locale: string }>
}) {
  const { locale } = await params
  setRequestLocale(locale)
  const t = await getTranslations({ locale, namespace: "docs.storageShare.hostLocalShared" })

  const messages = (await getMessages({ locale })) as unknown as {
    docs: { storageShare: { hostLocalShared: {
      why: { items: StringItem[] }
      bits: { rows: BitsRow[] }
      related: { items: RelatedItem[] }
    } } }
  }
  const whyItems = messages.docs.storageShare.hostLocalShared.why.items
  const bitsRows = messages.docs.storageShare.hostLocalShared.bits.rows
  const relatedItems = messages.docs.storageShare.hostLocalShared.related.items

  const code = (chunks: React.ReactNode) => <code>{chunks}</code>
  const strong = (chunks: React.ReactNode) => <strong>{chunks}</strong>
  const kbd = (chunks: React.ReactNode) => <kbd>{chunks}</kbd>
  const mountLink = (chunks: React.ReactNode) => (
    <Link href="/docs/storage-share/lxc-mount-points" className="text-blue-700 hover:underline">{chunks}</Link>
  )
  const diskLink = (chunks: React.ReactNode) => (
    <Link href="/docs/storage-share/host-local-disk" className="text-blue-600 hover:underline">{chunks}</Link>
  )

  return (
    <div>
      <DocHeader
        title={t("header.title")}
        description={t("header.description")}
        section={t("header.section")}
        estimatedMinutes={3}
        scriptPath="share/local-shared-manager.sh"
      />

      <Callout variant="info" title={t("intro.title")}>
        {t.rich("intro.body", { strong, code, mountLink })}
      </Callout>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("why.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">{t("why.intro")}</p>
      <ul className="list-disc pl-6 mb-4 text-gray-800 leading-relaxed space-y-1">
        {whyItems.map((_, idx) => (
          <li key={idx}>{t.rich(`why.items.${idx}`, { strong })}</li>
        ))}
      </ul>
      <p className="mb-4 text-gray-800 leading-relaxed">{t.rich("why.outro", { strong })}</p>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("howRuns.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">{t.rich("howRuns.body", { strong })}</p>

      <pre className="bg-gray-100 text-gray-800 p-4 rounded-md overflow-x-auto text-sm my-4 border border-gray-200 leading-snug">
{`┌─────────────────────────────────────────────┐
│  PHASE 1 — Pick the target path             │
│  (nothing touched yet)                      │
└──────────────────┬──────────────────────────┘
                   ▼
      Location picker (4 options)
      ├─ 1. Create new folder in /mnt
      │       ProxMenux suggests a free name
      │       ("shared", "shared2", "shared3"…)
      ├─ 2. Enter custom path
      │       Any absolute path on the host
      ├─ 3. View existing folders in /mnt
      │       Read-only summary (perms, owner,
      │       free space) then back to menu
      └─ 4. Cancel
                   │
                   ▼
      Path validation
      └─ Must start with "/" (absolute path)
         Non-absolute → reject, re-ask
                   │
                   ▼
      Existing directory?
      └─ If /mnt/<name> already exists, ask
         "Continue with permission setup?"
         (adjusting existing dir is allowed)
                   │
   ┌──────── Cancel   OR   Confirm ────┐
   ▼                                   ▼
Exit, nothing        ┌─────────────────┴─────────────────┐
was changed          │  PHASE 2 — Create + set perms      │
                     └─────────────────┬─────────────────┘
                                       ▼
                       mkdir -p <target>
                                       ▼
                       chown root:root <target>
                                       ▼
                       chmod 1777 <target>
                        (sticky bit + world-rwx)
                                       ▼
                       chmod -R a+rwX <target>
                        (existing content stays accessible;
                         X = execute only on directories)
                                       ▼
                       find <target> -type d \\
                            -exec chmod 1777 {} +
                        (propagate sticky bit to subdirs)
                                       ▼
                       setfacl -b -R <target>
                        (remove any restrictive ACLs)
                                       ▼
                       setfacl -R -m u::rwx,g::rwx,o::rwx,m::rwx
                        (explicit rwx for user/group/other/mask)
                                       ▼
                       setfacl -R -m d:u::rwx,d:g::rwx,...
                        (default ACLs so NEW files inherit rwx)
                                       ▼
                       Register in ProxMenux share map
                        (pmx_share_map_set <dir> "open")
                                       ▼
                       Summary:
                       • directory path
                       • permissions: 1777 (rwxrwxrwt)
                       • owner: root:root
                       • ACL: open rwx + default inheritance
                       • profile: works with priv and
                         unprivileged LXCs`}
      </pre>

      <h2 className="text-2xl font-semibold mt-12 mb-4 text-gray-900">{t("bits.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("bits.intro", { strong, code })}
      </p>

      <div className="overflow-x-auto mb-4 rounded-md border border-gray-200">
        <table className="min-w-full text-sm">
          <thead className="bg-gray-50 text-left text-gray-700">
            <tr>
              <th className="px-4 py-2 font-semibold">{t("bits.headerBit")}</th>
              <th className="px-4 py-2 font-semibold">{t("bits.headerEffect")}</th>
              <th className="px-4 py-2 font-semibold">{t("bits.headerWhy")}</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-200 text-gray-800">
            {bitsRows.map((row) => (
              <tr key={row.bit}>
                <td className="px-4 py-2 font-mono">{row.bit}</td>
                <td className="px-4 py-2">{row.effect}</td>
                <td className="px-4 py-2">{row.why}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <Callout variant="info" title={t("bits.privTitle")}>
        {t.rich("bits.privBody", { code })}
      </Callout>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("where.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">{t("where.intro")}</p>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4 my-6">
        <div className="rounded-lg border border-gray-200 bg-white p-4">
          <h3 className="text-base font-semibold text-gray-900 mb-2">{t("where.opt1Title")}</h3>
          <p className="text-sm text-gray-700 leading-relaxed">{t.rich("where.opt1Body", { code })}</p>
        </div>
        <div className="rounded-lg border border-gray-200 bg-white p-4">
          <h3 className="text-base font-semibold text-gray-900 mb-2">{t("where.opt2Title")}</h3>
          <p className="text-sm text-gray-700 leading-relaxed">{t.rich("where.opt2Body", { code })}</p>
        </div>
        <div className="rounded-lg border border-gray-200 bg-white p-4">
          <h3 className="text-base font-semibold text-gray-900 mb-2">{t("where.opt3Title")}</h3>
          <p className="text-sm text-gray-700 leading-relaxed">{t.rich("where.opt3Body", { code })}</p>
        </div>
        <div className="rounded-lg border border-gray-200 bg-white p-4">
          <h3 className="text-base font-semibold text-gray-900 mb-2">{t("where.opt4Title")}</h3>
          <p className="text-sm text-gray-700 leading-relaxed">{t.rich("where.opt4Body", { kbd })}</p>
        </div>
      </div>

      <Callout variant="tip" title={t("where.tipTitle")}>
        {t.rich("where.tipBody", { code, diskLink })}
      </Callout>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("manual.heading")}</h2>
      <p className="mb-3 text-gray-800 leading-relaxed">{t("manual.body")}</p>
      <CopyableCode code={`# 1. create the directory
mkdir -p /mnt/shared

# 2. apply 1777 (sticky + world-rwx) + open existing content
chown root:root /mnt/shared
chmod 1777 /mnt/shared
chmod -R a+rwX /mnt/shared
find /mnt/shared -type d -exec chmod 1777 {} +

# 3. ACLs: explicit rwx + default inheritance for new files
setfacl -b -R /mnt/shared
setfacl -R -m u::rwx,g::rwx,o::rwx,m::rwx /mnt/shared
setfacl -R -m d:u::rwx,d:g::rwx,d:o::rwx,d:m::rwx /mnt/shared`} />

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("next.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("next.body", { strong, code, mountLink })}
      </p>

      <h2 className="text-2xl font-semibold mt-12 mb-4 text-gray-900">{t("troubleshoot.heading")}</h2>

      <Callout variant="troubleshoot" title={t("troubleshoot.mkdirTitle")}>
        {t.rich("troubleshoot.mkdirBody", { code })}
      </Callout>

      <Callout variant="troubleshoot" title={t("troubleshoot.writeTitle")}>
        {t.rich("troubleshoot.writeBody", { code })}
      </Callout>

      <Callout variant="troubleshoot" title={t("troubleshoot.aclTitle")}>
        {t.rich("troubleshoot.aclBody", { code })}
      </Callout>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("related.heading")}</h2>
      <ul className="list-disc pl-6 mb-4 text-gray-800 leading-relaxed space-y-1">
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
