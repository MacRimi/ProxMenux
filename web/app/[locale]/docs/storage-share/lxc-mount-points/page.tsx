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
  const t = await getTranslations({ locale, namespace: "docs.storageShare.lxcMountPoints.meta" })
  return {
    title: t("title"),
    description: t("description"),
    openGraph: {
      title: t("ogTitle"),
      description: t("ogDescription"),
      type: "article",
      url: "https://macrimi.github.io/ProxMenux/docs/storage-share/lxc-mount-points",
    },
  }
}

type StringItem = string
type SourceRow = { source: string; where?: string; whereRich?: string; labelRich: string }
type StringList = string[]
type RelatedItem = {
  href: string
  label: string
  extraHref?: string
  extraLabel?: string
  joiner?: string
  tail?: string
  tailRich?: string
}

export default async function LxcMountPointsPage({
  params,
}: {
  params: Promise<{ locale: string }>
}) {
  const { locale } = await params
  setRequestLocale(locale)
  const t = await getTranslations({ locale, namespace: "docs.storageShare.lxcMountPoints" })

  const messages = (await getMessages({ locale })) as unknown as {
    docs: { storageShare: { lxcMountPoints: {
      bigPicture: { items: StringItem[] }
      sources: { rows: SourceRow[] }
      troubleshoot: { nfsItems: StringList }
      related: { items: RelatedItem[] }
    } } }
  }
  const bigPictureItems = messages.docs.storageShare.lxcMountPoints.bigPicture.items
  const sourceRows = messages.docs.storageShare.lxcMountPoints.sources.rows
  const nfsItems = messages.docs.storageShare.lxcMountPoints.troubleshoot.nfsItems
  const relatedItems = messages.docs.storageShare.lxcMountPoints.related.items

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
        scriptPath="share/lxc-mount-manager_minimal.sh"
      />

      <Callout variant="info" title={t("intro.title")}>
        {t("intro.body")}
      </Callout>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("bigPicture.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("bigPicture.intro", { code, em })}
      </p>

      <DataFlowDiagram
        nodes={[
          { label: t("bigPicture.sourceLabel"), detail: t("bigPicture.sourceDetail"), variant: "source" },
          { label: t("bigPicture.targetLabel"), detail: t("bigPicture.targetDetail"), variant: "target" },
        ]}
        arrowLabel={t("bigPicture.arrowLabel")}
        bidirectional
        command={`# What the script writes:
pct set <ctid> -mpN  /mnt/data, mp=/mnt/data, shared=1, backup=0`}
      />

      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("bigPicture.outro", { code })}
      </p>
      <ul className="list-disc pl-6 mb-4 text-gray-800 leading-relaxed space-y-1">
        {bigPictureItems.map((_, idx) => (
          <li key={idx}>{t.rich(`bigPicture.items.${idx}`, { code })}</li>
        ))}
      </ul>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("perms.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("perms.intro", { strong, em })}
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
                <div className="font-semibold whitespace-nowrap">{t("perms.localType")}</div>
                <div className="text-xs text-gray-600 mt-1 font-mono">{t("perms.localTypeSub")}</div>
              </td>
              <td className="px-4 py-3">{t.rich("perms.localActionRich", { code })}</td>
            </tr>
            <tr>
              <td className="px-4 py-3">
                <div className="font-semibold whitespace-nowrap">{t("perms.cifsType")}</div>
                <div className="text-xs text-gray-600 mt-1 font-mono">{t("perms.cifsTypeSub")}</div>
              </td>
              <td className="px-4 py-3">{t.rich("perms.cifsActionRich", { code })}</td>
            </tr>
            <tr>
              <td className="px-4 py-3">
                <div className="font-semibold whitespace-nowrap">{t("perms.nfsType")}</div>
                <div className="text-xs text-gray-600 mt-1 font-mono">{t("perms.nfsTypeSub")}</div>
              </td>
              <td className="px-4 py-3">{t.rich("perms.nfsActionRich", { code })}</td>
            </tr>
          </tbody>
        </table>
      </div>

      <Callout variant="info" title={t("perms.privTitle")}>
        {t("perms.privBody")}
      </Callout>

      <Callout variant="warning" title={t("perms.noCtTitle")}>
        {t.rich("perms.noCtBody", { strong, code })}
      </Callout>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("writes.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("writes.intro", { code, strong })}
      </p>

      <CopyableCode
        code={`# /etc/pve/lxc/545.conf  — single line added by the script
mp0: /mnt/NAS/hdd_cache,mp=/mnt/NAS/hdd_cache,shared=1,backup=0`}
        className="my-4"
      />

      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("writes.outro", { em })}
      </p>

      <h3 className="text-lg font-semibold mt-6 mb-2 text-gray-900">{t("writes.twoWaysHeading")}</h3>

      <div className="overflow-x-auto my-4 rounded-md border border-gray-200">
        <table className="min-w-full text-sm">
          <thead className="bg-gray-50 text-left text-gray-700">
            <tr>
              <th className="px-4 py-2 font-semibold align-top">{t("writes.headerApproach")}</th>
              <th className="px-4 py-2 font-semibold align-top">{t("writes.headerChanges")}</th>
              <th className="px-4 py-2 font-semibold align-top">{t("writes.headerWhen")}</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-200 text-gray-800 align-top">
            <tr>
              <td className="px-4 py-3 whitespace-nowrap">
                <div className="font-semibold">{t("writes.hostType")}</div>
                <div className="text-xs text-gray-600 mt-1">{t("writes.hostTypeSub")}</div>
              </td>
              <td className="px-4 py-3">{t.rich("writes.hostChangesRich", { code, em })}</td>
              <td className="px-4 py-3">{t("writes.hostWhen")}</td>
            </tr>
            <tr>
              <td className="px-4 py-3 whitespace-nowrap">
                <div className="font-semibold">{t.rich("writes.idmapTypeRich", { code })}</div>
                <div className="text-xs text-gray-600 mt-1">{t("writes.idmapTypeSub")}</div>
              </td>
              <td className="px-4 py-3">{t.rich("writes.idmapChangesRich", { code })}</td>
              <td className="px-4 py-3">{t.rich("writes.idmapWhenRich", { em, code })}</td>
            </tr>
          </tbody>
        </table>
      </div>

      <Callout variant="tip" title={t("writes.idmapTipTitle")}>
        {t.rich("writes.idmapTipBody", { code })}
      </Callout>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("opening.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("opening.body", { strong })}
      </p>

      <Image
        src="/share/lxc-mount-points-menu.png"
        alt={t("opening.imageAlt")}
        width={900}
        height={500}
        className="rounded shadow-lg my-6"
      />

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("addFlow.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">{t("addFlow.intro")}</p>

      <pre className="bg-gray-100 text-gray-800 p-4 rounded-md overflow-x-auto text-sm my-4 border border-gray-200 leading-snug">
{`┌─────────────────────────────────────────────┐
│  PHASE 1 — Pick CT, host dir, mount point   │
│  (nothing touched yet)                      │
└──────────────────┬──────────────────────────┘
                   ▼
      pct list — pick the target container
                   │
                   ▼
      Unified host-directory picker
      Lists every candidate the script can detect:
      ├─ Mounted CIFS / NFS shares (/proc/mounts)
      ├─ fstab-inactive network mounts (defined
      │   but not currently mounted) — labelled
      │   "fstab(off)-"
      ├─ Local /mnt/* directories
      ├─ Proxmox-managed storages under /mnt/pve/*
      │   (NFS / CIFS shares registered via pvesm)
      │   — labelled "PVE-"
      └─ "Enter path manually"  for anything else
                   │
                   ▼
      Detect the host directory TYPE
      └─ local  /  cifs  /  nfs
         (drives the permission-fix branch later)
                   │
                   ▼
      Container mount point picker
      ├─ Create new directory in /mnt
      │    (auto-suggests basename of host dir)
      ├─ Enter manual path (must be absolute)
      └─ Cancel
      Validates the path is not already used as
      a mount point in this CT.
                   │
                   ▼
      Detect CT type:
      ├─ Privileged   → no UID shift
      └─ Unprivileged → +100000 (default idmap)
                   │
                   ▼
      ACTIVE FIX FOR THE HOST DIRECTORY
      (depends on the type detected earlier)
      ├─ cifs  → offer remount with open uid/gid
      ├─ nfs   → offer chmod + setfacl on share
      └─ local → handled AFTER the bind mount
                 (only if CT is unprivileged)
                   │
   ┌──────── Cancel   OR   Confirm ────┐
   ▼                                   ▼
Exit, nothing        ┌─────────────────┴─────────────────┐
was changed          │  PHASE 2 — Apply                   │
                     └─────────────────┬─────────────────┘
                                       ▼
                       Find next free mpN slot
                       (scans /etc/pve/lxc/<ctid>.conf)
                                       ▼
                       pct set <ctid> -mpN \\
                            <host-dir>,
                            mp=<container-path>,
                            shared=1, backup=0
                                       ▼
                       For local + unprivileged:
                       └─ lmm_offer_host_permissions
                          (chmod o+rwx + ACL on host dir,
                           only if perms were insufficient)
                                       ▼
                       Offer to restart the container
                       └─ pct reboot <ctid>
                          (mounts only become active on
                           the next CT start)
                                       ▼
                       Verify: pct exec <ctid> -- test -d
                       <container-path>  → "accessible"`}
      </pre>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("sources.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("sources.intro", { em })}
      </p>

      <div className="overflow-x-auto mb-4 rounded-md border border-gray-200">
        <table className="min-w-full text-sm">
          <thead className="bg-gray-50 text-left text-gray-700">
            <tr>
              <th className="px-4 py-2 font-semibold">{t("sources.headerSource")}</th>
              <th className="px-4 py-2 font-semibold">{t("sources.headerWhere")}</th>
              <th className="px-4 py-2 font-semibold">{t("sources.headerLabel")}</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-200 text-gray-800">
            {sourceRows.map((row, idx) => (
              <tr key={row.source}>
                <td className="px-4 py-2 font-semibold">{row.source}</td>
                <td className="px-4 py-2">
                  {row.whereRich ? t.rich(`sources.rows.${idx}.whereRich`, { code }) : row.where}
                </td>
                <td className="px-4 py-2">{t.rich(`sources.rows.${idx}.labelRich`, { code, em })}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <Callout variant="tip" title={t("sources.tipTitle")}>
        {t.rich("sources.tipBody", { code })}
      </Callout>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("manual.heading")}</h2>
      <p className="mb-3 text-gray-800 leading-relaxed">{t("manual.privIntro")}</p>
      <CopyableCode code={`# 1. add the bind mount to the CT config
pct set 101 -mp0 /mnt/data,mp=/mnt/data,shared=1,backup=0

# 2. restart the CT to activate the mount
pct reboot 101

# 3. verify from inside
pct exec 101 -- ls -la /mnt/data`} />

      <p className="mb-3 mt-6 text-gray-800 leading-relaxed">{t("manual.unprivLocalIntro")}</p>
      <CopyableCode code={`# host: open the directory for any mapped UID
chmod o+rwx /mnt/data
setfacl -m o::rwx /mnt/data
setfacl -m d:o::rwx /mnt/data    # default ACL = applies to new files

# add the bind mount + restart
pct set 102 -mp0 /mnt/data,mp=/mnt/data,shared=1,backup=0
pct reboot 102`} />

      <p className="mb-3 mt-6 text-gray-800 leading-relaxed">{t("manual.unprivCifsIntro")}</p>
      <CopyableCode code={`# host: remount the CIFS with open uid/gid
umount /mnt/pve/cifs-nas
mount -t cifs //10.0.0.50/share /mnt/pve/cifs-nas \\
  -o "username=user,password=pass,uid=0,gid=0,file_mode=0777,dir_mode=0777"

# update /etc/fstab if the mount is persistent
sed -i 's|^\\(//10.0.0.50/share .*cifs \\).*|\\1username=user,password=pass,uid=0,gid=0,file_mode=0777,dir_mode=0777 0 0|' /etc/fstab

# bind mount + restart
pct set 102 -mp0 /mnt/pve/cifs-nas,mp=/mnt/nas,shared=1,backup=0
pct reboot 102`} />

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("view.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">{t.rich("view.body", { code })}</p>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("remove.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">{t.rich("remove.body", { code, strong })}</p>

      <Callout variant="warning" title={t("remove.warnTitle")}>
        {t.rich("remove.warnBody", { code })}
      </Callout>

      <h2 className="text-2xl font-semibold mt-12 mb-4 text-gray-900">{t("troubleshoot.heading")}</h2>

      <Callout variant="troubleshoot" title={t("troubleshoot.noMountTitle")}>
        {t.rich("troubleshoot.noMountBody", { code })}
      </Callout>

      <Callout variant="troubleshoot" title={t("troubleshoot.noWriteTitle")}>
        {t.rich("troubleshoot.noWriteBody", { code })}
      </Callout>

      <Callout variant="troubleshoot" title={t("troubleshoot.alreadyTitle")}>
        {t("troubleshoot.alreadyBody")}
      </Callout>

      <Callout variant="troubleshoot" title={t("troubleshoot.nfsTitle")}>
        {t("troubleshoot.nfsIntro")}
        <ul className="mt-2 list-disc list-inside space-y-1">
          {nfsItems.map((_, idx) => (
            <li key={idx}>{t.rich(`troubleshoot.nfsItems.${idx}`, { code })}</li>
          ))}
        </ul>
        {t("troubleshoot.nfsOutro")}
      </Callout>

      <Callout variant="troubleshoot" title={t("troubleshoot.fstabOffTitle")}>
        {t.rich("troubleshoot.fstabOffBody", { code })}
      </Callout>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("related.heading")}</h2>
      <ul className="list-disc pl-6 mb-4 text-gray-800 leading-relaxed space-y-1">
        {relatedItems.map((item, idx) => (
          <li key={item.href}>
            <Link href={item.href} className="text-blue-600 hover:underline">
              {item.label}
            </Link>
            {item.extraHref && item.extraLabel && (
              <>
                {item.joiner}
                <Link href={item.extraHref} className="text-blue-600 hover:underline">
                  {item.extraLabel}
                </Link>
              </>
            )}
            {item.tailRich ? t.rich(`related.items.${idx}.tailRich`, { code }) : item.tail}
          </li>
        ))}
      </ul>
    </div>
  )
}
