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
  const t = await getTranslations({ locale, namespace: "docs.storageShare.hostIscsi.meta" })
  return {
    title: t("title"),
    description: t("description"),
    openGraph: {
      title: t("ogTitle"),
      description: t("ogDescription"),
      type: "article",
      url: "https://macrimi.github.io/ProxMenux/docs/storage-share/host-iscsi",
    },
  }
}

type VocabRow = { term: string; meaningRich: string }
type StringItem = string
type RelatedItem = { href: string; label: string; tail?: string }

export default async function HostIscsiPage({
  params,
}: {
  params: Promise<{ locale: string }>
}) {
  const { locale } = await params
  setRequestLocale(locale)
  const t = await getTranslations({ locale, namespace: "docs.storageShare.hostIscsi" })

  const messages = (await getMessages({ locale })) as unknown as {
    docs: { storageShare: { hostIscsi: {
      vocab: { rows: VocabRow[] }
      add: { items: StringItem[] }
      troubleshoot: { discoverItems: StringItem[] }
      related: { items: RelatedItem[] }
    } } }
  }
  const vocabRows = messages.docs.storageShare.hostIscsi.vocab.rows
  const addItems = messages.docs.storageShare.hostIscsi.add.items
  const discoverItems = messages.docs.storageShare.hostIscsi.troubleshoot.discoverItems
  const relatedItems = messages.docs.storageShare.hostIscsi.related.items

  const code = (chunks: React.ReactNode) => <code>{chunks}</code>
  const strong = (chunks: React.ReactNode) => <strong>{chunks}</strong>
  const em = (chunks: React.ReactNode) => <em>{chunks}</em>

  return (
    <div>
      <DocHeader
        title={t("header.title")}
        description={t("header.description")}
        section={t("header.section")}
        estimatedMinutes={10}
        scriptPath="share/iscsi_host.sh"
      />

      <Callout variant="info" title={t("intro.title")}>
        {t.rich("intro.body", { code })}
      </Callout>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("vocab.heading")}</h2>
      <div className="overflow-x-auto mb-4 rounded-md border border-gray-200">
        <table className="min-w-full text-sm">
          <thead className="bg-gray-50 text-left text-gray-700">
            <tr>
              <th className="px-4 py-2 font-semibold">{t("vocab.headerTerm")}</th>
              <th className="px-4 py-2 font-semibold">{t("vocab.headerMeaning")}</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-200 text-gray-800">
            {vocabRows.map((row, idx) => (
              <tr key={row.term}>
                <td className="px-4 py-2 font-mono">{row.term}</td>
                <td className="px-4 py-2">{t.rich(`vocab.rows.${idx}.meaningRich`, { code, em })}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("opening.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("opening.body", { strong })}
      </p>

      <Image
        src="/share/host-iscsi-menu.png"
        alt={t("opening.imageAlt")}
        width={900}
        height={500}
        className="rounded shadow-lg my-6"
      />

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("howRuns.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">{t("howRuns.body")}</p>

      <pre className="bg-gray-100 text-gray-800 p-4 rounded-md overflow-x-auto text-sm my-4 border border-gray-200 leading-snug">
{`┌─────────────────────────────────────────────┐
│  PHASE 1 — Prepare initiator, discover      │
│  (nothing touched yet in storage.cfg)       │
└──────────────────┬──────────────────────────┘
                   ▼
      Dependency check
      └─ iscsiadm present? (open-iscsi package)
         If missing → apt-get install open-iscsi
                     + systemctl enable --now iscsid
                   │
                   ▼
      Portal entry (manual only)
      └─ user types  <ip>  or  <ip>:<port>
         If no ':' → ProxMenux appends ":3260"
                   │
                   ▼
      Reachability validation
      ├─ ping -c 1 -W 3 <host>          ── fail → abort
      └─ nc -z -w 3 <host> <port>       ── warn but continue
         (iSCSI over alternative ports may block nc)
                   │
                   ▼
      Target discovery
      iscsiadm --mode discovery --type sendtargets \\
               --portal <ip:port>
      Extracts IQNs from stdout (lines matching ^iqn\\.)
                   │
                   ▼
      Target selection
      ├─ 1 target found → auto-selected
      └─ 2+ targets    → menu
                   │
                   ▼
      Storage ID
      (default derived from last ':' segment of the IQN:
         "iscsi-<suffix-up-to-20-chars>")
                   │
                   ▼
      Content type (fixed — not a checklist)
      └─ images        iSCSI exposes block devices, so
                       only 'images' makes sense. No
                       backup/iso/vztmpl/rootdir/snippets.
                   │
   ┌──────── Cancel   OR   Confirm ────┐
   ▼                                   ▼
Exit, nothing        ┌─────────────────┴─────────────────┐
was changed          │  PHASE 2 — Register in Proxmox     │
                     └─────────────────┬─────────────────┘
                                       ▼
                       If storage ID already exists:
                       └─ ask "remove and recreate?"
                          └─ yes → pvesm remove <id>
                          └─ no  → abort
                                       ▼
                       pvesm add iscsi <id> \\
                           --portal <ip:port> \\
                           --target <iqn> \\
                           --content images
                                       │
                                       ▼
                       iscsid opens a persistent session to
                       the target; LUNs appear in /dev/disk/
                       by-path/ip-<ip>:<port>-iscsi-<iqn>-lun-N
                                       │
                                       ▼
                       Proxmox auto-connects on every boot
                       via the node.startup=automatic flag
                       written by pvesm`}
      </pre>

      <h2 className="text-2xl font-semibold mt-12 mb-4 text-gray-900">{t("add.heading")}</h2>

      <ol className="list-decimal pl-6 mb-4 text-gray-800 leading-relaxed space-y-2">
        {addItems.map((_, idx) => (
          <li key={idx}>{t.rich(`add.items.${idx}`, { strong, code })}</li>
        ))}
      </ol>

      <Callout variant="warning" title={t("add.authTitle")}>
        {t("add.authBody1")}
        <pre className="mt-2 p-2 rounded bg-white/50 text-xs overflow-x-auto"><code>cat /etc/iscsi/initiatorname.iscsi</code></pre>
        {t.rich("add.authBody2", { em, code })}
      </Callout>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("manual.heading")}</h2>
      <p className="mb-3 text-gray-800 leading-relaxed">{t("manual.body")}</p>
      <CopyableCode code={`apt-get install -y open-iscsi
systemctl enable --now iscsid

# 1. discover targets on a portal
iscsiadm --mode discovery --type sendtargets \\
         --portal 10.0.0.60:3260

# 2. register it in Proxmox
pvesm add iscsi myiscsi \\
  --portal 10.0.0.60:3260 \\
  --target iqn.2024-08.com.truenas:proxmox-pool \\
  --content images

# 3. verify + see the block devices
pvesm status myiscsi
ls -la /dev/disk/by-path/ | grep iscsi`} />

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("view.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">{t.rich("view.body", { code })}</p>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("remove.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">{t.rich("remove.body", { code, strong })}</p>

      <Callout variant="warning" title={t("remove.warnTitle")}>
        {t("remove.warnBody")}
      </Callout>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("test.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">{t.rich("test.body", { code })}</p>

      <h2 className="text-2xl font-semibold mt-12 mb-4 text-gray-900">{t("troubleshoot.heading")}</h2>

      <Callout variant="troubleshoot" title={t("troubleshoot.portalTitle")}>
        {t.rich("troubleshoot.portalBody", { em })}
      </Callout>

      <Callout variant="troubleshoot" title={t("troubleshoot.discoverTitle")}>
        {t("troubleshoot.discoverIntro")}
        <ul className="mt-2 list-disc list-inside space-y-1">
          {discoverItems.map((_, idx) => (
            <li key={idx}>{t.rich(`troubleshoot.discoverItems.${idx}`, { strong })}</li>
          ))}
        </ul>
      </Callout>

      <Callout variant="troubleshoot" title={t("troubleshoot.noTargetTitle")}>
        {t("troubleshoot.noTargetBody")}
      </Callout>

      <Callout variant="troubleshoot" title={t("troubleshoot.noLunTitle")}>
        {t.rich("troubleshoot.noLunBody", { code })}
      </Callout>

      <Callout variant="troubleshoot" title={t("troubleshoot.chapTitle")}>
        {t.rich("troubleshoot.chapBody", { code })}
      </Callout>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("related.heading")}</h2>
      <ul className="list-disc pl-6 mb-4 text-gray-800 leading-relaxed space-y-1">
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
