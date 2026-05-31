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
  const t = await getTranslations({ locale, namespace: "docs.storageShare.lxcSambaClient.meta" })
  return {
    title: t("title"),
    description: t("description"),
    openGraph: {
      title: t("ogTitle"),
      description: t("ogDescription"),
      type: "article",
      url: "https://macrimi.github.io/ProxMenux/docs/storage-share/lxc-samba-client",
    },
  }
}

type OptionRow = { option: string; effect: string }
type StringItem = string
type RelatedItem = { href: string; label: string; tail?: string; tailRich?: string }

export default async function LxcSambaClientPage({
  params,
}: {
  params: Promise<{ locale: string }>
}) {
  const { locale } = await params
  setRequestLocale(locale)
  const t = await getTranslations({ locale, namespace: "docs.storageShare.lxcSambaClient" })

  const messages = (await getMessages({ locale })) as unknown as {
    docs: { storageShare: { lxcSambaClient: {
      options: { rows: OptionRow[] }
      troubleshoot: { aptItems: StringItem[] }
      related: { items: RelatedItem[] }
    } } }
  }
  const optionRows = messages.docs.storageShare.lxcSambaClient.options.rows
  const aptItems = messages.docs.storageShare.lxcSambaClient.troubleshoot.aptItems
  const relatedItems = messages.docs.storageShare.lxcSambaClient.related.items

  const code = (chunks: React.ReactNode) => <code>{chunks}</code>
  const strong = (chunks: React.ReactNode) => <strong>{chunks}</strong>
  const em = (chunks: React.ReactNode) => <em>{chunks}</em>
  const hostSambaLink = (chunks: React.ReactNode) => (
    <Link href="/docs/storage-share/host-samba" className="text-blue-700 hover:underline">{chunks}</Link>
  )
  const mountLink = (chunks: React.ReactNode) => (
    <Link href="/docs/storage-share/lxc-mount-points" className="text-blue-700 hover:underline">{chunks}</Link>
  )

  return (
    <div>
      <DocHeader
        title={t("header.title")}
        description={t("header.description")}
        section={t("header.section")}
        estimatedMinutes={10}
        scriptPath="share/samba_client.sh"
      />

      <Callout variant="warning" title={t("privReq.title")}>
        {t.rich("privReq.body", { code, strong, hostSambaLink, mountLink })}
      </Callout>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("what.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">{t("what.body")}</p>

      <DataFlowDiagram
        nodes={[
          { label: t("what.diagramServerLabel"), detail: t("what.diagramServerDetail"), variant: "source" },
          { label: t("what.diagramHostLabel"), detail: t("what.diagramHostDetail"), variant: "bridge" },
          { label: t("what.diagramCtLabel"), detail: t("what.diagramCtDetail"), variant: "target" },
        ]}
        arrowLabel={t("what.diagramArrow")}
        command={`# Credentials stored in the CT (root:0600):
#   /etc/samba/credentials/<server>_<share>.cred

# What the script writes inside the CT:
pct exec <ctid> -- mount -t cifs //<server>/<share> /mnt/share \\
                         -o "rw,file_mode=0664,dir_mode=0775,iocharset=utf8,
                             credentials=/etc/samba/credentials/<srv>_<sh>.cred"`}
      />

      <Callout variant="info" title={t("what.twoWaysTitle")}>
        <ul className="mt-2 list-disc list-inside space-y-1">
          <li>{t.rich("what.twoWaysBind", { strong, mountLink })}</li>
          <li>{t.rich("what.twoWaysDirect", { strong })}</li>
        </ul>
      </Callout>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("opening.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("opening.body", { strong })}
      </p>

      <Image
        src="/share/lxc-samba-client-menu.png"
        alt={t("opening.imageAlt")}
        width={900}
        height={500}
        className="rounded shadow-lg my-6"
      />

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("howRuns.heading")}</h2>

      <pre className="bg-gray-100 text-gray-800 p-4 rounded-md overflow-x-auto text-sm my-4 border border-gray-200 leading-snug">
{`┌─────────────────────────────────────────────┐
│  PHASE 1 — Pick CT, server, auth, share     │
│  (nothing touched yet)                      │
└──────────────────┬──────────────────────────┘
                   ▼
      Privileged-CT gate (share-common.func)
      ├─ pct list — pick CT
      ├─ Auto-start if stopped
      └─ Reads /etc/pve/lxc/<ctid>.conf
         └─ unprivileged: 1  → abort with help message
                   │
                   ▼
      Install Samba client packages (in CT)
      └─ pct exec apt-get install -y \\
                   cifs-utils smbclient
         (skipped if already installed)
         Verifies: smbclient + mount.cifs both present
         Creates /etc/samba/credentials (mode 0700)
                   │
                   ▼
      Server selection (3 modes)
      ├─ Auto-discover (nmap from HOST on /24,
      │    ports 139/445, then nmblookup -A
      │    for NetBIOS names → "NETBIOS (ip)")
      ├─ Manual: type IP or hostname
      └─ Recent: parses /etc/fstab for previously
         used CIFS servers (one-click selection)
                   │
                   ▼
      Authentication (2 modes)
      ├─ User + password
      │   ├─ Username (whiptail inputbox)
      │   ├─ Password (passwordbox, hidden)
      │   ├─ Confirm password
      │   └─ ACTIVE VALIDATION against the server:
      │       creates a temp credentials file,
      │       runs smbclient -L with -A,
      │       distinguishes "guest fallback" from
      │       real auth success, retries on failure
      └─ Guest: validate guest access first
         (smbclient -L -N must succeed)
                   │
                   ▼
      Share selection
      ├─ Server returns shares → menu
      │   (filters out IPC$, ADMIN$, print$;
      │    for guest: only shares the user
      │    confirmed accessible during validation)
      └─ No shares / blocked → manual input
                   │
                   ▼
      Validate the chosen share still exists
                   │
                   ▼
      Mount-point picker (3 options)
      ├─ 1. Create new folder in /mnt
      │      (default: same name as the share)
      ├─ 2. Select existing folder in /mnt
      └─ 3. Enter custom path
                   │
                   ▼
      Mount-options preset (3 options)
      ├─ 1. Read/write
      │      rw,file_mode=0664,dir_mode=0775,
      │      iocharset=utf8
      ├─ 2. Read-only
      │      ro,file_mode=0444,dir_mode=0555,
      │      iocharset=utf8
      └─ 3. Custom — type your own option string
                   │
                   ▼
      Permanent mount? (yes/no)
      └─ yes → write entry to /etc/fstab
                   │
   ┌──────── Cancel   OR   Confirm ────┐
   ▼                                   ▼
Exit, nothing        ┌─────────────────┴─────────────────┐
was changed          │  PHASE 2 — Mount and persist       │
                     └─────────────────┬─────────────────┘
                                       ▼
                       Create mount point if missing
                       (pct exec mkdir -p <path>)
                                       ▼
                       If something is already mounted there,
                       offer to unmount first
                                       ▼
                       For user auth: write credentials file
                       /etc/samba/credentials/<srv>_<sh>.cred
                       (root:0600 inside the CT)
                                       ▼
                       pct exec mount -t cifs \\
                            //<server>/<share> <mp> \\
                            -o <opts>,credentials=<file>
                       (or  -o <opts>,guest  for guest)
                                       ▼
                       Smoke test: write a 0-byte file
                       and delete it (.test_write)
                       └─ no write access → "read-only"
                                       ▼
                       If "permanent" was chosen:
                       └─ Append to /etc/fstab inside CT:
                            //<srv>/<sh>  <mp>  cifs \\
                              <opts>,credentials=…,
                              _netdev,
                              x-systemd.automount,noauto  0 0
                       (any prior entry for this mp is removed first)
                                       ▼
                       Print summary (server / share / mp /
                       auth mode / permanent yes-no)`}
      </pre>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("creds.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("creds.body", { strong, code })}
      </p>

      <pre className="bg-gray-100 text-gray-800 p-4 rounded-md overflow-x-auto text-sm my-4 border border-gray-200 leading-snug">
{`Path:    /etc/samba/credentials/<server>_<share>.cred
Owner:   root
Mode:    0600

Content:
    username=<your-username>
    password=<your-password>

Reference in /etc/fstab:
    //<server>/<share>  /mnt/<path>  cifs  rw,...,
        credentials=/etc/samba/credentials/<server>_<share>.cred,
        _netdev,x-systemd.automount,noauto  0  0`}
      </pre>

      <Callout variant="info" title={t("creds.whyTitle")}>
        {t.rich("creds.whyBody", { code })}
      </Callout>

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
            {optionRows.map((row) => (
              <tr key={row.option}>
                <td className="px-4 py-2 font-mono">{row.option}</td>
                <td className="px-4 py-2">{row.effect}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <Callout variant="info" title={t("options.netEffectTitle")}>
        {t.rich("options.netEffectBody", { em })}
      </Callout>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("manual.heading")}</h2>
      <p className="mb-3 text-gray-800 leading-relaxed">
        {t.rich("manual.body", { strong, code })}
      </p>
      <CopyableCode code={`# 1. install the Samba client (one-time)
apt-get update
apt-get install -y cifs-utils smbclient

# 2. test reachability
ping -c 1 -W 3 10.0.0.50
nc   -z -w 3 10.0.0.50 445
smbclient -L 10.0.0.50 -U user

# 3. write the credentials file (root-only)
mkdir -p /etc/samba/credentials
chmod 700 /etc/samba/credentials
cat > /etc/samba/credentials/10.0.0.50_share.cred <<EOF
username=user
password=s3cret
EOF
chmod 600 /etc/samba/credentials/10.0.0.50_share.cred

# 4. mount it (one-shot)
mkdir -p /mnt/share
mount -t cifs //10.0.0.50/share /mnt/share \\
  -o "rw,file_mode=0664,dir_mode=0775,iocharset=utf8,credentials=/etc/samba/credentials/10.0.0.50_share.cred"

# 5. make it permanent (safe boot defaults)
cat >> /etc/fstab <<EOF
//10.0.0.50/share  /mnt/share  cifs  rw,file_mode=0664,dir_mode=0775,iocharset=utf8,credentials=/etc/samba/credentials/10.0.0.50_share.cred,_netdev,x-systemd.automount,noauto  0 0
EOF
systemctl daemon-reload`} />

      <p className="mb-3 mt-6 text-gray-800 leading-relaxed">{t("manual.guestIntro")}</p>
      <CopyableCode code={`mount -t cifs //10.0.0.50/public /mnt/public \\
  -o "rw,file_mode=0664,dir_mode=0775,iocharset=utf8,guest"

# fstab equivalent
echo "//10.0.0.50/public  /mnt/public  cifs  rw,file_mode=0664,dir_mode=0775,iocharset=utf8,guest,_netdev,x-systemd.automount,noauto  0 0" \\
     >> /etc/fstab`} />

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("view.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">{t.rich("view.body", { code })}</p>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("unmount.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("unmount.body", { strong, code })}
      </p>

      <Callout variant="warning" title={t("unmount.warnTitle")}>
        {t.rich("unmount.warnBody", { code, em })}
      </Callout>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("test.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">{t.rich("test.body", { code })}</p>

      <h2 className="text-2xl font-semibold mt-12 mb-4 text-gray-900">{t("troubleshoot.heading")}</h2>

      <Callout variant="troubleshoot" title={t("troubleshoot.privTitle")}>
        {t.rich("troubleshoot.privBody", { code })}
      </Callout>

      <Callout variant="troubleshoot" title={t("troubleshoot.aptTitle")}>
        {t.rich("troubleshoot.aptIntro", { code })}
        <ul className="mt-2 list-disc list-inside space-y-1">
          {aptItems.map((_, idx) => (
            <li key={idx}>{t.rich(`troubleshoot.aptItems.${idx}`, { code })}</li>
          ))}
        </ul>
        {t("troubleshoot.aptOutro")}
      </Callout>

      <Callout variant="troubleshoot" title={t("troubleshoot.guestFallbackTitle")}>
        {t("troubleshoot.guestFallbackBody")}
      </Callout>

      <Callout variant="troubleshoot" title={t("troubleshoot.denyTitle")}>
        {t.rich("troubleshoot.denyBody", { code })}
      </Callout>

      <Callout variant="troubleshoot" title={t("troubleshoot.utf8Title")}>
        {t.rich("troubleshoot.utf8Body", { code })}
      </Callout>

      <Callout variant="troubleshoot" title={t("troubleshoot.bootTitle")}>
        {t.rich("troubleshoot.bootBody", { code })}
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
