import type { Metadata } from "next"
import { getTranslations, getMessages, setRequestLocale } from "next-intl/server"
import { Link } from "@/i18n/navigation"
import Image from "next/image"
import { ExternalLink } from "lucide-react"
import { DocHeader } from "@/components/ui/doc-header"
import { Callout } from "@/components/ui/callout"
import { Prerequisites } from "@/components/ui/prerequisites"
import { Steps } from "@/components/ui/steps"
import CopyableCode from "@/components/CopyableCode"

export async function generateMetadata({
  params,
}: {
  params: Promise<{ locale: string }>
}): Promise<Metadata> {
  const { locale } = await params
  const t = await getTranslations({ locale, namespace: "docs.hardware.gpuVmPassthrough.meta" })
  return {
    title: t("title"),
    description: t("description"),
  }
}

type StringItem = string
type RelatedItem = { label: string; href: string; tail?: string }

export default async function GpuVmPassthroughPage({
  params,
}: {
  params: Promise<{ locale: string }>
}) {
  const { locale } = await params
  setRequestLocale(locale)
  const t = await getTranslations({ locale, namespace: "docs.hardware.gpuVmPassthrough" })

  const messages = (await getMessages({ locale })) as unknown as {
    docs: { hardware: { gpuVmPassthrough: {
      walkthrough: {
        preflight: { items: StringItem[] }
        switchMode: { items: StringItem[] }
        hostApply: { items: StringItem[] }
      }
      related: { items: RelatedItem[] }
    } } }
  }
  const preflightItems = messages.docs.hardware.gpuVmPassthrough.walkthrough.preflight.items
  const switchModeItems = messages.docs.hardware.gpuVmPassthrough.walkthrough.switchMode.items
  const hostApplyItems = messages.docs.hardware.gpuVmPassthrough.walkthrough.hostApply.items
  const relatedItems = messages.docs.hardware.gpuVmPassthrough.related.items

  const code = (chunks: React.ReactNode) => <code>{chunks}</code>
  const strong = (chunks: React.ReactNode) => <strong>{chunks}</strong>
  const em = (chunks: React.ReactNode) => <em>{chunks}</em>
  const pveLink = (chunks: React.ReactNode) => (
    <a
      href="https://pve.proxmox.com/wiki/PCI(e)_Passthrough"
      target="_blank"
      rel="noopener noreferrer"
      className="text-blue-700 hover:underline inline-flex items-center gap-1"
    >
      {chunks}
      <ExternalLink className="w-3 h-3" />
    </a>
  )
  const lxcLink = (chunks: React.ReactNode) => (
    <Link href="/docs/hardware/igpu-acceleration-lxc" className="text-blue-700 hover:underline">{chunks}</Link>
  )
  const nvidiaLink = (chunks: React.ReactNode) => (
    <Link href="/docs/hardware/nvidia-host" className="text-blue-700 hover:underline">{chunks}</Link>
  )
  const postLink = (chunks: React.ReactNode) => (
    <Link href="/docs/post-install/virtualization" className="text-blue-700 hover:underline">{chunks}</Link>
  )
  const vendorResetLink = (chunks: React.ReactNode) => (
    <a
      href="https://github.com/gnif/vendor-reset"
      target="_blank"
      rel="noopener noreferrer"
      className="text-blue-700 hover:underline inline-flex items-center gap-1"
    >
      {chunks}
      <ExternalLink className="w-3 h-3" />
    </a>
  )
  const sriovLink = (chunks: React.ReactNode) => (
    <a
      href="https://github.com/strongtz/i915-sriov-dkms"
      target="_blank"
      rel="noopener noreferrer"
      className="text-blue-700 hover:underline inline-flex items-center gap-1"
    >
      {chunks}
      <ExternalLink className="w-3 h-3" />
    </a>
  )

  return (
    <div>
      <DocHeader
        title={t("header.title")}
        description={t("header.description")}
        section={t("header.section")}
        estimatedMinutes={15}
        scriptPath="gpu_tpu/add_gpu_vm.sh"
      />

      <Callout variant="info" title={t("intro.title")}>
        {t.rich("intro.body", { code, em, pveLink })}
      </Callout>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("who.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("who.body", { strong, em, lxcLink })}
      </p>

      <Prerequisites
        title={t("prereqs.title")}
        items={[
          { label: <>{t.rich("prereqs.gpu", { strong, code })}</>, check: t("prereqs.gpuCheck") },
          { label: <>{t.rich("prereqs.iommu", { strong })}</> },
          { label: <>{t.rich("prereqs.q35", { strong, code })}</>, check: t("prereqs.q35Check") },
          { label: <>{t.rich("prereqs.moreGpus", { strong, em })}</> },
          { label: <>{t.rich("prereqs.nvidiaInstalled", { nvidiaLink, code, strong })}</> },
        ]}
      />

      <Callout variant="warning" title={t("pickOne.title")}>
        {t.rich("pickOne.body", { code })}
      </Callout>
      <ul className="list-disc pl-6 space-y-1 text-gray-800 mb-4">
        <li>{t.rich("pickOne.vmItem", { strong })}</li>
        <li>{t.rich("pickOne.lxcItem", { strong, lxcLink })}</li>
      </ul>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("running.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("running.body", { strong })}
      </p>

      <Image
        src="/gpu-tpu/gpu-vm-01-menu-entry.png"
        alt={t("running.imageAlt")}
        width={900}
        height={500}
        className="rounded shadow-lg my-6"
      />

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("howRuns.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">{t("howRuns.body")}</p>

      <pre className="bg-gray-100 text-gray-800 p-4 rounded-md overflow-x-auto text-sm my-4 border border-gray-200 leading-snug">
{`┌─────────────────────────────────────────────┐
│  PHASE 1 — Gather info, validate, confirm   │
│  (nothing touched yet)                      │
└──────────────────┬──────────────────────────┘
                   ▼
      ┌────────────┴────────────┐
      ▼                         ▼
  lspci detects             IOMMU enabled?
  GPUs (Intel/AMD/           ├─ No → offer to add
  NVIDIA)                    │      intel_iommu=on /
      │                      │      amd_iommu=on
      ▼                      └─ Yes → continue
  User selects GPU
      │
      ▼
  Pre-flight checks
  ├─ Not in SR-IOV
  ├─ Not D3cold (AMD)
  ├─ Has FLR or equivalent reset
  ├─ Warn if single-GPU host
  └─ Resolve IOMMU group
      │
      ▼
  Audio companion
      ├─ Has .1 sibling?  (dGPU: NVIDIA/AMD HDMI)
      │      → auto-include (never used by host)
      └─ No .1 sibling?   (Intel iGPU, split audio)
             → checklist of host audio controllers,
               default = none (user opts in)
      │
      ▼
  User selects VM
      │
      ▼
  VM is q35? ── No → abort
      │
     Yes
      ▼
  GPU already assigned elsewhere?
      │
      ├─ To LXC     → offer to remove it from LXC
      ├─ To other VM → offer to remove it there
      │               + clean up orphan audio
      │                 (skips audio whose
      │                 display sibling stays)
      └─ Free        → continue
      │
      ▼
  Show confirmation summary
  (GPU + IOMMU siblings + audio + target VM)
                   │
     ┌─────── Cancel   OR   Confirm ────┐
     ▼                                  ▼
 exit, nothing            ┌─────────────┴──────────────┐
 was changed              │  PHASE 2 — Apply changes   │
                          └─────────────┬──────────────┘
                                        ▼
                          Host:
                          ├─ /etc/modules (vfio_*)
                          ├─ /etc/modprobe.d/vfio.conf (ids=...)
                          ├─ /etc/modprobe.d/blacklist.conf
                          ├─ kernel cmdline (IOMMU if missing)
                          ├─ NVIDIA: disable udev rule + hard blacklist
                          ├─ AMD: dump ROM → /usr/share/kvm/*.bin
                          └─ update-initramfs -u -k all

                          VM config (qm set <vmid>):
                          ├─ hostpci0 = GPU (x-vga=1 unless Intel iGPU)
                          ├─ hostpci1..n = IOMMU group siblings
                          ├─ hostpci<last> = audio function(s)
                          ├─ vga = std
                          └─ NVIDIA: cpu=host,hidden=1
                                     args=... hv_vendor_id=NV43FIX
                                        │
                                        ▼
                        ┌───────────────┴───────────────┐
                        │  PHASE 3 — Summary + reboot   │
                        └───────────────────────────────┘
                        Show what changed. If host config
                        touched → prompt reboot.`}
      </pre>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("walkthrough.heading")}</h2>

      <Steps>
        <Steps.Step title={t("walkthrough.detect.title")}>
          <p className="mb-3 text-gray-800">{t.rich("walkthrough.detect.body", { code })}</p>
          <Callout variant="tip" title={t("walkthrough.detect.tipTitle")}>
            {t.rich("walkthrough.detect.tipBody", { postLink })}
          </Callout>
          <Image
            src="/gpu-tpu/gpu-vm-02-gpu-detection.png"
            alt={t("walkthrough.detect.imageAlt")}
            width={900}
            height={500}
            className="rounded shadow-lg my-6"
          />
        </Steps.Step>

        <Steps.Step title={t("walkthrough.preflight.title")}>
          <p className="mb-3 text-gray-800">{t("walkthrough.preflight.intro")}</p>
          <ul className="list-disc pl-6 space-y-1 text-gray-800 mb-3">
            {preflightItems.map((_, idx) => (
              <li key={idx}>{t.rich(`walkthrough.preflight.items.${idx}`, { strong, code, em })}</li>
            ))}
            <li>
              {t.rich("walkthrough.preflight.audioIntro", { strong })}
              <ul className="list-disc pl-6 mt-1 space-y-1">
                <li>{t.rich("walkthrough.preflight.audioDgpu", { strong, code })}</li>
                <li>{t.rich("walkthrough.preflight.audioIgpu", { strong, code })}</li>
              </ul>
            </li>
          </ul>
        </Steps.Step>

        <Steps.Step title={t("walkthrough.pickVm.title")}>
          <p className="mb-3 text-gray-800">{t("walkthrough.pickVm.body")}</p>
          <Image
            src="/gpu-tpu/gpu-vm-03-vm-select.png"
            alt={t("walkthrough.pickVm.imageAlt")}
            width={900}
            height={500}
            className="rounded shadow-lg my-6"
          />
        </Steps.Step>

        <Steps.Step title={t("walkthrough.switchMode.title")}>
          <p className="mb-3 text-gray-800">{t("walkthrough.switchMode.intro")}</p>
          <ul className="list-disc pl-6 space-y-1 text-gray-800 mb-3">
            {switchModeItems.map((_, idx) => (
              <li key={idx}>{t.rich(`walkthrough.switchMode.items.${idx}`, { strong, code })}</li>
            ))}
          </ul>
          <Image
            src="/gpu-tpu/gpu-vm-04-switch-mode.png"
            alt={t("walkthrough.switchMode.imageAlt")}
            width={900}
            height={500}
            className="rounded shadow-lg my-6"
          />

          <Callout variant="tip" title={t("walkthrough.switchMode.smartTitle")}>
            {t.rich("walkthrough.switchMode.smartBody", { strong, code })}
          </Callout>
        </Steps.Step>

        <Steps.Step title={t("walkthrough.audioPick.title")}>
          <p className="mb-3 text-gray-800">{t("walkthrough.audioPick.body")}</p>
          <Image
            src="/gpu-tpu/gpu-vm-07-audio-checklist.png"
            alt={t("walkthrough.audioPick.imageAlt")}
            width={900}
            height={500}
            className="rounded shadow-lg my-6"
          />
          <Callout variant="warning" title={t("walkthrough.audioPick.warnTitle")}>
            {t("walkthrough.audioPick.warnBody")}
          </Callout>
        </Steps.Step>

        <Steps.Step title={t("walkthrough.summary.title")}>
          <p className="mb-3 text-gray-800">{t("walkthrough.summary.body")}</p>
          <Image
            src="/gpu-tpu/gpu-vm-05-summary.png"
            alt={t("walkthrough.summary.imageAlt")}
            width={900}
            height={500}
            className="rounded shadow-lg my-6"
          />
        </Steps.Step>

        <Steps.Step title={t("walkthrough.hostApply.title")}>
          <p className="mb-3 text-gray-800">{t("walkthrough.hostApply.intro")}</p>
          <ul className="list-disc pl-6 space-y-1 text-gray-800 mb-3">
            {hostApplyItems.map((_, idx) => (
              <li key={idx}>{t.rich(`walkthrough.hostApply.items.${idx}`, { strong, code })}</li>
            ))}
          </ul>
        </Steps.Step>

        <Steps.Step title={t("walkthrough.vmApply.title")}>
          <p className="mb-3 text-gray-800">{t.rich("walkthrough.vmApply.body", { code })}</p>
          <CopyableCode
            code={`# Example — what ends up in the VM config after a GPU + audio passthrough
# (you don't type this, ProxMenux does it for you)

hostpci0: 0000:01:00.0,pcie=1,x-vga=1[,romfile=vbios_card.bin]   # GPU video
hostpci1: 0000:01:00.1,pcie=1                                    # GPU audio
vga: std

# NVIDIA only — hide the hypervisor from the guest driver (Code 43 fix)
cpu: host,hidden=1,flags=+pcid
args: -cpu 'host,+kvm_pv_unhalt,+kvm_pv_eoi,hv_vendor_id=NV43FIX,kvm=off'`}
            className="my-4"
          />
          <p className="mb-3 text-gray-800">{t.rich("walkthrough.vmApply.after1", { code, strong })}</p>
          <p className="mb-3 text-gray-800">{t.rich("walkthrough.vmApply.after2", { code })}</p>
        </Steps.Step>

        <Steps.Step title={t("walkthrough.reboot.title")}>
          <p className="mb-3 text-gray-800">{t("walkthrough.reboot.body")}</p>
          <Image
            src="/gpu-tpu/gpu-vm-06-reboot.png"
            alt={t("walkthrough.reboot.imageAlt")}
            width={900}
            height={500}
            className="rounded shadow-lg my-6"
          />
        </Steps.Step>
      </Steps>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("vendors.heading")}</h2>

      <h3 className="text-lg font-semibold mt-6 mb-2 text-gray-900">{t("vendors.nvidiaHeading")}</h3>
      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("vendors.nvidiaBody", { em, code })}
      </p>

      <h4 className="text-base font-semibold mt-4 mb-2 text-gray-900">{t("vendors.nvidiaMultiHeading")}</h4>
      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("vendors.nvidiaMultiBody", { strong, code })}
      </p>

      <h3 className="text-lg font-semibold mt-6 mb-2 text-gray-900">{t("vendors.amdHeading")}</h3>
      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("vendors.amdBody", { em, vendorResetLink })}
      </p>

      <h3 className="text-lg font-semibold mt-6 mb-2 text-gray-900">{t("vendors.intelHeading")}</h3>
      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("vendors.intelBody", { code, sriovLink })}
      </p>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("verification.heading")}</h2>

      <CopyableCode
        code={`# After reboot, confirm the GPU is bound to vfio-pci (not to the vendor driver)
lspci -nnk -d <vendor:device>
# Expect: "Kernel driver in use: vfio-pci"

# Start the VM and watch for successful binding
qm start <vmid>
journalctl -u qemu-server@<vmid>.service -f

# Inside the guest, drivers install normally and the GPU works as if it were physical.
# NVIDIA: verify with nvidia-smi inside the VM.
# AMD:    verify with Windows Device Manager / DXDiag.
# Intel:  verify display output / intel_gpu_top inside the VM.`}
        className="my-4"
      />

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("troubleshoot.heading")}</h2>

      <Callout variant="troubleshoot" title={t("troubleshoot.code43Title")}>
        {t.rich("troubleshoot.code43Body", { code })}
      </Callout>

      <Callout variant="troubleshoot" title={t("troubleshoot.amdResetTitle")}>
        {t.rich("troubleshoot.amdResetBody", { code, em })}
      </Callout>

      <Callout variant="troubleshoot" title={t("troubleshoot.stuckBootTitle")}>
        {t.rich("troubleshoot.stuckBootBody", { code })}
      </Callout>

      <Callout variant="troubleshoot" title={t("troubleshoot.darkTitle")}>
        {t.rich("troubleshoot.darkBody", { code })}
      </Callout>

      <CopyableCode
        code={`# Rescue — remove passthrough
# Remove hostpciN lines from the VM config
sed -i '/^hostpci[0-9]*:/d' /etc/pve/qemu-server/<vmid>.conf

# Unblacklist the host driver
rm -f /etc/modprobe.d/blacklist.conf /etc/modprobe.d/vfio.conf
# (if NVIDIA was involved)
mv /etc/udev/rules.d/70-nvidia.rules.proxmenux-disabled /etc/udev/rules.d/70-nvidia.rules 2>/dev/null

update-initramfs -u -k all
reboot`}
        className="my-4"
      />

      <Callout variant="tip" title={t("troubleshoot.logTitle")}>
        {t.rich("troubleshoot.logBody", { code })}
      </Callout>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("revert.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">{t("revert.intro")}</p>
      <CopyableCode
        code={`# Remove hostpci lines from the VM
qm set <vmid> --delete hostpci0
# (repeat for hostpci1, hostpci2, ... if multiple were added)

# ─── OPTIONAL — not required ──────────────────────────────────────
# The steps above already free the VM from the GPU. The lines below
# are only needed if you also want the host to use the GPU again
# (e.g. for LXC sharing or host-side transcoding). Skip this block
# if you simply want to stop passing the GPU to the VM.
# ──────────────────────────────────────────────────────────────────

# Release the GPU back to the host driver:
rm -f /etc/modprobe.d/vfio.conf
rm -f /etc/modprobe.d/blacklist.conf         # careful — this file may have other blacklists
# NVIDIA only — re-enable the udev rule + unpin the hard blacklist
mv /etc/udev/rules.d/70-nvidia.rules.proxmenux-disabled /etc/udev/rules.d/70-nvidia.rules 2>/dev/null
rm -f /etc/modprobe.d/nvidia-blacklist.conf

update-initramfs -u -k all
reboot`}
        className="my-4"
      />

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
