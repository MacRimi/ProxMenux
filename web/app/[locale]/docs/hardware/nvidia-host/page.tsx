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
  const t = await getTranslations({ locale, namespace: "docs.hardware.nvidiaHost.meta" })
  return {
    title: t("title"),
    description: t("description"),
  }
}

type MatrixRow = { kernel: string; pve: string; minCode: string; minTail: string }
type StringItem = string
type RelatedItem = { label: string; href: string; tail?: string }

export default async function NvidiaHostPage({
  params,
}: {
  params: Promise<{ locale: string }>
}) {
  const { locale } = await params
  setRequestLocale(locale)
  const t = await getTranslations({ locale, namespace: "docs.hardware.nvidiaHost" })

  const messages = (await getMessages({ locale })) as unknown as {
    docs: { hardware: { nvidiaHost: {
      walkthrough: {
        version: { rows: MatrixRow[] }
        prepare: { items: StringItem[] }
      }
      reinstallUninstall: { uninstallItems: StringItem[] }
      updates: { kindsItems: StringItem[] }
      related: { items: RelatedItem[] }
    } } }
  }
  const matrixRows = messages.docs.hardware.nvidiaHost.walkthrough.version.rows
  const prepareItems = messages.docs.hardware.nvidiaHost.walkthrough.prepare.items
  const uninstallItems = messages.docs.hardware.nvidiaHost.reinstallUninstall.uninstallItems
  const kindsItems = messages.docs.hardware.nvidiaHost.updates.kindsItems
  const relatedItems = messages.docs.hardware.nvidiaHost.related.items

  const code = (chunks: React.ReactNode) => <code>{chunks}</code>
  const strong = (chunks: React.ReactNode) => <strong>{chunks}</strong>
  const em = (chunks: React.ReactNode) => <em>{chunks}</em>
  const persistLink = (chunks: React.ReactNode) => (
    <a
      href="https://github.com/NVIDIA/nvidia-persistenced"
      target="_blank"
      rel="noopener noreferrer"
      className="text-blue-600 hover:underline inline-flex items-center gap-1"
    >
      {chunks}
      <ExternalLink className="w-3 h-3" />
    </a>
  )
  const patchLink = (chunks: React.ReactNode) => (
    <a
      href="https://github.com/keylase/nvidia-patch"
      target="_blank"
      rel="noopener noreferrer"
      className="text-blue-600 hover:underline inline-flex items-center gap-1"
    >
      {chunks}
      <ExternalLink className="w-3 h-3" />
    </a>
  )
  const patchTableLink = (chunks: React.ReactNode) => (
    <a
      href="https://github.com/keylase/nvidia-patch#patch-list"
      target="_blank"
      rel="noopener noreferrer"
      className="text-blue-700 hover:underline inline-flex items-center gap-1"
    >
      {chunks}
      <ExternalLink className="w-3 h-3" />
    </a>
  )
  const guideLink = (chunks: React.ReactNode) => (
    <Link href="/guides/nvidia-manual" className="text-blue-600 hover:underline">{chunks}</Link>
  )

  return (
    <div>
      <DocHeader
        title={t("header.title")}
        description={t("header.description")}
        section={t("header.section")}
        estimatedMinutes={20}
        scriptPath="gpu_tpu/nvidia_installer.sh"
      />

      <Callout variant="info" title={t("intro.title")}>
        {t.rich("intro.body", { code })}
      </Callout>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("who.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("who.body", { strong, em })}
      </p>

      <Prerequisites
        title={t("prereqs.title")}
        items={[
          { label: <>{t.rich("prereqs.gpu", { strong })}</>, check: t("prereqs.gpuCheck") },
          { label: <>{t.rich("prereqs.notVm", { strong })}</> },
          { label: <>{t.rich("prereqs.internet", { code })}</> },
          { label: <>{t.rich("prereqs.space", { strong, code })}</> },
        ]}
      />

      <Callout variant="warning" title={t("vmWarn.title")}>
        {t.rich("vmWarn.body", { code })}
      </Callout>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("running.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("running.body", { strong })}
      </p>

      <Image
        src="/gpu-tpu/nvidia-host-01-menu-entry.png"
        alt={t("running.imageAlt")}
        width={900}
        height={500}
        className="rounded shadow-lg my-6"
      />

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("howRuns.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">{t("howRuns.body")}</p>

      <pre className="bg-gray-100 text-gray-800 p-4 rounded-md overflow-x-auto text-sm my-4 border border-gray-200 leading-snug">
{`┌─────────────────────────────────────────────┐
│  PHASE 1 — Detect, validate, pick version   │
│  (nothing touched yet)                      │
└──────────────────┬──────────────────────────┘
                   ▼
      ┌────────────┴────────────┐
      ▼                         ▼
  lspci detects             GPU bound to
  NVIDIA GPU(s)             vfio-pci? ──→ Abort
      │                         │        (remove VM
      │                         No        passthrough first)
      ▼
  nvidia-smi: driver already installed?
      │
      ├─ No  → continue (fresh install)
      └─ Yes → ask: Reinstall/Update  OR  Remove
                     │
                     ├─ Remove    → complete uninstall
                     │               + reboot prompt
                     └─ Reinstall → continue
      │
      ▼
  Show install overview
  (GPU list + current driver +
   LXC containers with NVIDIA passthrough)
      │
      ▼
  Kernel-compat filter:
  ├─ Kernel 6.17+   → driver 580.82.07+
  ├─ Kernel 6.8–16  → driver 550+
  ├─ Kernel 6.2–7   → driver 535+
  └─ Kernel 5.15+   → driver 470+
      │
      ▼
  User picks version (or "Latest")
                   │
     ┌─────── Cancel   OR   Confirm ────┐
     ▼                                  ▼
 Exit, nothing            ┌─────────────┴──────────────┐
 was changed              │  PHASE 2 — Install driver  │
                          └─────────────┬──────────────┘
                                        ▼
                          Prepare host:
                          ├─ Install pve-headers-$(uname -r)
                          ├─ Install build-essential + dkms
                          ├─ Blacklist nouveau + unload
                          │  └ /etc/modprobe.d/nouveau-blacklist.conf
                          ├─ Write modules-load config
                          │  └ /etc/modules-load.d/nvidia-vfio.conf
                          ├─ Stop/disable nvidia services
                          └─ Unload residual nvidia modules

                          If different version already present:
                          └─ clean uninstall first (apt purge,
                             remove DKMS entries)
                                        │
                                        ▼
                          Download NVIDIA .run installer
                          to /opt/nvidia (validate size +
                          executable signature)
                                        │
                                        ▼
                          Run installer with --dkms
                          --disable-nouveau --no-nouveau-check
                                        │
                                        ▼
                          Install udev rules
                          └─ /etc/udev/rules.d/70-nvidia.rules
                          + clone NVIDIA/nvidia-persistenced
                                        │
                                        ▼
                          update-initramfs -u -k all
                                        │
                                        ▼
                          nvidia-smi — verify driver loaded
                                        │
                        ┌───────────────┴───────────────┐
                        │  PHASE 3 — Optional extras    │
                        └───────────────┬───────────────┘
                                        ▼
                          LXC containers with NVIDIA?
                          ├─ Yes → offer driver propagation
                          │        (Alpine: apk · Arch: pacman ·
                          │         Debian/others: extract .run)
                          └─ No  → skip
                                        │
                                        ▼
                          keylase/nvidia-patch (NVENC limit)?
                          ├─ Yes → clone + apply
                          └─ No  → skip
                                        │
                                        ▼
                          Reboot prompt — required to finalize
                          nouveau blacklist + load new module`}
      </pre>

      <Steps>
        <Steps.Step title={t("walkthrough.detect.title")}>
          <p className="mb-3 text-gray-800">{t.rich("walkthrough.detect.body1", { em })}</p>
          <p className="mb-3 text-gray-800">{t("walkthrough.detect.body2")}</p>
          <Image
            src="/gpu-tpu/nvidia-host-02-overview.png"
            alt={t("walkthrough.detect.imageAlt")}
            width={900}
            height={500}
            className="rounded shadow-lg my-6"
          />
        </Steps.Step>

        <Steps.Step title={t("walkthrough.version.title")}>
          <p className="mb-3 text-gray-800">{t.rich("walkthrough.version.body1", { strong, em })}</p>
          <p className="mb-3 text-gray-800">{t("walkthrough.version.body2")}</p>

          <div className="my-4 overflow-x-auto">
            <table className="min-w-full border border-gray-200 text-sm">
              <thead className="bg-gray-100">
                <tr>
                  <th className="border border-gray-200 px-3 py-2 text-left text-gray-900">{t("walkthrough.version.headerKernel")}</th>
                  <th className="border border-gray-200 px-3 py-2 text-left text-gray-900">{t("walkthrough.version.headerPve")}</th>
                  <th className="border border-gray-200 px-3 py-2 text-left text-gray-900">{t("walkthrough.version.headerMin")}</th>
                </tr>
              </thead>
              <tbody className="text-gray-800">
                {matrixRows.map((row, idx) => (
                  <tr key={idx}>
                    <td className="border border-gray-200 px-3 py-2">{row.kernel}</td>
                    <td className="border border-gray-200 px-3 py-2">{row.pve}</td>
                    <td className="border border-gray-200 px-3 py-2">
                      <code>{row.minCode}</code>{row.minTail}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <Callout variant="tip" title={t("walkthrough.version.whyTitle")}>
            {t("walkthrough.version.whyBody")}
          </Callout>

          <Image
            src="/gpu-tpu/nvidia-host-03-version-menu.png"
            alt={t("walkthrough.version.imageAlt")}
            width={900}
            height={500}
            className="rounded shadow-lg my-6"
          />
        </Steps.Step>

        <Steps.Step title={t("walkthrough.uninstall.title")}>
          <p className="mb-3 text-gray-800">{t.rich("walkthrough.uninstall.body", { code })}</p>
        </Steps.Step>

        <Steps.Step title={t("walkthrough.prepare.title")}>
          <p className="mb-3 text-gray-800">{t("walkthrough.prepare.body")}</p>
          <ul className="list-disc pl-6 space-y-1 text-gray-800">
            {prepareItems.map((_, idx) => (
              <li key={idx}>{t.rich(`walkthrough.prepare.items.${idx}`, { code })}</li>
            ))}
          </ul>
        </Steps.Step>

        <Steps.Step title={t("walkthrough.download.title")}>
          <p className="mb-3 text-gray-800">{t.rich("walkthrough.download.body", { code })}</p>
          <CopyableCode
            code={`# What ProxMenux runs under the hood (you don't have to type this):
sh NVIDIA-Linux-x86_64-<version>.run \\
  --no-questions \\
  --ui=none \\
  --disable-nouveau \\
  --no-nouveau-check \\
  --dkms`}
            className="my-4"
          />
          <Image
            src="/gpu-tpu/nvidia-host-04-install-progress.png"
            alt={t("walkthrough.download.imageAlt")}
            width={900}
            height={500}
            className="rounded shadow-lg my-6"
          />
        </Steps.Step>

        <Steps.Step title={t("walkthrough.persist.title")}>
          <p className="mb-3 text-gray-800">{t.rich("walkthrough.persist.body", { code, persistLink })}</p>
        </Steps.Step>

        <Steps.Step title={t("walkthrough.nvenc.title")}>
          <p className="mb-3 text-gray-800">{t.rich("walkthrough.nvenc.body", { strong, patchLink })}</p>
          <Callout variant="warning" title={t("walkthrough.nvenc.supportTitle")}>
            {t.rich("walkthrough.nvenc.supportBody", { patchTableLink })}
          </Callout>
        </Steps.Step>

        <Steps.Step title={t("walkthrough.propagate.title")}>
          <p className="mb-3 text-gray-800">{t.rich("walkthrough.propagate.body1", { code, strong })}</p>
          <p className="mb-3 text-gray-800">{t.rich("walkthrough.propagate.body2", { code })}</p>
          <Image
            src="/gpu-tpu/nvidia-host-05-lxc-update.png"
            alt={t("walkthrough.propagate.imageAlt")}
            width={900}
            height={500}
            className="rounded shadow-lg my-6"
          />
        </Steps.Step>

        <Steps.Step title={t("walkthrough.reboot.title")}>
          <p className="mb-3 text-gray-800">{t.rich("walkthrough.reboot.body", { code, strong })}</p>
        </Steps.Step>
      </Steps>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("reinstallUninstall.heading")}</h2>

      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("reinstallUninstall.intro", { code })}
      </p>

      <figure className="my-4">
        <Image
          src="/gpu-tpu/nvidia-host-06-action-menu.png"
          alt={t("reinstallUninstall.imageAlt")}
          width={1200}
          height={680}
          className="rounded-lg border border-gray-200 shadow-sm w-full h-auto"
        />
        <figcaption className="text-sm text-gray-500 mt-2 text-center italic">
          {t("reinstallUninstall.imageCaption")}
        </figcaption>
      </figure>

      <h3 className="text-lg font-semibold mt-6 mb-2 text-gray-900">{t("reinstallUninstall.reinstallHeading")}</h3>
      <p className="mb-4 text-gray-800 leading-relaxed">{t("reinstallUninstall.reinstallBody")}</p>

      <h3 className="text-lg font-semibold mt-6 mb-2 text-gray-900">{t("reinstallUninstall.uninstallHeading")}</h3>
      <p className="mb-4 text-gray-800 leading-relaxed">{t("reinstallUninstall.uninstallIntro")}</p>
      <ul className="list-disc pl-6 mb-4 text-gray-800 leading-relaxed space-y-1">
        {uninstallItems.map((_, idx) => (
          <li key={idx}>{t.rich(`reinstallUninstall.uninstallItems.${idx}`, { code })}</li>
        ))}
      </ul>

      <Callout variant="warning" title={t("reinstallUninstall.lxcWarnTitle")}>
        {t("reinstallUninstall.lxcWarnBody")}
      </Callout>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("updates.heading")}</h2>

      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("updates.body", { code })}
      </p>

      <h3 className="text-lg font-semibold mt-6 mb-2 text-gray-900">{t("updates.kindsHeading")}</h3>
      <ul className="list-disc pl-6 mb-4 text-gray-800 leading-relaxed space-y-1">
        {kindsItems.map((_, idx) => (
          <li key={idx}>{t.rich(`updates.kindsItems.${idx}`, { strong })}</li>
        ))}
      </ul>

      <Callout variant="info" title={t("updates.antiTitle")}>
        {t("updates.antiBody")}
      </Callout>

      <Callout variant="info" title={t("updates.applyTitle")}>
        {t.rich("updates.applyBody", { strong })}
      </Callout>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("verify.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">{t("verify.intro")}</p>
      <CopyableCode
        code={`nvidia-smi`}
        className="my-4"
      />
      <p className="mb-4 text-gray-800 leading-relaxed">{t("verify.after")}</p>
      <CopyableCode
        code={`systemctl status nvidia-persistenced`}
        className="my-4"
      />

      <Image
        src="/gpu-tpu/nvidia-host-06-nvidia-smi-ok.png"
        alt={t("verify.imageAlt")}
        width={900}
        height={500}
        className="rounded shadow-lg my-6"
      />

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("troubleshoot.heading")}</h2>

      <Callout variant="troubleshoot" title={t("troubleshoot.smiFailTitle")}>
        {t.rich("troubleshoot.smiFailBody", { strong, code })}
      </Callout>

      <Callout variant="troubleshoot" title={t("troubleshoot.lxcMissTitle")}>
        {t.rich("troubleshoot.lxcMissBody", { code })}
      </Callout>

      <Callout variant="tip" title={t("troubleshoot.logTitle")}>
        {t.rich("troubleshoot.logBody", { code })}
      </Callout>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("manualSteps.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("manualSteps.body", { code, guideLink })}
      </p>

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
