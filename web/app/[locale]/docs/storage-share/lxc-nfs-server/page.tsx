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
  const t = await getTranslations({ locale, namespace: "docs.storageShare.lxcNfsServer.meta" })
  return {
    title: t("title"),
    description: t("description"),
    openGraph: {
      title: t("ogTitle"),
      description: t("ogDescription"),
      type: "article",
      url: "https://macrimi.github.io/ProxMenux/docs/storage-share/lxc-nfs-server",
    },
  }
}

type NetworkRow = { mode: string; value: string; when?: string; whenRich?: string }
type OptionRow = { option: string; effect?: string; effectRich?: string }
type StringItem = string
type RelatedItem = { href: string; label: string; tail?: string; tailRich?: string }

export default async function LxcNfsServerPage({
  params,
}: {
  params: Promise<{ locale: string }>
}) {
  const { locale } = await params
  setRequestLocale(locale)
  const t = await getTranslations({ locale, namespace: "docs.storageShare.lxcNfsServer" })

  const messages = (await getMessages({ locale })) as unknown as {
    docs: { storageShare: { lxcNfsServer: {
      network: { rows: NetworkRow[] }
      options: { rows: OptionRow[] }
      troubleshoot: { aptItems: StringItem[]; ownItems: StringItem[] }
      related: { items: RelatedItem[] }
    } } }
  }
  const networkRows = messages.docs.storageShare.lxcNfsServer.network.rows
  const optionRows = messages.docs.storageShare.lxcNfsServer.options.rows
  const aptItems = messages.docs.storageShare.lxcNfsServer.troubleshoot.aptItems
  const ownItems = messages.docs.storageShare.lxcNfsServer.troubleshoot.ownItems
  const relatedItems = messages.docs.storageShare.lxcNfsServer.related.items

  const code = (chunks: React.ReactNode) => <code>{chunks}</code>
  const strong = (chunks: React.ReactNode) => <strong>{chunks}</strong>
  const em = (chunks: React.ReactNode) => <em>{chunks}</em>

  return (
    <div>
      <DocHeader
        title={t("header.title")}
        description={t("header.description")}
        section={t("header.section")}
        estimatedMinutes={12}
        scriptPath="share/nfs_lxc_server.sh"
      />

      <Callout variant="warning" title={t("privReq.title")}>
        {t.rich("privReq.body", { code, strong })}
      </Callout>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("what.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("what.body", { em, strong })}
      </p>

      <DataFlowDiagram
        nodes={[
          { label: t("what.diagramServerLabel"), detail: t("what.diagramServerDetail"), variant: "source" },
          { label: t("what.diagramClientLabel"), detail: t("what.diagramClientDetail"), variant: "target" },
        ]}
        arrowLabel={t("what.diagramArrow")}
        bidirectional
        command={`# /etc/exports inside the CT:
/mnt/data  <network>(rw,sync,no_subtree_check,no_root_squash)`}
      />

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("shared.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("shared.body", { code, strong })}
      </p>

      <Callout variant="info" title={t("shared.gidTitle")}>
        {t.rich("shared.gidBody", { strong, code })}
      </Callout>

      <Callout variant="warning" title={t("shared.remapTitle")}>
        {t.rich("shared.remapBody", { code, strong })}
      </Callout>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("defaults.heading")}</h2>
      <Callout variant="danger" title={t("defaults.warnTitle")}>
        {t.rich("defaults.warnBody", { code, strong })}
      </Callout>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("opening.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("opening.body", { strong })}
      </p>

      <Image
        src="/share/lxc-nfs-server-menu.png"
        alt={t("opening.imageAlt")}
        width={900}
        height={500}
        className="rounded shadow-lg my-6"
      />

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("howRuns.heading")}</h2>

      <pre className="bg-gray-100 text-gray-800 p-4 rounded-md overflow-x-auto text-sm my-4 border border-gray-200 leading-snug">
{`┌─────────────────────────────────────────────┐
│  PHASE 1 — Pick CT, folder, network, opts   │
│  (nothing touched yet)                      │
└──────────────────┬──────────────────────────┘
                   ▼
      Privileged-CT gate (share-common.func)
      ├─ pct list — pick CT
      ├─ Auto-start if stopped
      └─ Aborts if "unprivileged: 1" in CT config
                   │
                   ▼
      Folder selection (2 modes)
      ├─ Auto: choose from existing folders
      │   inside /mnt of the CT
      └─ Manual: enter any absolute path
         (must already exist inside the CT)
                   │
                   ▼
      Network ACL (3 modes)
      ├─ 1. Local network (192.168.0.0/16)
      ├─ 2. Custom subnet (e.g. 192.168.10.0/24)
      └─ 3. Single host IP
                   │
                   ▼
      Export options (3 modes)
      ├─ 1. Read-write — rw,sync,no_subtree_check,
      │                  no_root_squash  (DEFAULT)
      ├─ 2. Read-only  — ro,sync,no_subtree_check,
      │                  no_root_squash
      └─ 3. Custom     — type your own option string
                   │
   ┌──────── Cancel   OR   Confirm ────┐
   ▼                                   ▼
Exit, nothing        ┌─────────────────┴─────────────────┐
was changed          │  PHASE 2 — Install + configure     │
                     └─────────────────┬─────────────────┘
                                       ▼
                       Install NFS server (in CT)
                       └─ pct exec apt-get install -y \\
                              nfs-kernel-server
                              nfs-common rpcbind
                          + systemctl enable --now both
                          (skipped if already installed)
                                       ▼
                       setup_universal_sharedfiles_group
                       └─ groupadd -g 101000 sharedfiles
                          (or groupmod if exists at wrong GID)
                          For each regular user (UID >= 1000):
                            ├─ usermod -a -G sharedfiles <user>
                            └─ useradd -u <uid+100000> \\
                                       -g sharedfiles \\
                                       remap_<uid>
                          Same for common UIDs (33, 1000-1002)
                                       ▼
                       Apply ownership + SGID on the folder
                       └─ chown root:sharedfiles <folder>
                          chmod 2775 <folder>
                            (sticky group: new files inherit
                             the sharedfiles group)
                                       ▼
                       Update /etc/exports
                       └─ If existing entry for the folder:
                              ask "update?", remove + replace.
                          Else:
                              append the new line.
                                       ▼
                       systemctl restart rpcbind \\
                                         nfs-kernel-server
                       exportfs -ra
                                       ▼
                       Print connection details:
                       • Server IP (CT hostname -I)
                       • Export path
                       • Mount options chosen
                       • Network ACL
                       • Mount examples (auto / v4 / v3)`}
      </pre>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("network.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("network.intro", { code })}
      </p>

      <div className="overflow-x-auto mb-4 rounded-md border border-gray-200">
        <table className="min-w-full text-sm">
          <thead className="bg-gray-50 text-left text-gray-700">
            <tr>
              <th className="px-4 py-2 font-semibold">{t("network.headerMode")}</th>
              <th className="px-4 py-2 font-semibold">{t("network.headerValue")}</th>
              <th className="px-4 py-2 font-semibold">{t("network.headerWhen")}</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-200 text-gray-800">
            {networkRows.map((row, idx) => (
              <tr key={row.mode}>
                <td className="px-4 py-2 font-semibold">{row.mode}</td>
                <td className="px-4 py-2 font-mono">{row.value}</td>
                <td className="px-4 py-2">
                  {row.whenRich ? t.rich(`network.rows.${idx}.whenRich`, { code }) : row.when}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("options.heading")}</h2>
      <div className="overflow-x-auto mb-4 rounded-md border border-gray-200">
        <table className="min-w-full text-sm">
          <thead className="bg-gray-50 text-left text-gray-700">
            <tr>
              <th className="px-4 py-2 font-semibold">{t("options.headerOption")}</th>
              <th className="px-4 py-2 font-semibold">{t("options.headerEffect")}</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-200 text-gray-800">
            {optionRows.map((row, idx) => (
              <tr key={row.option}>
                <td className="px-4 py-2 font-mono">{row.option}</td>
                <td className="px-4 py-2">
                  {row.effectRich ? t.rich(`options.rows.${idx}.effectRich`, { code, strong }) : row.effect}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("manual.heading")}</h2>
      <p className="mb-3 text-gray-800 leading-relaxed">
        {t.rich("manual.body", { strong, code })}
      </p>
      <CopyableCode code={`# 1. install the NFS server (one-time)
apt-get update
apt-get install -y nfs-kernel-server nfs-common rpcbind
systemctl enable --now rpcbind nfs-kernel-server

# 2. create the sharedfiles group convention
groupadd -g 101000 sharedfiles
# add each regular user to it
for u in $(awk -F: '$3 >= 1000 && $3 < 65534 {print $1}' /etc/passwd); do
  usermod -a -G sharedfiles "$u"
done

# 3. set ownership + SGID on the folder
mkdir -p /mnt/data
chown root:sharedfiles /mnt/data
chmod 2775            /mnt/data    # SGID: new files inherit group

# 4. add the export line
echo "/mnt/data 192.168.0.0/16(rw,sync,no_subtree_check,no_root_squash)" \\
     >> /etc/exports

# 5. apply
systemctl restart rpcbind nfs-kernel-server
exportfs -ra

# verify
exportfs -v
showmount -e localhost`} />

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("view.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">{t.rich("view.body", { code })}</p>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("delete.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">{t.rich("delete.body", { code })}</p>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("status.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">{t.rich("status.body", { code })}</p>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("uninstall.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("uninstall.body", { code, strong })}
      </p>

      <Callout variant="warning" title={t("uninstall.warnTitle")}>
        {t.rich("uninstall.warnBody", { em, code })}
      </Callout>

      <h2 className="text-2xl font-semibold mt-12 mb-4 text-gray-900">{t("troubleshoot.heading")}</h2>

      <Callout variant="troubleshoot" title={t("troubleshoot.privTitle")}>
        {t.rich("troubleshoot.privBody", { code })}
      </Callout>

      <Callout variant="troubleshoot" title={t("troubleshoot.aptTitle")}>
        {t("troubleshoot.aptIntro")}
        <ul className="mt-2 list-disc list-inside space-y-1">
          {aptItems.map((_, idx) => (
            <li key={idx}>{t.rich(`troubleshoot.aptItems.${idx}`, { code })}</li>
          ))}
        </ul>
        {t("troubleshoot.aptOutro")}
      </Callout>

      <Callout variant="troubleshoot" title={t("troubleshoot.aclTitle")}>
        {t.rich("troubleshoot.aclBody", { code })}
      </Callout>

      <Callout variant="troubleshoot" title={t("troubleshoot.ownTitle")}>
        {t("troubleshoot.ownIntro")}
        <ul className="mt-2 list-disc list-inside space-y-1">
          {ownItems.map((_, idx) => (
            <li key={idx}>{t.rich(`troubleshoot.ownItems.${idx}`, { code })}</li>
          ))}
        </ul>
      </Callout>

      <Callout variant="troubleshoot" title={t("troubleshoot.noShowTitle")}>
        {t.rich("troubleshoot.noShowBody", { code })}
      </Callout>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("related.heading")}</h2>
      <ul className="list-disc pl-6 mb-4 text-gray-800 leading-relaxed space-y-1">
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
