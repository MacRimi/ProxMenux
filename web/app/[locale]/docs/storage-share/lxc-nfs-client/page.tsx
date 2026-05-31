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
  const t = await getTranslations({ locale, namespace: "docs.storageShare.lxcNfsClient.meta" })
  return {
    title: t("title"),
    description: t("description"),
    openGraph: {
      title: t("ogTitle"),
      description: t("ogDescription"),
      type: "article",
      url: "https://macrimi.github.io/ProxMenux/docs/storage-share/lxc-nfs-client",
    },
  }
}

type FlagRow = { flag: string; effect?: string; effectRich?: string }
type StringItem = string
type RelatedItem = { href: string; label: string; tail?: string; tailRich?: string }

export default async function LxcNfsClientPage({
  params,
}: {
  params: Promise<{ locale: string }>
}) {
  const { locale } = await params
  setRequestLocale(locale)
  const t = await getTranslations({ locale, namespace: "docs.storageShare.lxcNfsClient" })

  const messages = (await getMessages({ locale })) as unknown as {
    docs: { storageShare: { lxcNfsClient: {
      fstabFlags: { rows: FlagRow[] }
      troubleshoot: { aptItems: StringItem[]; squashItems: StringItem[] }
      related: { items: RelatedItem[] }
    } } }
  }
  const flagRows = messages.docs.storageShare.lxcNfsClient.fstabFlags.rows
  const aptItems = messages.docs.storageShare.lxcNfsClient.troubleshoot.aptItems
  const squashItems = messages.docs.storageShare.lxcNfsClient.troubleshoot.squashItems
  const relatedItems = messages.docs.storageShare.lxcNfsClient.related.items

  const code = (chunks: React.ReactNode) => <code>{chunks}</code>
  const strong = (chunks: React.ReactNode) => <strong>{chunks}</strong>
  const em = (chunks: React.ReactNode) => <em>{chunks}</em>
  const hostNfsLink = (chunks: React.ReactNode) => (
    <Link href="/docs/storage-share/host-nfs" className="text-blue-700 hover:underline">{chunks}</Link>
  )
  const mountLink = (chunks: React.ReactNode) => (
    <Link href="/docs/storage-share/lxc-mount-points" className="text-blue-700 hover:underline">{chunks}</Link>
  )
  const importLink = (chunks: React.ReactNode) => (
    <Link href="/docs/disk-manager/import-disk-lxc" className="text-blue-700 hover:underline">{chunks}</Link>
  )

  return (
    <div>
      <DocHeader
        title={t("header.title")}
        description={t("header.description")}
        section={t("header.section")}
        estimatedMinutes={8}
        scriptPath="share/nfs_client.sh"
      />

      <Callout variant="warning" title={t("privReq.title")}>
        {t.rich("privReq.body", { code, strong, hostNfsLink, mountLink })}
      </Callout>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("what.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("what.body", { em, strong, code })}
      </p>

      <DataFlowDiagram
        nodes={[
          { label: t("what.diagramServerLabel"), detail: t("what.diagramServerDetail"), variant: "source" },
          { label: t("what.diagramHostLabel"), detail: t("what.diagramHostDetail"), variant: "bridge" },
          { label: t("what.diagramCtLabel"), detail: t("what.diagramCtDetail"), variant: "target" },
        ]}
        arrowLabel={t("what.diagramArrow")}
        command={`# Inside the CT — what the script writes:
pct exec <ctid> -- mount -t nfs -o rw,hard,rsize=…,wsize=… \\
                         <server>:/export/data /mnt/data

# Persistent (added to /etc/fstab inside the CT):
<server>:/export/data  /mnt/data  nfs  <opts>,_netdev,x-systemd.automount,noauto  0 0`}
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
        src="/share/lxc-nfs-client-menu.png"
        alt={t("opening.imageAlt")}
        width={900}
        height={500}
        className="rounded shadow-lg my-6"
      />

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("howRuns.heading")}</h2>

      <pre className="bg-gray-100 text-gray-800 p-4 rounded-md overflow-x-auto text-sm my-4 border border-gray-200 leading-snug">
{`┌─────────────────────────────────────────────┐
│  PHASE 1 — Pick CT, server, export, options │
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
      Install NFS client packages (in CT)
      └─ pct exec apt-get install -y nfs-common
         (skipped if nfs-common is already installed)
         Verifies: showmount + mount.nfs both present
                   │
                   ▼
      Server selection
      ├─ Auto-discover (nmap from HOST on /24,
      │    port 2049, then showmount -e per result)
      └─ Manual: type IP or hostname
                   │
                   ▼
      Reachability validation chain (from inside CT)
      ├─ pct exec ping -c 1 -W 3 <server> ── fail → abort
      ├─ pct exec nc -z -w 3 <server> 2049 ── fail → abort
      └─ pct exec showmount -e <server>      ── fail → abort
                   │
                   ▼
      Export selection
      ├─ Server returns exports → checklist with ACL
      └─ No exports / blocked  → manual input
                   │
                   ▼
      Validate the chosen export still exists
      (re-runs showmount -e | grep <export>)
                   │
                   ▼
      Mount-point picker (3 options)
      ├─ 1. Create new folder in /mnt
      │      (default: nfs_<server>_<export-basename>)
      ├─ 2. Select existing folder in /mnt
      │      (warns if folder is not empty —
      │       mounting hides existing files)
      └─ 3. Enter custom path
                   │
                   ▼
      Mount-options preset (3 options)
      ├─ 1. Read/write
      │      rw,hard,rsize=1048576,wsize=1048576,
      │      timeo=600,retrans=2
      ├─ 2. Read-only
      │      ro,hard,rsize=1048576,wsize=1048576,
      │      timeo=600,retrans=2
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
                       pct exec mount -t nfs \\
                            -o <chosen options> \\
                            <server>:<export> <mount-point>
                                       ▼
                       Smoke test: write a 0-byte file
                       (.test_write) and delete it
                       └─ no write access → "read-only"
                                       ▼
                       If "permanent" was chosen:
                       └─ Append to /etc/fstab inside CT:
                            <srv>:<exp>  <mp>  nfs \\
                              <opts>,_netdev,
                              x-systemd.automount,noauto  0 0
                       (any prior entry for this MP is removed first)
                                       ▼
                       Print summary (server / export / mp /
                       options / permanent yes-no)`}
      </pre>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("fstabFlags.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("fstabFlags.intro", { code })}
      </p>

      <div className="overflow-x-auto mb-4 rounded-md border border-gray-200">
        <table className="min-w-full text-sm">
          <thead className="bg-gray-50 text-left text-gray-700">
            <tr>
              <th className="px-4 py-2 font-semibold">{t("fstabFlags.headerFlag")}</th>
              <th className="px-4 py-2 font-semibold">{t("fstabFlags.headerEffect")}</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-200 text-gray-800">
            {flagRows.map((row, idx) => (
              <tr key={row.flag}>
                <td className="px-4 py-2 font-mono">{row.flag}</td>
                <td className="px-4 py-2">
                  {row.effectRich ? t.rich(`fstabFlags.rows.${idx}.effectRich`, { code }) : row.effect}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <Callout variant="info" title={t("fstabFlags.netEffectTitle")}>
        {t.rich("fstabFlags.netEffectBody", { em })}
      </Callout>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("manual.heading")}</h2>
      <p className="mb-3 text-gray-800 leading-relaxed">
        {t.rich("manual.body", { strong, code })}
      </p>
      <CopyableCode code={`# 1. install the NFS client (one-time)
apt-get update
apt-get install -y nfs-common

# 2. test reachability
ping -c 1 -W 3 10.0.0.50
nc   -z -w 3 10.0.0.50 2049
showmount -e 10.0.0.50

# 3. mount it (one-shot)
mkdir -p /mnt/data
mount -t nfs -o "rw,hard,rsize=1048576,wsize=1048576,timeo=600,retrans=2" \\
      10.0.0.50:/export/data /mnt/data

# 4. make it permanent (safe boot defaults)
cat >> /etc/fstab <<EOF
10.0.0.50:/export/data  /mnt/data  nfs  rw,hard,rsize=1048576,wsize=1048576,timeo=600,retrans=2,_netdev,x-systemd.automount,noauto  0 0
EOF
systemctl daemon-reload`} />

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("view.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">{t.rich("view.body", { code })}</p>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("unmount.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("unmount.body", { strong, em, code })}
      </p>

      <Callout variant="warning" title={t("unmount.warnTitle")}>
        {t.rich("unmount.warnBody", { code, em })}
      </Callout>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("test.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">{t.rich("test.body", { code })}</p>

      <h2 className="text-2xl font-semibold mt-12 mb-4 text-gray-900">{t("troubleshoot.heading")}</h2>

      <Callout variant="troubleshoot" title={t("troubleshoot.privTitle")}>
        {t.rich("troubleshoot.privBody", { code, importLink })}
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

      <Callout variant="troubleshoot" title={t("troubleshoot.portTitle")}>
        {t.rich("troubleshoot.portBody", { code })}
      </Callout>

      <Callout variant="troubleshoot" title={t("troubleshoot.bootTitle")}>
        {t.rich("troubleshoot.bootBody", { code })}
      </Callout>

      <Callout variant="troubleshoot" title={t("troubleshoot.squashTitle")}>
        {t.rich("troubleshoot.squashIntro", { code })}
        <ul className="mt-2 list-disc list-inside space-y-1">
          {squashItems.map((_, idx) => (
            <li key={idx}>{t.rich(`troubleshoot.squashItems.${idx}`, { code })}</li>
          ))}
        </ul>
        {t("troubleshoot.squashOutro")}
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
