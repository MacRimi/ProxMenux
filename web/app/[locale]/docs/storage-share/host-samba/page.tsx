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
  const t = await getTranslations({ locale, namespace: "docs.storageShare.hostSamba.meta" })
  return {
    title: t("title"),
    description: t("description"),
    openGraph: {
      title: t("ogTitle"),
      description: t("ogDescription"),
      type: "article",
      url: "https://macrimi.github.io/ProxMenux/docs/storage-share/host-samba",
    },
  }
}

type StringItem = string
type ModesRow = { method: string; mount?: string; mountRich?: string; ui: string; useCase?: string; useCaseRich?: string }
type ContentRow = { type: string; allows?: string; allowsRich?: string }
type RelatedItem = { href: string; label: string; tail?: string; tailRich?: string }

export default async function HostSambaPage({
  params,
}: {
  params: Promise<{ locale: string }>
}) {
  const { locale } = await params
  setRequestLocale(locale)
  const t = await getTranslations({ locale, namespace: "docs.storageShare.hostSamba" })

  const messages = (await getMessages({ locale })) as unknown as {
    docs: { storageShare: { hostSamba: {
      modes: { rows: ModesRow[] }
      pvesmBranch: { items: StringItem[]; rows: ContentRow[] }
      fstabBranch: { items: StringItem[]; applies: StringItem[] }
      related: { items: RelatedItem[] }
    } } }
  }
  const modesRows = messages.docs.storageShare.hostSamba.modes.rows
  const pvesmItems = messages.docs.storageShare.hostSamba.pvesmBranch.items
  const contentRows = messages.docs.storageShare.hostSamba.pvesmBranch.rows
  const fstabItems = messages.docs.storageShare.hostSamba.fstabBranch.items
  const fstabAppliesItems = messages.docs.storageShare.hostSamba.fstabBranch.applies
  const relatedItems = messages.docs.storageShare.hostSamba.related.items

  const code = (chunks: React.ReactNode) => <code>{chunks}</code>
  const strong = (chunks: React.ReactNode) => <strong>{chunks}</strong>
  const em = (chunks: React.ReactNode) => <em>{chunks}</em>
  const mountLink = (chunks: React.ReactNode) => (
    <Link href="/docs/storage-share/lxc-mount-points" className="text-blue-700 hover:underline">{chunks}</Link>
  )

  return (
    <div>
      <DocHeader
        title={t("header.title")}
        description={t("header.description")}
        section={t("header.section")}
        estimatedMinutes={7}
        scriptPath="share/samba_host.sh"
      />

      <Callout variant="info" title={t("intro.title")}>
        {t.rich("intro.body", { code, strong })}
      </Callout>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("opening.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("opening.body", { strong })}
      </p>

      <Image
        src="/share/host-samba-menu.png"
        alt={t("opening.imageAlt")}
        width={900}
        height={500}
        className="rounded shadow-lg my-6"
      />

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("howRuns.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("howRuns.body", { code })}
      </p>

      <pre className="bg-gray-100 text-gray-800 p-4 rounded-md overflow-x-auto text-sm my-4 border border-gray-200 leading-snug">
{`┌─────────────────────────────────────────────┐
│  PHASE 1 — Discover, validate, choose       │
│  (nothing touched yet)                      │
└──────────────────┬──────────────────────────┘
                   ▼
      Server discovery (nmap 139/445 + nmblookup)
                   │
                   ▼
      Authentication (User or Guest)
                   │
                   ▼
      Share selection (smbclient -L)
                   │
                   ▼
      ╔═════════════════════════════════════╗
      ║   MOUNT METHOD PICKER  (checklist)  ║
      ║   [ ] As Proxmox storage  (pvesm)   ║
      ║   [ ] As host fstab mount only      ║
      ║   (mark one or both — re-prompts    ║
      ║    if you press OK without marks)   ║
      ╚════════════════╤════════════════════╝
                       │
        ┌──────────────┴──────────────┐
        ▼                             ▼
   pvesm branch                  fstab branch
   ├─ storage ID                 ├─ mount path
   ├─ content types              ├─ mount options
                                 └─ (User) write
                                     /etc/samba/credentials/...cred
                                     (mode 0600)
   ▼                             ▼
   ┌─────────────────────────────────────────┐
   │  PHASE 2 — Apply (only marked methods)  │
   └──────────────────┬──────────────────────┘
                      ▼
   pvesm add cifs <id> ...    +  mkdir -p <path>
   (auto-mount at            mount -t cifs ...
    /mnt/pve/<id> with        (uid=0,gid=0,
    default options)           file_mode=0777,
                               dir_mode=0777)
                             append /etc/fstab
                             systemctl daemon-reload
                      ▼
              Summary printed`}
      </pre>

      <h2 className="text-2xl font-semibold mt-12 mb-4 text-gray-900">{t("modes.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">{t("modes.intro")}</p>

      <div className="overflow-x-auto mb-4 rounded-md border border-gray-200">
        <table className="min-w-full text-sm">
          <thead className="bg-gray-50 text-left text-gray-700">
            <tr>
              <th className="px-4 py-2 font-semibold">{t("modes.headerMethod")}</th>
              <th className="px-4 py-2 font-semibold">{t("modes.headerMount")}</th>
              <th className="px-4 py-2 font-semibold">{t("modes.headerUi")}</th>
              <th className="px-4 py-2 font-semibold">{t("modes.headerUseCase")}</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-200 text-gray-800 align-top">
            {modesRows.map((row, idx) => (
              <tr key={idx}>
                <td className="px-4 py-2">{t.rich(`modes.rows.${idx}.method`, { strong })}</td>
                <td className="px-4 py-2">
                  {row.mountRich ? t.rich(`modes.rows.${idx}.mountRich`, { code }) : row.mount}
                </td>
                <td className="px-4 py-2">{row.ui}</td>
                <td className="px-4 py-2">
                  {row.useCaseRich ? t.rich(`modes.rows.${idx}.useCaseRich`, { em }) : row.useCase}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <Callout variant="info" title={t("modes.bothTitle")}>
        {t.rich("modes.bothBody", { code })}
      </Callout>

      <h2 className="text-2xl font-semibold mt-12 mb-4 text-gray-900">{t("pvesmBranch.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("pvesmBranch.intro", { em })}
      </p>

      <ol className="list-decimal pl-6 mb-4 text-gray-800 leading-relaxed space-y-2">
        {pvesmItems.map((_, idx) => (
          <li key={idx}>{t.rich(`pvesmBranch.items.${idx}`, { strong, em, code })}</li>
        ))}
      </ol>

      <div className="overflow-x-auto mb-4 rounded-md border border-gray-200">
        <table className="min-w-full text-sm">
          <thead className="bg-gray-50 text-left text-gray-700">
            <tr>
              <th className="px-4 py-2 font-semibold">{t("pvesmBranch.headerType")}</th>
              <th className="px-4 py-2 font-semibold">{t("pvesmBranch.headerAllows")}</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-200 text-gray-800">
            {contentRows.map((row, idx) => (
              <tr key={row.type}>
                <td className="px-4 py-2 font-mono">{row.type}</td>
                <td className="px-4 py-2">
                  {row.allowsRich
                    ? t.rich(`pvesmBranch.rows.${idx}.allowsRich`, { code, strong })
                    : row.allows}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <Callout variant="warning" title={t("pvesmBranch.warnTitle")}>
        {t.rich("pvesmBranch.warnBody", { code })}
      </Callout>

      <Callout variant="info" title={t("pvesmBranch.credsTitle")}>
        {t.rich("pvesmBranch.credsBody", { code })}
      </Callout>

      <h2 className="text-2xl font-semibold mt-12 mb-4 text-gray-900">{t("fstabBranch.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("fstabBranch.intro", { em, code })}
      </p>

      <ol className="list-decimal pl-6 mb-4 text-gray-800 leading-relaxed space-y-2">
        {fstabItems.map((_, idx) => (
          <li key={idx}>{t.rich(`fstabBranch.items.${idx}`, { strong, em, code })}</li>
        ))}
      </ol>

      <Callout variant="info" title={t("fstabBranch.credsTitle")}>
        {t.rich("fstabBranch.credsBody", { code })}
      </Callout>

      <p className="mb-3 text-gray-800 leading-relaxed">{t("fstabBranch.appliesIntro")}</p>
      <ul className="list-disc pl-6 mb-4 text-gray-800 leading-relaxed space-y-1">
        {fstabAppliesItems.map((_, idx) => (
          <li key={idx}>{t.rich(`fstabBranch.applies.${idx}`, { code })}</li>
        ))}
      </ul>

      <Callout variant="info" title={t("fstabBranch.lxcTitle")}>
        {t.rich("fstabBranch.lxcBody", { code, strong, mountLink })}
      </Callout>

      <Callout variant="warning" title={t("fstabBranch.noUiTitle")}>
        {t.rich("fstabBranch.noUiBody", { em })}
      </Callout>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("manual.heading")}</h2>

      <p className="mb-3 text-gray-800 leading-relaxed">{t("manual.pvesmIntro")}</p>
      <CopyableCode code={`apt-get install -y cifs-utils smbclient    # one-time: SMB client tools

# with user authentication
pvesm add cifs mycifs \\
  --server 10.0.0.50 \\
  --share proxmox \\
  --username backup_user \\
  --password 's3cret' \\
  --content backup,iso

# guest access (no credentials)
pvesm add cifs mycifs-guest \\
  --server 10.0.0.50 \\
  --share public \\
  --content iso,vztmpl

pvesm status mycifs                         # verify it's active
ls -la /mnt/pve/mycifs                       # Proxmox auto-mounts here`} />

      <p className="mb-3 mt-6 text-gray-800 leading-relaxed">{t("manual.fstabUserIntro")}</p>
      <CopyableCode code={`# 1. credentials file (root-only)
mkdir -p /etc/samba/credentials && chmod 0700 /etc/samba/credentials
cat > /etc/samba/credentials/nas01_share.cred <<'EOF'
username=admin
password=s3cret
EOF
chmod 0600 /etc/samba/credentials/nas01_share.cred

# 2. mount with open uid/gid/file_mode (for unpriv LXC bind-mounts)
mkdir -p /mnt/data
mount -t cifs //10.0.0.50/share /mnt/data \\
  -o "rw,uid=0,gid=0,file_mode=0777,dir_mode=0777,iocharset=utf8,nofail,_netdev,credentials=/etc/samba/credentials/nas01_share.cred"

# 3. persist
echo "//10.0.0.50/share /mnt/data cifs rw,uid=0,gid=0,file_mode=0777,dir_mode=0777,iocharset=utf8,nofail,_netdev,credentials=/etc/samba/credentials/nas01_share.cred 0 0" \\
  >> /etc/fstab
systemctl daemon-reload

# 4. bind into an unpriv LXC (no changes inside the CT)
pct set <ctid> -mp0 /mnt/data,mp=/mnt/data,shared=1,backup=0
pct reboot <ctid>`} />

      <p className="mb-3 mt-6 text-gray-800 leading-relaxed">{t("manual.fstabGuestIntro")}</p>
      <CopyableCode code={`mkdir -p /mnt/public
mount -t cifs //10.0.0.50/public /mnt/public \\
  -o "rw,uid=0,gid=0,file_mode=0777,dir_mode=0777,iocharset=utf8,nofail,_netdev,guest"

echo "//10.0.0.50/public /mnt/public cifs rw,uid=0,gid=0,file_mode=0777,dir_mode=0777,iocharset=utf8,nofail,_netdev,guest 0 0" \\
  >> /etc/fstab
systemctl daemon-reload`} />

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("view.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">{t.rich("view.body", { code, em, strong })}</p>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("remove.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">{t.rich("remove.body", { code, strong })}</p>

      <Callout variant="warning" title={t("remove.warnTitle")}>
        {t("remove.warnBody")}
      </Callout>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("test.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">{t.rich("test.body", { code })}</p>

      <h2 className="text-2xl font-semibold mt-12 mb-4 text-gray-900">{t("troubleshoot.heading")}</h2>

      <Callout variant="troubleshoot" title={t("troubleshoot.noServersTitle")}>
        {t.rich("troubleshoot.noServersBody", { code, em })}
      </Callout>

      <Callout variant="troubleshoot" title={t("troubleshoot.noSharesTitle")}>
        {t.rich("troubleshoot.noSharesBody", { code })}
      </Callout>

      <Callout variant="troubleshoot" title={t("troubleshoot.denyTitle")}>
        {t.rich("troubleshoot.denyBody", { code })}
      </Callout>

      <Callout variant="troubleshoot" title={t("troubleshoot.sleepTitle")}>
        {t.rich("troubleshoot.sleepBody", { code })}
      </Callout>

      <Callout variant="troubleshoot" title={t("troubleshoot.lxcNoWriteTitle")}>
        {t.rich("troubleshoot.lxcNoWriteBody", { code })}
      </Callout>

      <Callout variant="troubleshoot" title={t("troubleshoot.fstabBootTitle")}>
        {t.rich("troubleshoot.fstabBootBody", { code })}
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
