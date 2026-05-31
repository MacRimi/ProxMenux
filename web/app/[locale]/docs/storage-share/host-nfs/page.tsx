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
  const t = await getTranslations({ locale, namespace: "docs.storageShare.hostNfs.meta" })
  return {
    title: t("title"),
    description: t("description"),
    openGraph: {
      title: t("ogTitle"),
      description: t("ogDescription"),
      type: "article",
      url: "https://macrimi.github.io/ProxMenux/docs/storage-share/host-nfs",
    },
  }
}

type StringItem = string
type ModesRow = { method: string; mount?: string; mountRich?: string; ui: string; useCase?: string; useCaseRich?: string }
type ContentRow = { type: string; allows?: string; allowsRich?: string }
type RelatedItem = { href: string; label: string; tail?: string; tailRich?: string }

export default async function HostNfsPage({
  params,
}: {
  params: Promise<{ locale: string }>
}) {
  const { locale } = await params
  setRequestLocale(locale)
  const t = await getTranslations({ locale, namespace: "docs.storageShare.hostNfs" })

  const messages = (await getMessages({ locale })) as unknown as {
    docs: { storageShare: { hostNfs: {
      modes: { rows: ModesRow[] }
      pvesmBranch: { items: StringItem[]; rows: ContentRow[] }
      fstabBranch: { items: StringItem[]; applies: StringItem[] }
      related: { items: RelatedItem[] }
    } } }
  }
  const modesRows = messages.docs.storageShare.hostNfs.modes.rows
  const pvesmItems = messages.docs.storageShare.hostNfs.pvesmBranch.items
  const contentRows = messages.docs.storageShare.hostNfs.pvesmBranch.rows
  const fstabItems = messages.docs.storageShare.hostNfs.fstabBranch.items
  const fstabAppliesItems = messages.docs.storageShare.hostNfs.fstabBranch.applies
  const relatedItems = messages.docs.storageShare.hostNfs.related.items

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
        estimatedMinutes={6}
        scriptPath="share/nfs_host.sh"
      />

      <Callout variant="info" title={t("intro.title")}>
        {t.rich("intro.body", { code, strong })}
      </Callout>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("opening.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("opening.body", { strong })}
      </p>

      <Image
        src="/share/host-nfs-menu.png"
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
      Dependency check
      └─ nfs-common present? (showmount)
         If missing → apt-get install nfs-common
                   │
                   ▼
      Server selection
      ├─ Auto-discover  (nmap -p 2049 on /24)
      └─ Manual         (type IP or hostname)
                   │
                   ▼
      Reachability + showmount validation
                   │
                   ▼
      Export selection
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
   ├─ content types              └─ mount options
   ▼                             ▼
   ┌─────────────────────────────────────────┐
   │  PHASE 2 — Apply (only marked methods)  │
   └──────────────────┬──────────────────────┘
                      ▼
   pvesm add nfs <id> ...    +  mkdir -p <path>
   (auto-mount at            mount -t nfs ...
    /mnt/pve/<id>)           append /etc/fstab
                             systemctl daemon-reload
                             chmod 1777 + setfacl
                             (best-effort, NFS server-side)
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
          <li key={idx}>{t.rich(`pvesmBranch.items.${idx}`, { strong, code })}</li>
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
                    ? t.rich(`pvesmBranch.rows.${idx}.allowsRich`, { em, code })
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

      <p className="mb-4 mt-4 text-gray-800 leading-relaxed">
        {t.rich("pvesmBranch.result", { code })}
      </p>

      <h2 className="text-2xl font-semibold mt-12 mb-4 text-gray-900">{t("fstabBranch.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("fstabBranch.intro", { em, code })}
      </p>

      <ol className="list-decimal pl-6 mb-4 text-gray-800 leading-relaxed space-y-2">
        {fstabItems.map((_, idx) => (
          <li key={idx}>{t.rich(`fstabBranch.items.${idx}`, { strong, em, code })}</li>
        ))}
      </ol>

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
      <CopyableCode code={`apt-get install -y nfs-common    # one-time: NFS client tools
pvesm add nfs mynfs \\
  --server 10.0.0.50 \\
  --export /export/proxmox \\
  --content import,backup,iso

pvesm status mynfs                # verify it's active
ls -la /mnt/pve/mynfs              # Proxmox auto-mounts here`} />

      <p className="mb-3 mt-6 text-gray-800 leading-relaxed">{t("manual.fstabIntro")}</p>
      <CopyableCode code={`apt-get install -y nfs-common    # one-time

mkdir -p /mnt/data
mount -t nfs -o "rw,hard,nofail,_netdev,rsize=131072,wsize=131072,timeo=600,retrans=2" \\
      10.0.0.50:/export/proxmox /mnt/data

# Persist
echo "10.0.0.50:/export/proxmox /mnt/data nfs rw,hard,nofail,_netdev,rsize=131072,wsize=131072,timeo=600,retrans=2 0 0" \\
  >> /etc/fstab
systemctl daemon-reload

# Best-effort open perms for LXC bind-mount writes (server permitting)
chmod 1777 /mnt/data 2>/dev/null || true
setfacl -m o::rwx /mnt/data 2>/dev/null || true

# Bind into an unprivileged LXC (host-side perms only — no changes inside CT)
pct set <ctid> -mp0 /mnt/data,mp=/mnt/data,shared=1,backup=0
pct reboot <ctid>`} />

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("view.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">{t.rich("view.body", { code, strong })}</p>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("remove.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">{t.rich("remove.body", { code, strong })}</p>

      <Callout variant="warning" title={t("remove.warnTitle")}>
        {t("remove.warnBody")}
      </Callout>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("test.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">{t.rich("test.body", { code, em })}</p>

      <h2 className="text-2xl font-semibold mt-12 mb-4 text-gray-900">{t("troubleshoot.heading")}</h2>

      <Callout variant="troubleshoot" title={t("troubleshoot.noServersTitle")}>
        {t.rich("troubleshoot.noServersBody", { code, em })}
      </Callout>

      <Callout variant="troubleshoot" title={t("troubleshoot.portTitle")}>
        {t.rich("troubleshoot.portBody", { code })}
      </Callout>

      <Callout variant="troubleshoot" title={t("troubleshoot.showmountTitle")}>
        {t.rich("troubleshoot.showmountBody", { code })}
      </Callout>

      <Callout variant="troubleshoot" title={t("troubleshoot.inactiveTitle")}>
        {t.rich("troubleshoot.inactiveBody", { em, code })}
      </Callout>

      <Callout variant="troubleshoot" title={t("troubleshoot.lxcNoWriteTitle")}>
        {t.rich("troubleshoot.lxcNoWriteBody", { code, strong })}
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
