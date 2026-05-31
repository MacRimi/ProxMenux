import type { Metadata } from "next"
import { getTranslations, getMessages, setRequestLocale } from "next-intl/server"
import { Link } from "@/i18n/navigation"
import Image from "next/image"
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
  const t = await getTranslations({ locale, namespace: "docs.hardware.igpuAccelerationLxc.meta" })
  return {
    title: t("title"),
    description: t("description"),
  }
}

type CompareRow = { feature: string; lxc: string; vm: string }
type PreflightItem = string
type DistroRow = { distro: string; intel: string; nvidia: string }
type RelatedItem = { label: string; href: string; tail?: string }

export default async function AddGpuToLxcPage({
  params,
}: {
  params: Promise<{ locale: string }>
}) {
  const { locale } = await params
  setRequestLocale(locale)
  const t = await getTranslations({ locale, namespace: "docs.hardware.igpuAccelerationLxc" })

  const messages = (await getMessages({ locale })) as unknown as {
    docs: { hardware: { igpuAccelerationLxc: {
      compare: { rows: CompareRow[] }
      walkthrough: {
        preflight: { items: PreflightItem[] }
        installDrivers: { rows: DistroRow[] }
      }
      related: { items: RelatedItem[] }
    } } }
  }
  const compareRows = messages.docs.hardware.igpuAccelerationLxc.compare.rows
  const preflightItems = messages.docs.hardware.igpuAccelerationLxc.walkthrough.preflight.items
  const distroRows = messages.docs.hardware.igpuAccelerationLxc.walkthrough.installDrivers.rows
  const relatedItems = messages.docs.hardware.igpuAccelerationLxc.related.items

  const code = (chunks: React.ReactNode) => <code>{chunks}</code>
  const strong = (chunks: React.ReactNode) => <strong>{chunks}</strong>
  const em = (chunks: React.ReactNode) => <em>{chunks}</em>
  const vmLink = (chunks: React.ReactNode) => (
    <Link href="/docs/hardware/gpu-vm-passthrough" className="text-blue-700 hover:underline">{chunks}</Link>
  )
  const switchLink = (chunks: React.ReactNode) => (
    <Link href="/docs/hardware/switch-gpu-mode" className="text-blue-700 hover:underline">{chunks}</Link>
  )
  const nvidiaLink = (chunks: React.ReactNode) => (
    <Link href="/docs/hardware/nvidia-host" className="text-blue-700 hover:underline">{chunks}</Link>
  )

  return (
    <div>
      <DocHeader
        title={t("header.title")}
        description={t("header.description")}
        section={t("header.section")}
        estimatedMinutes={10}
        scriptPath="gpu_tpu/add_gpu_lxc.sh"
      />

      <Callout variant="info" title={t("intro.title")}>
        {t.rich("intro.body", { code })}
      </Callout>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("compare.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("compare.intro", { em, vmLink })}
      </p>
      <div className="my-4 overflow-x-auto">
        <table className="min-w-full border border-gray-200 text-sm">
          <thead className="bg-gray-100">
            <tr>
              <th className="border border-gray-200 px-3 py-2 text-left text-gray-900">{t("compare.headerFeature")}</th>
              <th className="border border-gray-200 px-3 py-2 text-left text-gray-900">{t("compare.headerLxc")}</th>
              <th className="border border-gray-200 px-3 py-2 text-left text-gray-900">
                <Link href="/docs/hardware/gpu-vm-passthrough" className="text-blue-700 hover:underline">
                  {t("compare.headerVm")}
                </Link>
              </th>
            </tr>
          </thead>
          <tbody className="text-gray-800">
            {compareRows.map((row, idx) => (
              <tr key={idx}>
                <td className="border border-gray-200 px-3 py-2">{row.feature}</td>
                <td className="border border-gray-200 px-3 py-2">{row.lxc}</td>
                <td className="border border-gray-200 px-3 py-2">{row.vm}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <Prerequisites
        title={t("prereqs.title")}
        items={[
          {
            label: <>{t.rich("prereqs.gpu", { strong, code })}</>,
            check: t("prereqs.gpuCheck"),
          },
          {
            label: <>{t.rich("prereqs.vfio", { strong, switchLink })}</>,
          },
          {
            label: <>{t.rich("prereqs.nvidia", { strong, nvidiaLink })}</>,
            check: t("prereqs.nvidiaCheck"),
          },
          {
            label: <>{t.rich("prereqs.container", { strong })}</>,
          },
        ]}
      />

      <Callout variant="warning" title={t("unpriv.title")}>
        {t.rich("unpriv.body", { code })}
      </Callout>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("running.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("running.body", { strong })}
      </p>

      <Image
        src="/gpu-tpu/gpu-lxc-01-menu-entry.png"
        alt={t("running.imageAlt")}
        width={900}
        height={500}
        className="rounded shadow-lg my-6"
      />

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("howRuns.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">{t("howRuns.body")}</p>

      <pre className="bg-gray-100 text-gray-800 p-4 rounded-md overflow-x-auto text-sm my-4 border border-gray-200 leading-snug">
{`┌─────────────────────────────────────────────┐
│  PHASE 1 — Detect, select, validate         │
│  (nothing touched yet)                      │
└──────────────────┬──────────────────────────┘
                   ▼
  lspci detects Intel / AMD / NVIDIA GPU(s)
  (NVIDIA: also check nvidia module loaded +
   nvidia-smi, capture host driver version)
                   │
                   ▼
  User picks LXC container from the list
                   │
                   ▼
  User selects which GPU(s) to add
  (checklist; auto-selects if only one)
                   │
                   ▼
  Pre-flight checks
  ├─ Not in SR-IOV (VF / active PF) → block
  ├─ Bound to vfio-pci? → offer Switch Mode, exit
  └─ Already configured in this CT? → filter out
      (skip duplicates, warn if partial)
                   │
     ┌─────── Cancel   OR   Confirm ────┐
     ▼                                  ▼
 Exit, nothing       ┌──────────────────┴──────────────────┐
 was changed         │  PHASE 2 — Configure + install      │
                     └──────────────────┬──────────────────┘
                                        ▼
                       Stop container (if running)
                                        │
                                        ▼
                       Write LXC config (/etc/pve/lxc/<ctid>.conf):
                       ├─ Intel / AMD iGPU:
                       │    dev<N>: /dev/dri/card*   gid=video
                       │    dev<N>: /dev/dri/renderD* gid=render
                       ├─ AMD with ROCm (if /dev/kfd):
                       │    dev<N>: /dev/kfd  gid=render
                       └─ NVIDIA:
                            dev<N>: /dev/nvidia0..N
                            dev<N>: /dev/nvidiactl · nvidia-uvm*
                            dev<N>: /dev/nvidia-modeset
                            dev<N>: /dev/nvidia-caps/* (if exists)
                                        │
                                        ▼
                       Install GPU guard hookscript
                       (same one used by VM passthrough, if
                        available — prevents conflicts on start/stop)
                                        │
                                        ▼
                       Start container + wait for readiness
                       (pct exec — true, up to ~30 s)
                                        │
                                        ▼
                       Install userspace drivers inside CT
                       (distro auto-detected)
                       ├─ Intel  → apk/pacman/apt
                       │           (intel-media-driver,
                       │            libva-utils, opencl-icd)
                       ├─ AMD    → Mesa VA drivers
                       │           (mesa-va-drivers, libva)
                       └─ NVIDIA →
                          ├─ Alpine:  apk add nvidia-utils
                          ├─ Arch:    pacman -S nvidia-utils
                          └─ Debian/Ubuntu/others:
                             host .run is pre-extracted, packed,
                             pct push'd into the container, run
                             with --no-kernel-modules --no-dkms
                                        │
                                        ▼
                       Align GIDs in /etc/group inside CT
                       (video=44, render=104 to match host)
                                        │
                                        ▼
                       Restore container state
                       (stop if it was stopped before)
                                        │
                                        ▼
                       Show summary + nvidia-smi output
                       (if NVIDIA) + log path`}
      </pre>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("walkthrough.heading")}</h2>

      <Steps>
        <Steps.Step title={t("walkthrough.detect.title")}>
          <p className="mb-3 text-gray-800">{t.rich("walkthrough.detect.body", { code })}</p>
          <Callout variant="tip" title={t("walkthrough.detect.tipTitle")}>
            {t.rich("walkthrough.detect.tipBody", { nvidiaLink })}
          </Callout>
        </Steps.Step>

        <Steps.Step title={t("walkthrough.pickCt.title")}>
          <p className="mb-3 text-gray-800">{t("walkthrough.pickCt.body")}</p>
          <Image
            src="/gpu-tpu/select-container.png"
            alt={t("walkthrough.pickCt.imageAlt")}
            width={800}
            height={400}
            className="rounded shadow-lg my-4"
          />
        </Steps.Step>

        <Steps.Step title={t("walkthrough.selectGpu.title")}>
          <p className="mb-3 text-gray-800">{t("walkthrough.selectGpu.body")}</p>
          <Image
            src="/gpu-tpu/gpu-lxc-02-gpu-select.png"
            alt={t("walkthrough.selectGpu.imageAlt")}
            width={900}
            height={500}
            className="rounded shadow-lg my-4"
          />
        </Steps.Step>

        <Steps.Step title={t("walkthrough.preflight.title")}>
          <Image
            src="/gpu-tpu/gpu-lxc-03-switch-mode.png"
            alt={t("walkthrough.preflight.imageAlt")}
            width={900}
            height={500}
            className="rounded shadow-lg my-4"
          />
          <p className="mb-3 text-gray-800">{t("walkthrough.preflight.intro")}</p>
          <ul className="list-disc pl-6 space-y-1 text-gray-800 mb-3">
            {preflightItems.map((_, idx) => (
              <li key={idx}>{t.rich(`walkthrough.preflight.items.${idx}`, { strong, code, switchLink })}</li>
            ))}
          </ul>
        </Steps.Step>

        <Steps.Step title={t("walkthrough.applyConfig.title")}>
          <p className="mb-3 text-gray-800">{t.rich("walkthrough.applyConfig.body1", { code })}</p>
          <p className="mb-3 text-gray-800">{t("walkthrough.applyConfig.body2")}</p>
          <CopyableCode
            code={`# in /etc/pve/lxc/<ctid>.conf
dev0: /dev/dri/card0,gid=44
dev1: /dev/dri/renderD128,gid=104
dev2: /dev/nvidia0,gid=44
dev3: /dev/nvidiactl,gid=44
dev4: /dev/nvidia-uvm,gid=44
dev5: /dev/nvidia-uvm-tools,gid=44
dev6: /dev/nvidia-modeset,gid=44`}
            className="my-4"
          />
        </Steps.Step>

        <Steps.Step title={t("walkthrough.installDrivers.title")}>
          <p className="mb-3 text-gray-800">{t.rich("walkthrough.installDrivers.body", { code })}</p>
          <div className="my-4 overflow-x-auto">
            <table className="min-w-full border border-gray-200 text-sm">
              <thead className="bg-gray-100">
                <tr>
                  <th className="border border-gray-200 px-3 py-2 text-left text-gray-900">{t("walkthrough.installDrivers.headerDistro")}</th>
                  <th className="border border-gray-200 px-3 py-2 text-left text-gray-900">{t("walkthrough.installDrivers.headerInt")}</th>
                  <th className="border border-gray-200 px-3 py-2 text-left text-gray-900">{t("walkthrough.installDrivers.headerNvidia")}</th>
                </tr>
              </thead>
              <tbody className="text-gray-800">
                {distroRows.map((row, idx) => (
                  <tr key={idx}>
                    <td className="border border-gray-200 px-3 py-2">{row.distro}</td>
                    <td className="border border-gray-200 px-3 py-2"><code>{row.intel}</code></td>
                    <td className="border border-gray-200 px-3 py-2"><code>{row.nvidia}</code></td>
                  </tr>
                ))}
                <tr>
                  <td className="border border-gray-200 px-3 py-2">{t("walkthrough.installDrivers.debianDistro")}</td>
                  <td className="border border-gray-200 px-3 py-2"><code>{t("walkthrough.installDrivers.debianIntel")}</code></td>
                  <td className="border border-gray-200 px-3 py-2">{t.rich("walkthrough.installDrivers.debianNvidia", { code })}</td>
                </tr>
              </tbody>
            </table>
          </div>
          <Callout variant="tip" title={t("walkthrough.installDrivers.whyTitle")}>
            {t.rich("walkthrough.installDrivers.whyBody", { code, strong })}
          </Callout>
        </Steps.Step>

        <Steps.Step title={t("walkthrough.alignGids.title")}>
          <p className="mb-3 text-gray-800">{t.rich("walkthrough.alignGids.body1", { code })}</p>
          <p className="mb-3 text-gray-800">{t("walkthrough.alignGids.body2")}</p>
        </Steps.Step>
      </Steps>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("vendors.heading")}</h2>

      <h3 className="text-lg font-semibold mt-6 mb-2 text-gray-900">{t("vendors.intelHeading")}</h3>
      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("vendors.intelBody", { em, code })}
      </p>

      <h3 className="text-lg font-semibold mt-6 mb-2 text-gray-900">{t("vendors.amdHeading")}</h3>
      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("vendors.amdBody", { code })}
      </p>

      <h3 className="text-lg font-semibold mt-6 mb-2 text-gray-900">{t("vendors.nvidiaHeading")}</h3>
      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("vendors.nvidiaBody", { code, strong })}
      </p>

      <Callout variant="warning" title={t("vendors.updateTitle")}>
        {t.rich("vendors.updateBody", { code, nvidiaLink })}
      </Callout>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("verification.heading")}</h2>
      <p className="mb-3 text-gray-800 leading-relaxed">{t("verification.body")}</p>
      <CopyableCode
        code={`# Enter the container
pct enter <ctid>

# Intel / AMD — check DRI nodes and VA-API
ls -l /dev/dri/
vainfo

# NVIDIA — check nvidia-smi matches the host version
nvidia-smi
nvidia-smi --query-gpu=driver_version --format=csv,noheader

# Check group alignment
getent group video render`}
        className="my-4"
      />

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("troubleshoot.heading")}</h2>

      <Callout variant="troubleshoot" title={t("troubleshoot.mismatchTitle")}>
        {t.rich("troubleshoot.mismatchBody", { code })}
      </Callout>

      <Callout variant="troubleshoot" title={t("troubleshoot.denyTitle")}>
        {t.rich("troubleshoot.denyBody", { code })}
      </Callout>

      <Callout variant="troubleshoot" title={t("troubleshoot.vainfoTitle")}>
        {t.rich("troubleshoot.vainfoBody", { code })}
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
