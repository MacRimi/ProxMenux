import type { Metadata } from "next"
import { getTranslations, getMessages, setRequestLocale } from "next-intl/server"
import { Link } from "@/i18n/navigation"
import Image from "next/image"
import { DocHeader } from "@/components/ui/doc-header"
import { Callout } from "@/components/ui/callout"
import { Prerequisites } from "@/components/ui/prerequisites"
import { Steps } from "@/components/ui/steps"
import { SwitchModeGraphic } from "@/components/ui/switch-mode-graphic"
import CopyableCode from "@/components/CopyableCode"

export async function generateMetadata({
  params,
}: {
  params: Promise<{ locale: string }>
}): Promise<Metadata> {
  const { locale } = await params
  const t = await getTranslations({ locale, namespace: "docs.hardware.switchGpuMode.meta" })
  return {
    title: t("title"),
    description: t("description"),
  }
}

type WhenRow = { situation?: string; situationRich?: string; use?: string; useRich?: string }
type DirectionItem = string
type RelatedItem = { label: string; href: string; tail?: string }

export default async function SwitchGpuModePage({
  params,
}: {
  params: Promise<{ locale: string }>
}) {
  const { locale } = await params
  setRequestLocale(locale)
  const t = await getTranslations({ locale, namespace: "docs.hardware.switchGpuMode" })

  const messages = (await getMessages({ locale })) as unknown as {
    docs: { hardware: { switchGpuMode: {
      when: { rows: WhenRow[] }
      walkthrough: { direction: { items: DirectionItem[] } }
      related: { items: RelatedItem[] }
    } } }
  }
  const whenRows = messages.docs.hardware.switchGpuMode.when.rows
  const directionItems = messages.docs.hardware.switchGpuMode.walkthrough.direction.items
  const relatedItems = messages.docs.hardware.switchGpuMode.related.items

  const code = (chunks: React.ReactNode) => <code>{chunks}</code>
  const strong = (chunks: React.ReactNode) => <strong>{chunks}</strong>
  const em = (chunks: React.ReactNode) => <em>{chunks}</em>
  const vmLink = (chunks: React.ReactNode) => (
    <Link href="/docs/hardware/gpu-vm-passthrough" className="text-blue-700 hover:underline">{chunks}</Link>
  )
  const lxcLink = (chunks: React.ReactNode) => (
    <Link href="/docs/hardware/igpu-acceleration-lxc" className="text-blue-700 hover:underline">{chunks}</Link>
  )

  return (
    <div>
      <DocHeader
        title={t("header.title")}
        description={t("header.description")}
        section={t("header.section")}
        estimatedMinutes={10}
        scriptPath="gpu_tpu/switch_gpu_mode.sh"
      />

      <Callout variant="info" title={t("intro.title")}>
        {t.rich("intro.body", { code, em, strong })}
      </Callout>

      <div className="grid gap-4 md:grid-cols-2 my-6 not-prose">
        <SwitchModeGraphic
          mode="lxc"
          title={t("graphics.lxcTitle")}
          description={t("graphics.lxcDesc")}
        />
        <SwitchModeGraphic
          mode="vm"
          title={t("graphics.vmTitle")}
          description={t("graphics.vmDesc")}
        />
      </div>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("when.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("when.intro", { strong })}
      </p>
      <div className="my-4 overflow-x-auto">
        <table className="min-w-full border border-gray-200 text-sm">
          <thead className="bg-gray-100">
            <tr>
              <th className="border border-gray-200 px-3 py-2 text-left text-gray-900">{t("when.headerSituation")}</th>
              <th className="border border-gray-200 px-3 py-2 text-left text-gray-900">{t("when.headerUse")}</th>
            </tr>
          </thead>
          <tbody className="text-gray-800">
            {whenRows.map((row, idx) => (
              <tr key={idx}>
                <td className="border border-gray-200 px-3 py-2">
                  {row.situationRich
                    ? t.rich(`when.rows.${idx}.situationRich`, { code })
                    : row.situation}
                </td>
                <td className="border border-gray-200 px-3 py-2">
                  {row.useRich
                    ? t.rich(`when.rows.${idx}.useRich`, { vmLink, lxcLink, strong })
                    : row.use}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <Prerequisites
        title={t("prereqs.title")}
        items={[
          { label: <>{t.rich("prereqs.assigned", { strong })}</> },
          {
            label: <>{t.rich("prereqs.iommu", { strong, em })}</>,
            check: t("prereqs.iommuCheck"),
          },
          { label: <>{t.rich("prereqs.reboot", { strong })}</> },
          { label: <>{t.rich("prereqs.knowList", { strong })}</> },
        ]}
      />

      <Callout variant="warning" title={t("blocklist.title")}>
        {t.rich("blocklist.body", { code, em })}
      </Callout>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("running.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("running.body", { strong })}
      </p>

      <Image
        src="/gpu-tpu/gpu-switch-01-menu-entry.png"
        alt={t("running.imageAlt")}
        width={900}
        height={500}
        className="rounded shadow-lg my-6"
      />

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("howRuns.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">{t("howRuns.body")}</p>

      <pre className="bg-gray-100 text-gray-800 p-4 rounded-md overflow-x-auto text-sm my-4 border border-gray-200 leading-snug">
{`┌─────────────────────────────────────────────┐
│  PHASE 1 — Detect, select, plan             │
│  (nothing touched yet)                      │
└──────────────────┬──────────────────────────┘
                   ▼
  lspci detects every GPU + current driver
  (vfio-pci, nvidia, amdgpu, i915, …)
                   │
                   ▼
  User selects GPU(s) to switch
  (checklist; auto-selects if only one)
                   │
                   ▼
  Uniform current mode check
  ├─ All in VM mode    → target = LXC
  ├─ All in LXC mode   → target = VM
  └─ Mixed             → reject, reselect
                   │
                   ▼
  Validations
  ├─ SR-IOV VF / active PF?       → block
  ├─ Target = VM and blocked ID?  → block
  └─ IOMMU parameter present?     → warn if missing
                   │
                   ▼
  Find affected workloads
  ├─ LXC configs referencing the GPU
  └─ VM configs with hostpci for the GPU
      (precise BDF regex, no substring false-positives)
                   │
                   ▼
  Conflict policy per affected workload
  ┌──────────────────────────────────────┐
  │ Keep config, disable onboot          │
  │   └─ safest; workload stays defined  │
  │      but won't auto-start broken     │
  │ Remove GPU lines from config         │
  │   └─ clean; workload works without   │
  │      the GPU after the switch        │
  └──────────────────────────────────────┘
                   │
                   ▼
  If target = LXC (leaving VM mode):
  └─ Orphan audio cascade
     (offer to remove companion audio
      hostpci + clean vfio.conf if the
      audio ID isn't used by any other VM)
                   │
                   ▼
  Confirmation summary
  (target mode + affected workloads +
   host changes about to happen)
                   │
     ┌─────── Cancel   OR   Confirm ────┐
     ▼                                  ▼
 Exit, nothing       ┌──────────────────┴──────────────────┐
 was changed         │  PHASE 2 — Apply                    │
                     └──────────────────┬──────────────────┘
                                        ▼
                       Target = VM (bind to vfio-pci):
                       ├─ /etc/modprobe.d/vfio.conf
                       │    add vendor:device + disable_vga=1
                       ├─ /etc/modprobe.d/blacklist.conf
                       │    add type-specific blacklists
                       ├─ /etc/modules
                       │    add vfio-pci, vfio
                       ├─ NVIDIA: sanitize host stack
                       │    (disable udev rule, hard-blacklist)
                       └─ AMD: softdep vfio-pci

                       Target = LXC (back to native driver):
                       ├─ /etc/modprobe.d/vfio.conf
                       │    drop vendor:device IDs for this GPU
                       │    (delete line if now empty)
                       ├─ /etc/modprobe.d/blacklist.conf
                       │    drop type blacklists if no GPU of
                       │    that type remains in vfio.conf
                       ├─ /etc/modules
                       │    drop vfio-pci if no GPU in vfio.conf
                       └─ NVIDIA: restore host stack
                          (re-enable udev, drop hard-blacklist)
                                        │
                                        ▼
                       Apply workload conflict policy
                       (pct set onboot=0  OR  sed hostpci/dev
                        lines out of VM/LXC configs)
                                        │
                                        ▼
                       update-initramfs -u -k all
                       (only if host config actually changed)
                                        │
                                        ▼
                       Reboot prompt — required for the new
                       binding to take effect`}
      </pre>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("walkthrough.heading")}</h2>

      <Steps>
        <Steps.Step title={t("walkthrough.detect.title")}>
          <p className="mb-3 text-gray-800">{t.rich("walkthrough.detect.body", { code })}</p>
          <Image
            src="/gpu-tpu/gpu-switch-02-gpu-select.png"
            alt={t("walkthrough.detect.imageAlt")}
            width={900}
            height={500}
            className="rounded shadow-lg my-6"
          />
        </Steps.Step>

        <Steps.Step title={t("walkthrough.pickGpu.title")}>
          <p className="mb-3 text-gray-800">{t.rich("walkthrough.pickGpu.body", { em })}</p>
          <Callout variant="tip" title={t("walkthrough.pickGpu.tipTitle")}>
            {t("walkthrough.pickGpu.tipBody")}
          </Callout>
        </Steps.Step>

        <Steps.Step title={t("walkthrough.direction.title")}>
          <p className="mb-3 text-gray-800">{t("walkthrough.direction.intro")}</p>
          <ul className="list-disc pl-6 space-y-1 text-gray-800 mb-3">
            {directionItems.map((_, idx) => (
              <li key={idx}>{t.rich(`walkthrough.direction.items.${idx}`, { strong, code })}</li>
            ))}
          </ul>
          <p className="mb-3 text-gray-800">{t("walkthrough.direction.outro")}</p>
        </Steps.Step>

        <Steps.Step title={t("walkthrough.conflict.title")}>
          <p className="mb-3 text-gray-800">{t.rich("walkthrough.conflict.body", { code })}</p>
          <div className="my-4 overflow-x-auto">
            <table className="min-w-full border border-gray-200 text-sm">
              <thead className="bg-gray-100">
                <tr>
                  <th className="border border-gray-200 px-3 py-2 text-left text-gray-900">{t("walkthrough.conflict.headerPolicy")}</th>
                  <th className="border border-gray-200 px-3 py-2 text-left text-gray-900">{t("walkthrough.conflict.headerEffect")}</th>
                  <th className="border border-gray-200 px-3 py-2 text-left text-gray-900">{t("walkthrough.conflict.headerWhen")}</th>
                </tr>
              </thead>
              <tbody className="text-gray-800">
                <tr>
                  <td className="border border-gray-200 px-3 py-2"><strong>{t("walkthrough.conflict.keepPolicy")}</strong></td>
                  <td className="border border-gray-200 px-3 py-2">{t.rich("walkthrough.conflict.keepEffect", { code })}</td>
                  <td className="border border-gray-200 px-3 py-2">{t("walkthrough.conflict.keepWhen")}</td>
                </tr>
                <tr>
                  <td className="border border-gray-200 px-3 py-2"><strong>{t("walkthrough.conflict.removePolicy")}</strong></td>
                  <td className="border border-gray-200 px-3 py-2">{t.rich("walkthrough.conflict.removeEffect", { code })}</td>
                  <td className="border border-gray-200 px-3 py-2">{t("walkthrough.conflict.removeWhen")}</td>
                </tr>
              </tbody>
            </table>
          </div>
          <Image
            src="/gpu-tpu/gpu-switch-03-conflict-policy.png"
            alt={t("walkthrough.conflict.imageAlt")}
            width={900}
            height={500}
            className="rounded shadow-lg my-6"
          />
        </Steps.Step>

        <Steps.Step title={t("walkthrough.audio.title")}>
          <p className="mb-3 text-gray-800">{t.rich("walkthrough.audio.body1", { code })}</p>
          <p className="mb-3 text-gray-800">{t.rich("walkthrough.audio.body2", { code })}</p>
        </Steps.Step>

        <Steps.Step title={t("walkthrough.apply.title")}>
          <p className="mb-3 text-gray-800">{t.rich("walkthrough.apply.body", { code })}</p>
        </Steps.Step>

        <Steps.Step title={t("walkthrough.reboot.title")}>
          <p className="mb-3 text-gray-800">{t("walkthrough.reboot.body")}</p>
          <Image
            src="/gpu-tpu/gpu-switch-04-summary.png"
            alt={t("walkthrough.reboot.imageAlt")}
            width={900}
            height={500}
            className="rounded shadow-lg my-6"
          />
        </Steps.Step>
      </Steps>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("manual.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("manual.intro", { strong, code })}
      </p>
      <CopyableCode
        code={`# Drop the vendor:device from vfio.conf — keep other GPUs intact
sed -i 's/10de:2204,//; s/,10de:2204//; s/=10de:2204 /=/' /etc/modprobe.d/vfio.conf

# Remove the NVIDIA hard-blacklist and nouveau blacklist
sed -i '/^blacklist nouveau$/d; /^blacklist nvidia$/d; /^blacklist nvidia_drm$/d; /^blacklist nvidia_modeset$/d; /^blacklist nvidia_uvm$/d; /^blacklist nvidiafb$/d' /etc/modprobe.d/blacklist.conf
rm -f /etc/modprobe.d/nvidia-blacklist.conf

# Re-enable NVIDIA udev rule + modules-load config (if disabled by VM-mode switch)
[ -f /etc/udev/rules.d/70-nvidia.rules.proxmenux-disabled-vfio ] && \\
  mv /etc/udev/rules.d/70-nvidia.rules.proxmenux-disabled-vfio \\
     /etc/udev/rules.d/70-nvidia.rules
[ -f /etc/modules-load.d/nvidia-vfio.conf.proxmenux-disabled-vfio ] && \\
  mv /etc/modules-load.d/nvidia-vfio.conf.proxmenux-disabled-vfio \\
     /etc/modules-load.d/nvidia-vfio.conf

# Clean up the VM config — precise BDF regex, no substring collisions
# (replace 0000:01:00 with your GPU's slot)
sed -E -i '/^hostpci[0-9]+:[[:space:]]*(0000:)?01:00\\.[0-7]([,[:space:]]|$)/d' \\
  /etc/pve/qemu-server/<vmid>.conf

# Rebuild initramfs and reboot
update-initramfs -u -k all
reboot`}
        className="my-4"
      />

      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("manual.lxcToVm", { strong })}
      </p>
      <CopyableCode
        code={`# Add the vendor:device to vfio.conf (create the line if missing)
grep -q '^options vfio-pci ids=' /etc/modprobe.d/vfio.conf && \\
  sed -i '/^options vfio-pci ids=/ s/$/,10de:2204/' /etc/modprobe.d/vfio.conf || \\
  echo 'options vfio-pci ids=10de:2204 disable_vga=1' >> /etc/modprobe.d/vfio.conf

# Blacklist the native driver so vfio-pci can claim the card
cat >> /etc/modprobe.d/blacklist.conf <<'EOF'
blacklist nouveau
blacklist nvidia
blacklist nvidia_drm
blacklist nvidia_modeset
blacklist nvidia_uvm
blacklist nvidiafb
options nouveau modeset=0
EOF

# Make sure vfio-pci loads at boot
grep -q '^vfio-pci$' /etc/modules || echo 'vfio-pci' >> /etc/modules

# Rebuild initramfs and reboot
update-initramfs -u -k all
reboot`}
        className="my-4"
      />

      <Callout variant="warning" title={t("manual.oneVmTitle")}>
        {t.rich("manual.oneVmBody", { code })}
      </Callout>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("verification.heading")}</h2>
      <CopyableCode
        code={`# Confirm the GPU is bound to the driver you expect
lspci -nnk -d <vendor:device>
# Expected (LXC mode): "Kernel driver in use: nvidia" (or amdgpu, i915)
# Expected (VM  mode): "Kernel driver in use: vfio-pci"

# LXC mode — is the host tool happy?
nvidia-smi                 # if NVIDIA
intel_gpu_top              # if Intel iGPU

# VM mode — ready to be claimed by a VM start
lsmod | grep vfio`}
        className="my-4"
      />

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("troubleshoot.heading")}</h2>

      <Callout variant="troubleshoot" title={t("troubleshoot.stillVfioTitle")}>
        {t.rich("troubleshoot.stillVfioBody", { code })}
      </Callout>

      <Callout variant="troubleshoot" title={t("troubleshoot.vmFailTitle")}>
        {t.rich("troubleshoot.vmFailBody", { code, em })}
      </Callout>
      <CopyableCode
        code={`# Delete every hostpci line for the GPU slot
sed -E -i '/^hostpci[0-9]+:[[:space:]]*(0000:)?<slot>\\.[0-7]([,[:space:]]|$)/d' \\
  /etc/pve/qemu-server/<vmid>.conf`}
        className="my-4"
      />

      <Callout variant="troubleshoot" title={t("troubleshoot.smiFailTitle")}>
        {t.rich("troubleshoot.smiFailBody", { code })}
      </Callout>

      <Callout variant="tip" title={t("troubleshoot.logTitle")}>
        {t.rich("troubleshoot.logBody", { code })}
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
