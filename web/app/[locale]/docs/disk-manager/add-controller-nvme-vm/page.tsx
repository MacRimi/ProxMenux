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
  const t = await getTranslations({ locale, namespace: "docs.diskManager.addControllerNvmeVm.meta" })
  return {
    title: t("title"),
    description: t("description"),
    openGraph: {
      title: t("ogTitle"),
      description: t("ogDescription"),
      type: "article",
      url: "https://macrimi.github.io/ProxMenux/docs/disk-manager/add-controller-nvme-vm",
    },
  }
}

type StepData = {
  title: string
  body?: string
  bodyRich?: string
  items?: string[]
  outro?: string
  img?: string
  alt?: string
  caption?: string
}
type StringItem = string
type RelatedItem = { href: string; label: string; tail?: string }

export default async function AddControllerNVMeVMPage({
  params,
}: {
  params: Promise<{ locale: string }>
}) {
  const { locale } = await params
  setRequestLocale(locale)
  const t = await getTranslations({ locale, namespace: "docs.diskManager.addControllerNvmeVm" })

  const messages = (await getMessages({ locale })) as unknown as {
    docs: { diskManager: { addControllerNvmeVm: {
      prereqs: { items: StringItem[] }
      steps: { list: StepData[] }
      related: { items: RelatedItem[] }
    } } }
  }
  const prereqItems = messages.docs.diskManager.addControllerNvmeVm.prereqs.items
  const stepList = messages.docs.diskManager.addControllerNvmeVm.steps.list
  const relatedItems = messages.docs.diskManager.addControllerNvmeVm.related.items

  const code = (chunks: React.ReactNode) => <code>{chunks}</code>
  const strong = (chunks: React.ReactNode) => <strong>{chunks}</strong>
  const em = (chunks: React.ReactNode) => <em>{chunks}</em>

  return (
    <div>
      <DocHeader
        title={t("header.title")}
        description={t("header.description")}
        section={t("header.section")}
        estimatedMinutes={15}
        scriptPath="storage/add_controller_nvme_vm.sh"
      />

      <Callout variant="info" title={t("intro.title")}>
        {t.rich("intro.body", { strong, code })}
      </Callout>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("howRuns.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">{t("howRuns.body")}</p>

      <pre className="bg-gray-100 text-gray-800 p-4 rounded-md overflow-x-auto text-sm my-4 border border-gray-200 leading-snug">
{`┌─────────────────────────────────────────────┐
│  PHASE 1 — Detect, validate, plan           │
│  (nothing touched yet)                      │
└──────────────────┬──────────────────────────┘
                   ▼
      qm list — user picks target VM
                   │
                   ▼
      IOMMU status on the running kernel
      ├─ /sys/kernel/iommu_groups/* exists?
      │
      ├─ Yes → IOMMU active, continue
      │
      └─ No  → cmdline check + offer to enable
            CPU vendor detect (cat /proc/cpuinfo)
            ├─ Intel → write intel_iommu=on
            └─ AMD   → write amd_iommu=on
            Into:
            ├─ /etc/kernel/cmdline  (systemd-boot)
            └─ /etc/default/grub    (GRUB)
            + update-initramfs -u -k all
            + offer reboot now
            ├─ reboot accepted → reboot
            └─ reboot declined → abort
                 (re-run after reboot)
                   │
                   ▼
      Enumerate storage-class PCI devices
      lspci -Dnn filtered by class:
      ├─ SATA / SAS / SCSI / NVMe controllers
      ├─ Resolve IOMMU group via /sys path
      └─ For HBAs: list disks currently behind
                   │
                   ▼
      Conflict / eligibility filter
      ├─ Already in this VM's hostpci? → hide
      ├─ Already in another VM's hostpci?
      │    → block (shown with owner VM id)
      ├─ Carries the Proxmox root disk
      │    or any disk referenced by an LXC
      │    → block
      └─ Shared IOMMU group
         with non-storage members?
            → show ⚠ warning inline
                   │
                   ▼
      User selects device(s) via checklist
                   │
                   ▼
      Summary:
      (VM + each PCI device + IOMMU group
       membership + reboot status)
                   │
   ┌──────── Cancel   OR   Confirm ────┐
   ▼                                   ▼
Exit, nothing        ┌─────────────────┴─────────────────┐
was changed          │  PHASE 2 — Apply                   │
                     └─────────────────┬─────────────────┘
                                       ▼
                       Host side (once per session):
                       ├─ Add vfio-pci to /etc/modules
                       ├─ Append the device vendor:device
                       │  IDs to /etc/modprobe.d/vfio.conf
                       └─ update-initramfs -u -k all
                       (so the device is bound to vfio-pci
                        at next boot, not the native driver)
                                       │
                                       ▼
                       For each selected device:
                       ├─ Find next free hostpciN slot
                       │   (scans qm config)
                       └─ qm set <VMID> --hostpciN \\
                             <BDF>,pcie=1
                             (e.g. 0000:01:00.0,pcie=1)
                                       │
                                       ▼
                       Verify: qm config <VMID> shows
                       the new hostpciN entries
                                       │
                                       ▼
                       If IOMMU was just enabled:
                       └─ reminder to reboot before
                          starting the VM
                                       │
                                       ▼
                       Guest on next boot sees the
                       controller directly + every disk
                       behind it (full SMART, native
                       firmware features, no Proxmox layer)`}
      </pre>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("iommu.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("iommu.body", { strong })}
      </p>
      <div className="my-6 rounded-md border border-gray-200 bg-gray-50 p-4 overflow-x-auto">
        <pre className="text-xs leading-relaxed text-gray-800 whitespace-pre font-mono">
{`          Host PCIe bus — grouped by IOMMU
                      │
                      ▼
    ┌─────────────────────────────────────────┐
    │  Group 12                               │
    │  ────────                               │
    │  00:17.0   SATA HBA                     │
    │    └── sda sdb sdc sdd                  │
    │                                         │
    │  Pass-through takes:                    │
    │    the HBA + every disk on it           │
    │                                         │
    │  ✓ clean — no extra members in group    │
    └──────────────────┬──────────────────────┘
                       │
                       ▼
    ┌─────────────────────────────────────────┐
    │  Group 13                               │
    │  ────────                               │
    │  01:00.0   NVMe controller              │
    │                                         │
    │  Pass-through takes:                    │
    │    the NVMe controller itself           │
    │                                         │
    │  ✓ clean — NVMe alone in its group      │
    └──────────────────┬──────────────────────┘
                       │
                       ▼
    ┌─────────────────────────────────────────┐
    │  Group 14                               │
    │  ────────                               │
    │  02:00.0   SATA HBA                     │
    │    └── sde sdf                          │
    │  02:00.1   USB 3.0 controller           │
    │                                         │
    │  Pass-through takes:                    │
    │    SATA HBA + USB 3.0 controller        │
    │    (whole group leaves together)        │
    │                                         │
    │  ⚠ shared group — the USB ports will    │
    │    also leave the host. Review whether  │
    │    that is acceptable before confirming.│
    └─────────────────────────────────────────┘`}
        </pre>
      </div>
      <p className="mb-4 text-gray-800 leading-relaxed">{t("iommu.outro")}</p>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("prereqs.heading")}</h2>
      <ul className="list-disc pl-6 mb-4 text-gray-800 leading-relaxed space-y-1">
        {prereqItems.map((_, idx) => (
          <li key={idx}>{t.rich(`prereqs.items.${idx}`, { strong, em })}</li>
        ))}
      </ul>

      <Callout variant="warning" title={t("prereqs.warnTitle")}>
        {t("prereqs.warnBody")}
      </Callout>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("steps.heading")}</h2>

      {stepList.map((step, idx) => (
        <section key={idx} className="mt-8 border-b border-gray-200 pb-8">
          <div className="flex items-center gap-3 mb-3">
            <span className="inline-flex items-center rounded-full border border-blue-200 bg-blue-50 px-2.5 py-0.5 text-xs font-semibold text-blue-800">
              {t("steps.stepLabel")} {idx + 1}
            </span>
            <h3 className="text-lg font-semibold text-gray-900 m-0">{step.title}</h3>
          </div>
          <div className="mb-4 text-gray-800 leading-relaxed">
            {step.bodyRich ? (
              <p className="mb-4">{t.rich(`steps.list.${idx}.bodyRich`, { code, strong })}</p>
            ) : step.body && <p className="mb-4">{step.body}</p>}
            {step.items && (
              <ul className="list-disc pl-6 mt-2 space-y-1 mb-4">
                {step.items.map((_, i) => (
                  <li key={i}>{t.rich(`steps.list.${idx}.items.${i}`, { code })}</li>
                ))}
              </ul>
            )}
            {step.outro && <p className="mb-4">{step.outro}</p>}
          </div>
          {step.img && (
            <div className="flex flex-col items-center w-full max-w-[768px] mx-auto my-4">
              <div className="w-full overflow-hidden rounded-md border border-gray-200">
                <Image src={step.img} alt={step.alt || step.title} width={768} height={0} style={{ height: "auto" }} className="w-full object-contain" sizes="(max-width: 768px) 100vw, 768px" />
              </div>
              {step.caption && <span className="mt-2 text-sm text-gray-600">{step.caption}</span>}
            </div>
          )}
        </section>
      ))}

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("manual.heading")}</h2>
      <CopyableCode code={`# 1. verify IOMMU is active
dmesg | grep -iE "DMAR|IOMMU" | head
ls /sys/kernel/iommu_groups/

# 2. list IOMMU groups and their members
for d in /sys/kernel/iommu_groups/*/devices/*; do
  n=$(basename "$d"); g=$(dirname "$(dirname "$d")")
  printf 'group %3d  %s  %s\\n' "$(basename "$g")" "$n" \\
    "$(lspci -s "$n" | cut -d' ' -f2-)"
done | sort -n

# 3. attach a storage controller at PCI 0000:00:17.0 to VM 101
qm set 101 --hostpci0 0000:00:17.0,pcie=1

# 4. verify
qm config 101 | grep ^hostpci`} />

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("troubleshoot.heading")}</h2>
      <Callout variant="troubleshoot" title={t("troubleshoot.noGroupsTitle")}>
        {t("troubleshoot.noGroupsBody")}
      </Callout>
      <Callout variant="troubleshoot" title={t("troubleshoot.busyTitle")}>
        {t.rich("troubleshoot.busyBody", { code })}
      </Callout>
      <Callout variant="troubleshoot" title={t("troubleshoot.noDisksTitle")}>
        {t("troubleshoot.noDisksBody")}
      </Callout>
      <Callout variant="troubleshoot" title={t("troubleshoot.sharedTitle")}>
        {t.rich("troubleshoot.sharedBody", { em })}
      </Callout>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("related.heading")}</h2>
      <ul className="list-disc pl-6 text-gray-800 leading-relaxed space-y-1">
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
