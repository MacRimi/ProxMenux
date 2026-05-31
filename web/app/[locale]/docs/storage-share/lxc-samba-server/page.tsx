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
  const t = await getTranslations({ locale, namespace: "docs.storageShare.lxcSambaServer.meta" })
  return {
    title: t("title"),
    description: t("description"),
    openGraph: {
      title: t("ogTitle"),
      description: t("ogDescription"),
      type: "article",
      url: "https://macrimi.github.io/ProxMenux/docs/storage-share/lxc-samba-server",
    },
  }
}

type StringItem = string
type RelatedItem = { href: string; label: string; tail?: string; tailRich?: string }

export default async function LxcSambaServerPage({
  params,
}: {
  params: Promise<{ locale: string }>
}) {
  const { locale } = await params
  setRequestLocale(locale)
  const t = await getTranslations({ locale, namespace: "docs.storageShare.lxcSambaServer" })

  const messages = (await getMessages({ locale })) as unknown as {
    docs: { storageShare: { lxcSambaServer: {
      troubleshoot: { aptItems: StringItem[] }
      related: { items: RelatedItem[] }
    } } }
  }
  const aptItems = messages.docs.storageShare.lxcSambaServer.troubleshoot.aptItems
  const relatedItems = messages.docs.storageShare.lxcSambaServer.related.items

  const code = (chunks: React.ReactNode) => <code>{chunks}</code>
  const strong = (chunks: React.ReactNode) => <strong>{chunks}</strong>
  const em = (chunks: React.ReactNode) => <em>{chunks}</em>
  const nfsLink = (chunks: React.ReactNode) => (
    <Link href="/docs/storage-share/lxc-nfs-server" className="text-blue-700 hover:underline">{chunks}</Link>
  )
  const clientLink = (chunks: React.ReactNode) => (
    <Link href="/docs/storage-share/lxc-samba-client" className="text-blue-600 hover:underline">{chunks}</Link>
  )

  return (
    <div>
      <DocHeader
        title={t("header.title")}
        description={t("header.description")}
        section={t("header.section")}
        estimatedMinutes={12}
        scriptPath="share/samba_lxc_server.sh"
      />

      <Callout variant="warning" title={t("privReq.title")}>
        {t.rich("privReq.body", { code, strong })}
      </Callout>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("what.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("what.body", { code })}
      </p>

      <DataFlowDiagram
        nodes={[
          { label: t("what.diagramServerLabel"), detail: t("what.diagramServerDetail"), variant: "source" },
          { label: t("what.diagramClientLabel"), detail: t("what.diagramClientDetail"), variant: "target" },
        ]}
        arrowLabel={t("what.diagramArrow")}
        bidirectional
        command={`# /etc/samba/smb.conf  —  block written by ProxMenux:
[<share-name>]
    path = /mnt/data
    valid users = <username>
    force group = sharedfiles
    read only = no
    create mask = 0664
    directory mask = 2775`}
      />

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("perms.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("perms.body", { code, strong })}
      </p>

      <div className="overflow-x-auto my-6 rounded-md border border-gray-200">
        <table className="min-w-full text-sm">
          <thead className="bg-gray-50 text-left text-gray-700">
            <tr>
              <th className="px-4 py-2 font-semibold align-top">{t("perms.headerType")}</th>
              <th className="px-4 py-2 font-semibold align-top">{t("perms.headerAction")}</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-200 text-gray-800 align-top">
            <tr>
              <td className="px-4 py-3">
                <div className="font-semibold whitespace-nowrap">{t("perms.bindType")}</div>
                <div className="text-xs text-gray-600 mt-1">{t.rich("perms.bindTypeSubRich", { code })}</div>
              </td>
              <td className="px-4 py-3">{t.rich("perms.bindActionRich", { code })}</td>
            </tr>
            <tr>
              <td className="px-4 py-3">
                <div className="font-semibold whitespace-nowrap">{t("perms.localType")}</div>
                <div className="text-xs text-gray-600 mt-1">{t("perms.localTypeSub")}</div>
              </td>
              <td className="px-4 py-3">{t.rich("perms.localActionRich", { code })}</td>
            </tr>
          </tbody>
        </table>
      </div>

      <Callout variant="warning" title={t("perms.gidTitle")}>
        {t.rich("perms.gidBody", { strong, code, nfsLink })}
      </Callout>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("opening.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("opening.body", { strong })}
      </p>

      <Image
        src="/share/lxc-samba-server-menu.png"
        alt={t("opening.imageAlt")}
        width={900}
        height={500}
        className="rounded shadow-lg my-6"
      />

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("howRuns.heading")}</h2>

      <pre className="bg-gray-100 text-gray-800 p-4 rounded-md overflow-x-auto text-sm my-4 border border-gray-200 leading-snug">
{`┌─────────────────────────────────────────────┐
│  PHASE 1 — Pick CT, folder, user, options   │
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
      ├─ Auto: choose from /mnt/* in the CT
      └─ Manual: enter any absolute path
         (offers to mkdir -p if missing)
                   │
                   ▼
      Samba install check
      ├─ Already installed?
      │    └─ Detect existing user via pdbedit -L
      └─ First time?
         ├─ apt-get install samba samba-common-bin acl
         ├─ Ask username (default: "proxmenux")
         ├─ Ask password (twice — must match)
         ├─ adduser <username> (no password)
         └─ smbpasswd -a <username>
                   │
                   ▼
      Permission setup (2 paths)
      ├─ Bind-mount detected
      │     groupadd -g 999 sharedfiles
      │     usermod -aG sharedfiles <user>
      │     chown root:sharedfiles + chmod 2775
      │     setfacl fallback if write fails
      └─ Local folder
            chown -R <user>:<user>
            chmod -R 755
            setfacl fallback if needed
                   │
                   ▼
      Share permissions (3 modes)
      ├─ rw — read-write block (default)
      ├─ ro — read-only block
      └─ custom — your own directives
                   │
   ┌──────── Cancel   OR   Confirm ────┐
   ▼                                   ▼
Exit, nothing        ┌─────────────────┴─────────────────┐
was changed          │  PHASE 2 — Write smb.conf + apply  │
                     └─────────────────┬─────────────────┘
                                       ▼
                       If [share-name] already in smb.conf:
                       └─ ask "update?", remove + replace
                          (sed deletes from [name] to next blank)
                       Else:
                       └─ append the new block
                                       ▼
                       systemctl restart smbd.service
                                       ▼
                       Print connection details:
                       • Server IP (hostname -I)
                       • Share name + path
                       • Username
                       • Sample mount commands`}
      </pre>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("modes.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("modes.intro", { code })}
      </p>

      <div className="overflow-x-auto mb-4 rounded-md border border-gray-200">
        <table className="min-w-full text-sm">
          <thead className="bg-gray-50 text-left text-gray-700">
            <tr>
              <th className="px-4 py-2 font-semibold">{t("modes.headerMode")}</th>
              <th className="px-4 py-2 font-semibold">{t.rich("modes.headerBlock", { code })}</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-200 text-gray-800 align-top">
            <tr>
              <td className="px-4 py-3 font-semibold whitespace-nowrap">{t("modes.rwMode")}</td>
              <td className="px-4 py-3">
                <pre className="text-xs font-mono">{`read only = no
writable = yes
browseable = yes
guest ok = no
create mask = 0664
directory mask = 2775
force create mode = 0664
force directory mode = 2775`}</pre>
              </td>
            </tr>
            <tr>
              <td className="px-4 py-3 font-semibold whitespace-nowrap">{t("modes.roMode")}</td>
              <td className="px-4 py-3">
                <pre className="text-xs font-mono">{`read only = yes
writable = no
browseable = yes
guest ok = no`}</pre>
              </td>
            </tr>
            <tr>
              <td className="px-4 py-3 font-semibold">{t("modes.customMode")}</td>
              <td className="px-4 py-3">
                {t.rich("modes.customBodyRich", { code })}
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("manual.heading")}</h2>
      <p className="mb-3 text-gray-800 leading-relaxed">
        {t.rich("manual.body", { strong, code })}
      </p>
      <CopyableCode code={`# 1. install Samba (one-time)
apt-get update
apt-get install -y samba samba-common-bin acl

# 2. create a Samba user (system + smbpasswd)
adduser --disabled-password --gecos "" proxmenux
echo -e "P4ssw0rd\\nP4ssw0rd" | smbpasswd -a proxmenux

# 3. for a bind-mounted folder: shared group + SGID
mkdir -p /mnt/data
groupadd -g 999 sharedfiles 2>/dev/null || true
usermod -aG sharedfiles proxmenux
chown root:sharedfiles /mnt/data
chmod 2775             /mnt/data
# fallback if user can't write:
# setfacl -R -m u:proxmenux:rwx /mnt/data

# 4. write the share block
cat >> /etc/samba/smb.conf <<'EOF'

[data]
    path = /mnt/data
    valid users = proxmenux
    force group = sharedfiles
    read only = no
    writable = yes
    browseable = yes
    guest ok = no
    create mask = 0664
    directory mask = 2775
    force create mode = 0664
    force directory mode = 2775
    veto files = /lost+found/
EOF

# 5. apply
systemctl restart smbd
testparm -s | grep -A6 '^\\[data\\]'`} />

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("connect.heading")}</h2>

      <div className="overflow-x-auto mb-4 rounded-md border border-gray-200">
        <table className="min-w-full text-sm">
          <thead className="bg-gray-50 text-left text-gray-700">
            <tr>
              <th className="px-4 py-2 font-semibold">{t("connect.headerOs")}</th>
              <th className="px-4 py-2 font-semibold">{t("connect.headerHow")}</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-200 text-gray-800 align-top">
            <tr>
              <td className="px-4 py-3 font-semibold">{t("connect.windowsOs")}</td>
              <td className="px-4 py-3">{t.rich("connect.windowsHowRich", { code, em })}</td>
            </tr>
            <tr>
              <td className="px-4 py-3 font-semibold">{t("connect.macosOs")}</td>
              <td className="px-4 py-3">{t.rich("connect.macosHowRich", { code, em })}</td>
            </tr>
            <tr>
              <td className="px-4 py-3 font-semibold">{t("connect.linuxOs")}</td>
              <td className="px-4 py-3">{t.rich("connect.linuxHowRich", { code, clientLink })}</td>
            </tr>
          </tbody>
        </table>
      </div>

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

      <Callout variant="troubleshoot" title={t("troubleshoot.noShareTitle")}>
        {t.rich("troubleshoot.noShareBody", { code })}
      </Callout>

      <Callout variant="troubleshoot" title={t("troubleshoot.authTitle")}>
        {t.rich("troubleshoot.authBody", { em, code })}
      </Callout>

      <Callout variant="troubleshoot" title={t("troubleshoot.groupTitle")}>
        {t.rich("troubleshoot.groupBody", { code })}
      </Callout>

      <Callout variant="troubleshoot" title={t("troubleshoot.bothTitle")}>
        {t.rich("troubleshoot.bothBody", { code })}
        <pre className="mt-2 p-2 rounded bg-white/50 text-xs overflow-x-auto"><code>groupmod -g 101000 sharedfiles
chgrp -R sharedfiles /mnt/&lt;your-share&gt;</code></pre>
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
