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
  const t = await getTranslations({ locale, namespace: "docs.hardware.installCoralTpuHost.meta" })
  return {
    title: t("title"),
    description: t("description"),
  }
}

type StringItem = string
type RelatedItem = { label: string; href: string; tail?: string }

export default async function InstallCoralTPUHostPage({
  params,
}: {
  params: Promise<{ locale: string }>
}) {
  const { locale } = await params
  setRequestLocale(locale)
  const t = await getTranslations({ locale, namespace: "docs.hardware.installCoralTpuHost" })

  const messages = (await getMessages({ locale })) as unknown as {
    docs: { hardware: { installCoralTpuHost: {
      walkthrough: {
        detect: { items: StringItem[] }
        pcie: { items: StringItem[]; kernelPatches: StringItem[]; afterItems: StringItem[] }
        usb: { items: StringItem[] }
      }
      reinstallUninstall: { uninstallItems: StringItem[] }
      related: { items: RelatedItem[] }
    } } }
  }
  const detectItems = messages.docs.hardware.installCoralTpuHost.walkthrough.detect.items
  const pcieItems = messages.docs.hardware.installCoralTpuHost.walkthrough.pcie.items
  const kernelPatches = messages.docs.hardware.installCoralTpuHost.walkthrough.pcie.kernelPatches
  const pcieAfterItems = messages.docs.hardware.installCoralTpuHost.walkthrough.pcie.afterItems
  const usbItems = messages.docs.hardware.installCoralTpuHost.walkthrough.usb.items
  const uninstallItems = messages.docs.hardware.installCoralTpuHost.reinstallUninstall.uninstallItems
  const relatedItems = messages.docs.hardware.installCoralTpuHost.related.items

  const code = (chunks: React.ReactNode) => <code>{chunks}</code>
  const strong = (chunks: React.ReactNode) => <strong>{chunks}</strong>
  const em = (chunks: React.ReactNode) => <em>{chunks}</em>
  const lxcLink = (chunks: React.ReactNode) => (
    <Link href="/docs/hardware/coral-tpu-lxc" className="text-blue-700 hover:underline">{chunks}</Link>
  )
  const feranickLink = (chunks: React.ReactNode) => (
    <a
      href="https://github.com/feranick/gasket-driver"
      target="_blank"
      rel="noopener noreferrer"
      className="text-blue-600 hover:underline inline-flex items-center gap-1"
    >
      {chunks}
      <ExternalLink className="w-3 h-3" />
    </a>
  )
  const googleLink = (chunks: React.ReactNode) => (
    <a
      href="https://github.com/google/gasket-driver"
      target="_blank"
      rel="noopener noreferrer"
      className="text-blue-600 hover:underline inline-flex items-center gap-1"
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
        estimatedMinutes={10}
        scriptPath="gpu_tpu/install_coral.sh"
      />

      <Callout variant="info" title={t("intro.title")}>
        {t.rich("intro.body", { strong, code })}
      </Callout>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("which.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">{t("which.body")}</p>

      <div className="my-4 overflow-x-auto">
        <table className="min-w-full border border-gray-200 text-sm">
          <thead className="bg-gray-100">
            <tr>
              <th className="border border-gray-200 px-3 py-2 text-left text-gray-900">{t("which.headerForm")}</th>
              <th className="border border-gray-200 px-3 py-2 text-left text-gray-900">{t("which.headerDetect")}</th>
              <th className="border border-gray-200 px-3 py-2 text-left text-gray-900">{t("which.headerInstall")}</th>
              <th className="border border-gray-200 px-3 py-2 text-left text-gray-900">{t("which.headerReboot")}</th>
            </tr>
          </thead>
          <tbody className="text-gray-800">
            <tr>
              <td className="border border-gray-200 px-3 py-2">
                <strong>{t("which.pcieForm")}</strong>
                <br />
                <span className="text-xs text-gray-600">{t("which.pcieFormSub")}</span>
              </td>
              <td className="border border-gray-200 px-3 py-2">{t.rich("which.pcieDetect", { code })}</td>
              <td className="border border-gray-200 px-3 py-2">{t("which.pcieInstall")}</td>
              <td className="border border-gray-200 px-3 py-2"><strong>{t("which.pcieReboot")}</strong></td>
            </tr>
            <tr>
              <td className="border border-gray-200 px-3 py-2">
                <strong>{t("which.usbForm")}</strong>
                <br />
                <span className="text-xs text-gray-600">{t("which.usbFormSub")}</span>
              </td>
              <td className="border border-gray-200 px-3 py-2">{t.rich("which.usbDetect", { code })}</td>
              <td className="border border-gray-200 px-3 py-2">{t.rich("which.usbInstall", { code })}</td>
              <td className="border border-gray-200 px-3 py-2">{t("which.usbReboot")}</td>
            </tr>
          </tbody>
        </table>
      </div>

      <Prerequisites
        title={t("prereqs.title")}
        items={[
          { label: <>{t.rich("prereqs.coral", { strong })}</>, check: t("prereqs.coralCheck") },
          { label: <>{t.rich("prereqs.internet", { strong, code })}</> },
          { label: <>{t.rich("prereqs.headers", { strong, code })}</> },
          { label: <>{t.rich("prereqs.reboot", { strong })}</> },
        ]}
      />

      <Callout variant="tip" title={t("hostPrepTip.title")}>
        {t.rich("hostPrepTip.body", { em, lxcLink })}
      </Callout>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("running.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("running.body", { strong })}
      </p>

      <Image
        src="/gpu-tpu/coral-host-01-menu-entry.png"
        alt={t("running.imageAlt")}
        width={900}
        height={500}
        className="rounded shadow-lg my-6"
      />

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("howRuns.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">{t("howRuns.body")}</p>

      <pre className="bg-gray-100 text-gray-800 p-4 rounded-md overflow-x-auto text-sm my-4 border border-gray-200 leading-snug">
{`┌────────────────────────────────────────────────┐
│ 1. detect_coral_hardware()                     │
│    → count PCIe (vendor 1ac1) + USB (IDs)      │
└────────────────┬───────────────────────────────┘
                 ▼
     ┌───────────┴───────────┐
     │                       │
     ▼                       ▼
  None                 At least one
     │                       │
     ▼                       ▼
 Dialog            pre_install_prompt()
 "No Coral" →      shows what was detected
  exit 0           and what will be installed
                           │
                           ▼
          ┌────────────────┴────────────────┐
          │                                 │
          ▼                                 ▼
   PCIe detected?                    USB detected?
          │                                 │
        Yes                               Yes
          ▼                                 ▼
 install_gasket_apex_dkms        install_libedgetpu_runtime
 ├─ cleanup_broken_gasket_dkms   ├─ add Google GPG keyring
 ├─ apt install deps             │    /etc/apt/keyrings/...
 │  (git, dkms, build-essential, ├─ add APT repo (signed-by)
 │   proxmox-headers-$(uname-r)) │    /etc/apt/sources.list.d/
 ├─ clone feranick/gasket-driver │     coral-edgetpu.list
 │   (google fallback + patches) ├─ apt install libedgetpu1-std
 ├─ copy src/ → /usr/src/        └─ udev reload + trigger
 │   gasket-1.0/
 ├─ generate dkms.conf
 ├─ dkms add / build / install
 └─ modprobe gasket + apex
 + ensure_apex_group_and_udev
          │                                 │
          └────────────────┬────────────────┘
                           ▼
          ┌────────────────┴────────────────┐
          │                                 │
       PCIe ran?                       USB only
          │                                 │
          ▼                                 ▼
  restart_prompt()          "No reboot required"
  (reboot required to       (runtime + udev rules
   load fresh kernel         are already active)
   module cleanly)`}
      </pre>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("walkthrough.heading")}</h2>

      <Steps>
        <Steps.Step title={t("walkthrough.detect.title")}>
          <p className="mb-3 text-gray-800">{t.rich("walkthrough.detect.body", { code, strong })}</p>
          <ul className="list-disc pl-6 space-y-1 text-gray-800 mb-3">
            {detectItems.map((_, idx) => (
              <li key={idx}>{t.rich(`walkthrough.detect.items.${idx}`, { code, em })}</li>
            ))}
          </ul>
          <p className="mb-3 text-gray-800">{t("walkthrough.detect.outro")}</p>
        </Steps.Step>

        <Steps.Step title={t("walkthrough.prompt.title")}>
          <p className="mb-3 text-gray-800">{t("walkthrough.prompt.body")}</p>
          <Image
            src="/gpu-tpu/coral-host-02-pre-install.png"
            alt={t("walkthrough.prompt.imageAlt")}
            width={900}
            height={500}
            className="rounded shadow-lg my-4"
          />
        </Steps.Step>

        <Steps.Step title={t("walkthrough.pcie.title")}>
          <p className="mb-3 text-gray-800">{t("walkthrough.pcie.body")}</p>
          <ol className="list-decimal pl-6 space-y-1 text-gray-800 mb-3">
            {pcieItems.map((_, idx) => (
              <li key={idx}>{t.rich(`walkthrough.pcie.items.${idx}`, { strong, code })}</li>
            ))}
            <li>
              {t.rich("walkthrough.pcie.cloneIntro", { strong, feranickLink, googleLink })}
              <ul className="list-disc pl-6 mt-1">
                {kernelPatches.map((_, idx) => (
                  <li key={idx}>{t.rich(`walkthrough.pcie.kernelPatches.${idx}`, { code })}</li>
                ))}
              </ul>
            </li>
            {pcieAfterItems.map((_, idx) => (
              <li key={`after-${idx}`}>{t.rich(`walkthrough.pcie.afterItems.${idx}`, { strong, code })}</li>
            ))}
          </ol>
          <Image
            src="/gpu-tpu/coral-host-03-dkms-build.png"
            alt={t("walkthrough.pcie.imageAlt")}
            width={900}
            height={500}
            className="rounded shadow-lg my-4"
          />
        </Steps.Step>

        <Steps.Step title={t("walkthrough.usb.title")}>
          <p className="mb-3 text-gray-800">{t("walkthrough.usb.body")}</p>
          <ol className="list-decimal pl-6 space-y-1 text-gray-800 mb-3">
            {usbItems.map((_, idx) => (
              <li key={idx}>{t.rich(`walkthrough.usb.items.${idx}`, { strong, code })}</li>
            ))}
          </ol>
          <Callout variant="tip" title={t("walkthrough.usb.stdTitle")}>
            {t.rich("walkthrough.usb.stdBody", { code })}
          </Callout>
        </Steps.Step>

        <Steps.Step title={t("walkthrough.reboot.title")}>
          <p className="mb-3 text-gray-800">{t.rich("walkthrough.reboot.body", { code })}</p>
          <Image
            src="/gpu-tpu/coral-host-04-summary.png"
            alt={t("walkthrough.reboot.imageAlt")}
            width={900}
            height={500}
            className="rounded shadow-lg my-4"
          />
        </Steps.Step>
      </Steps>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("reinstallUninstall.heading")}</h2>

      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("reinstallUninstall.intro", { code })}
      </p>

      <figure className="my-4">
        <Image
          src="/gpu-tpu/coral-host-05-action-menu.png"
          alt={t("reinstallUninstall.imageAlt")}
          width={1200}
          height={680}
          className="rounded-lg border border-gray-200 shadow-sm w-full h-auto"
        />
        <figcaption className="text-sm text-gray-500 mt-2 text-center italic">
          {t.rich("reinstallUninstall.imageCaption", { code })}
        </figcaption>
      </figure>

      <h3 className="text-lg font-semibold mt-6 mb-2 text-gray-900">{t("reinstallUninstall.reinstallHeading")}</h3>
      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("reinstallUninstall.reinstallBody", { code })}
      </p>

      <h3 className="text-lg font-semibold mt-6 mb-2 text-gray-900">{t("reinstallUninstall.uninstallHeading")}</h3>
      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("reinstallUninstall.uninstallIntro", { code })}
      </p>
      <ul className="list-disc pl-6 mb-4 text-gray-800 leading-relaxed space-y-1">
        {uninstallItems.map((_, idx) => (
          <li key={idx}>{t.rich(`reinstallUninstall.uninstallItems.${idx}`, { code, strong })}</li>
        ))}
      </ul>

      <Callout variant="warning" title={t("reinstallUninstall.lxcWarnTitle")}>
        {t("reinstallUninstall.lxcWarnBody")}
      </Callout>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("updates.heading")}</h2>

      <p className="mb-4 text-gray-800 leading-relaxed">{t("updates.intro")}</p>

      <div className="my-4 overflow-x-auto">
        <table className="min-w-full border border-gray-200 text-sm">
          <thead className="bg-gray-100">
            <tr>
              <th className="border border-gray-200 px-3 py-2 text-left text-gray-900">{t("updates.headerVariant")}</th>
              <th className="border border-gray-200 px-3 py-2 text-left text-gray-900">{t("updates.headerTracked")}</th>
              <th className="border border-gray-200 px-3 py-2 text-left text-gray-900">{t("updates.headerUpstream")}</th>
            </tr>
          </thead>
          <tbody className="text-gray-800">
            <tr>
              <td className="border border-gray-200 px-3 py-2">{t("updates.pcieVariant")}</td>
              <td className="border border-gray-200 px-3 py-2">{t.rich("updates.pcieTracked", { code })}</td>
              <td className="border border-gray-200 px-3 py-2">{t.rich("updates.pcieUpstream", { code })}</td>
            </tr>
            <tr>
              <td className="border border-gray-200 px-3 py-2">{t("updates.usbVariant")}</td>
              <td className="border border-gray-200 px-3 py-2">{t.rich("updates.usbTracked", { code })}</td>
              <td className="border border-gray-200 px-3 py-2">{t.rich("updates.usbUpstream", { code })}</td>
            </tr>
          </tbody>
        </table>
      </div>

      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("updates.outro", { code, strong })}
      </p>

      <Callout variant="info" title={t("updates.antiTitle")}>
        {t("updates.antiBody")}
      </Callout>

      <Callout variant="info" title={t("updates.rebootTitle")}>
        {t("updates.rebootBody")}
      </Callout>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("manual.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">{t("manual.intro")}</p>

      <h3 className="text-lg font-semibold mt-6 mb-2 text-gray-900">{t("manual.pcieHeading")}</h3>
      <CopyableCode
        code={`# Build deps
apt-get update
apt-get install -y git dkms build-essential "proxmox-headers-$(uname -r)"

# Clone the (maintained) fork
cd /tmp
rm -rf gasket-driver
git clone --depth=1 https://github.com/feranick/gasket-driver.git

# Stage under /usr/src for DKMS
cp -a /tmp/gasket-driver/src/. /usr/src/gasket-1.0/

# Tell DKMS what it is
cat > /usr/src/gasket-1.0/dkms.conf <<'EOF'
PACKAGE_NAME="gasket"
PACKAGE_VERSION="1.0"
BUILT_MODULE_NAME[0]="gasket"
BUILT_MODULE_NAME[1]="apex"
DEST_MODULE_LOCATION[0]="/updates/dkms"
DEST_MODULE_LOCATION[1]="/updates/dkms"
MAKE[0]="make KVERSION=\${kernelver}"
CLEAN="make clean"
AUTOINSTALL="yes"
EOF

# Register + build + install
dkms add    /usr/src/gasket-1.0
dkms build  gasket/1.0 -k "$(uname -r)"
dkms install gasket/1.0 -k "$(uname -r)"

# Load it
modprobe gasket
modprobe apex

# Group + udev so /dev/apex_* end up with sane perms
groupadd --system apex 2>/dev/null || true
cat > /etc/udev/rules.d/99-coral-apex.rules <<'EOF'
KERNEL=="apex_*",   GROUP="apex", MODE="0660"
SUBSYSTEM=="apex",  GROUP="apex", MODE="0660"
EOF
udevadm control --reload-rules
udevadm trigger --subsystem-match=apex || true

# (Reboot recommended)`}
        className="my-4"
      />

      <h3 className="text-lg font-semibold mt-6 mb-2 text-gray-900">{t("manual.usbHeading")}</h3>
      <CopyableCode
        code={`# GPG key + repo (modern signed-by layout)
mkdir -p /etc/apt/keyrings
curl -fsSL https://packages.cloud.google.com/apt/doc/apt-key.gpg \\
  | gpg --dearmor -o /etc/apt/keyrings/coral-edgetpu.gpg
chmod 0644 /etc/apt/keyrings/coral-edgetpu.gpg

echo 'deb [signed-by=/etc/apt/keyrings/coral-edgetpu.gpg] https://packages.cloud.google.com/apt coral-edgetpu-stable main' \\
  > /etc/apt/sources.list.d/coral-edgetpu.list

# Install the runtime
apt-get update
apt-get install -y libedgetpu1-std

# Reload udev so shipped rules apply to anything already plugged in
udevadm control --reload-rules
udevadm trigger --subsystem-match=usb || true`}
        className="my-4"
      />

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("verification.heading")}</h2>

      <h3 className="text-lg font-semibold mt-6 mb-2 text-gray-900">{t("verification.pcieHeading")}</h3>
      <CopyableCode
        code={`# Module loaded?
lsmod | grep apex
# Expect: apex, gasket (gasket as dependency)

# Device node present with apex group?
ls -l /dev/apex_*
# Expect: crw-rw---- 1 root apex ...  /dev/apex_0

# Kernel sees the device cleanly?
dmesg | grep -i apex | tail -10
# Expect: "Apex chip ID ..." / "apex 0000:xx:00.0: Apex performance changed to ..."`}
        className="my-4"
      />

      <h3 className="text-lg font-semibold mt-6 mb-2 text-gray-900">{t("verification.usbHeading")}</h3>
      <CopyableCode
        code={`# Is it seen by USB?
lsusb | grep -E '1a6e:089a|18d1:9302'

# Runtime installed?
dpkg -l libedgetpu1-std | grep ii

# Quick smoke test — run the Coral classification example from any Python env
#   pip install pycoral tflite_runtime pillow
# (Ran from the container that will use the TPU, not the host.)`}
        className="my-4"
      />

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("troubleshoot.heading")}</h2>

      <Callout variant="troubleshoot" title={t("troubleshoot.dkmsFailTitle")}>
        {t.rich("troubleshoot.dkmsFailBody", { code })}
      </Callout>

      <Callout variant="troubleshoot" title={t("troubleshoot.apexMissTitle")}>
        {t.rich("troubleshoot.apexMissBody", { code })}
      </Callout>

      <Callout variant="troubleshoot" title={t("troubleshoot.lxcMissTitle")}>
        {t.rich("troubleshoot.lxcMissBody", { lxcLink })}
      </Callout>

      <Callout variant="troubleshoot" title={t("troubleshoot.usbUnreachTitle")}>
        {t.rich("troubleshoot.usbUnreachBody", { code })}
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
