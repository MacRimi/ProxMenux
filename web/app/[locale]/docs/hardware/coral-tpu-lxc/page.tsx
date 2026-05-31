import type { Metadata } from "next"
import { getTranslations, getMessages, setRequestLocale } from "next-intl/server"
import { Link } from "@/i18n/navigation"
import { ExternalLink } from "lucide-react"
import { DocHeader } from "@/components/ui/doc-header"
import { Callout } from "@/components/ui/callout"
import { Prerequisites } from "@/components/ui/prerequisites"
import Image from "next/image"
import { Steps } from "@/components/ui/steps"
import CopyableCode from "@/components/CopyableCode"

export async function generateMetadata({
  params,
}: {
  params: Promise<{ locale: string }>
}): Promise<Metadata> {
  const { locale } = await params
  const t = await getTranslations({ locale, namespace: "docs.hardware.coralTpuLxc.meta" })
  return {
    title: t("title"),
    description: t("description"),
  }
}

type RelatedItem = { label: string; href: string; tail?: string }
type DriverItem = string

export default async function AddCoralTPUtoLXC({
  params,
}: {
  params: Promise<{ locale: string }>
}) {
  const { locale } = await params
  setRequestLocale(locale)
  const t = await getTranslations({ locale, namespace: "docs.hardware.coralTpuLxc" })

  const messages = (await getMessages({ locale })) as unknown as {
    docs: { hardware: { coralTpuLxc: {
      walkthrough: { drivers: { items: DriverItem[] } }
      related: { items: RelatedItem[] }
    } } }
  }
  const driverItems = messages.docs.hardware.coralTpuLxc.walkthrough.drivers.items
  const relatedItems = messages.docs.hardware.coralTpuLxc.related.items

  const code = (chunks: React.ReactNode) => <code>{chunks}</code>
  const strong = (chunks: React.ReactNode) => <strong>{chunks}</strong>
  const em = (chunks: React.ReactNode) => <em>{chunks}</em>
  const frigateLink = (chunks: React.ReactNode) => (
    <a
      href="https://frigate.video/"
      target="_blank"
      rel="noopener noreferrer"
      className="text-blue-700 hover:underline inline-flex items-center gap-1"
    >
      {chunks}
      <ExternalLink className="w-3 h-3" />
    </a>
  )
  const hostLink = (chunks: React.ReactNode) => (
    <Link href="/docs/hardware/install-coral-tpu-host" className="text-blue-700 hover:underline">{chunks}</Link>
  )
  const lxcGpuLink = (chunks: React.ReactNode) => (
    <Link href="/docs/hardware/igpu-acceleration-lxc" className="text-blue-700 hover:underline">{chunks}</Link>
  )
  const coralLink = (chunks: React.ReactNode) => (
    <a
      href="https://coral.ai/docs/accelerator/get-started/"
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
        estimatedMinutes={8}
        scriptPath="gpu_tpu/install_coral_lxc.sh"
      />

      <Callout variant="info" title={t("intro.title")}>
        {t.rich("intro.body", { code, strong, lxcGpuLink })}
      </Callout>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("whenUse.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("whenUse.body", { frigateLink })}
      </p>

      <Prerequisites
        title={t("prereqs.title")}
        items={[
          {
            label: <>{t.rich("prereqs.drivers", { strong, code, hostLink })}</>,
            check: t("prereqs.driversCheck"),
          },
          {
            label: <>{t.rich("prereqs.container", { strong, code })}</>,
          },
          {
            label: <>{t.rich("prereqs.downtime", { strong })}</>,
          },
        ]}
      />

      <Callout variant="warning" title={t("hostPrep.title")}>
        {t.rich("hostPrep.body", { code, strong })}
      </Callout>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("running.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("running.body", { strong })}
      </p>

      <Image
        src="/gpu-tpu/coral-lxc-01-menu-entry.png"
        alt={t("running.imageAlt")}
        width={900}
        height={500}
        className="rounded shadow-lg my-6"
      />

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("howRuns.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">{t("howRuns.body")}</p>

      <pre className="bg-gray-100 text-gray-800 p-4 rounded-md overflow-x-auto text-sm my-4 border border-gray-200 leading-snug">
{`┌────────────────────────────────────────────────┐
│ 1. User picks the LXC container                │
│    (pct list → dialog → CTID)                  │
└────────────────┬───────────────────────────────┘
                 ▼
       Stop container if running
                 │
                 ▼
       ┌─────────┴──────────┐
       │                    │
       ▼                    ▼
    Coral M.2/PCIe?     Coral USB?
    lspci "Global      (udev rule creates
     Unichip"           /dev/coral symlink
       │                on the host)
       │                    │
      Yes                  Yes
       │                    │
       ▼                    ▼
  /dev/apex_0       Write udev rule
  exists?           /etc/udev/rules.d/
    │                99-coral-usb.rules
    ├─ Yes →        (ATTRS idVendor/idProduct
    │  dev<N>:       → SYMLINK /dev/coral)
    │  /dev/apex_0        │
    │  gid=apex           ▼
    │               Append to LXC config:
    └─ No  →          lxc.cgroup2.devices.allow:
       cgroup2         c 189:* rwm
       fallback        lxc.mount.entry:
       (major 245       /dev/bus/usb dev/bus/usb
        from /proc/     none bind,optional,
        devices)        create=dir
         │              (bind the WHOLE usb tree,
         ▼              not /dev/coral — survives
      cgroup2           USB replug to other port)
      + mount               │
                           │
       └──────────────┬──────┘
                      ▼
       Clean up duplicate entries in the config
                      │
                      ▼
       ┌──────────────┴──────────────┐
       │  Start container + wait     │
       │  up to 15s for readiness    │
       └──────────────┬──────────────┘
                      ▼
       pct exec inside container:
       ├─ apt-get update
       ├─ Install Coral deps (gnupg, curl, ca-certificates)
       ├─ Add Google Coral APT repo
       │  /etc/apt/keyrings/coral-edgetpu.gpg
       │  /etc/apt/sources.list.d/coral-edgetpu.list
       └─ apt install libedgetpu1-std
          (or libedgetpu1-max for M.2 if user picks)
                      │
                      ▼
       Show summary (what was enabled)
       Container stays running

       Note: iGPU passthrough (Quick Sync / VA-API
       / NVENC) is now handled exclusively by
       "Add GPU to LXC" — run it BEFORE this script
       if you also want hardware video decode.`}
      </pre>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("walkthrough.heading")}</h2>

      <Steps>
        <Steps.Step title={t("walkthrough.pick.title")}>
          <p className="mb-3 text-gray-800">{t.rich("walkthrough.pick.body", { code })}</p>
        </Steps.Step>

        <Steps.Step title={t("walkthrough.gpuHint.title")}>
          <p className="mb-3 text-gray-800">{t.rich("walkthrough.gpuHint.body", { code, lxcGpuLink })}</p>
        </Steps.Step>

        <Steps.Step title={t("walkthrough.usb.title")}>
          <p className="mb-3 text-gray-800">{t.rich("walkthrough.usb.body", { code, strong })}</p>
          <CopyableCode
            code={`# /etc/udev/rules.d/99-coral-usb.rules  (on the host)
SUBSYSTEM=="usb", ATTRS{idVendor}=="1a6e", ATTRS{idProduct}=="089a", \\
  SYMLINK+="coral", MODE="0666"
SUBSYSTEM=="usb", ATTRS{idVendor}=="18d1", ATTRS{idProduct}=="9302", \\
  SYMLINK+="coral", MODE="0666"

# Appended to /etc/pve/lxc/<ctid>.conf
lxc.cgroup2.devices.allow: c 189:* rwm
lxc.mount.entry: /dev/bus/usb dev/bus/usb none bind,optional,create=dir`}
            className="my-4"
          />
          <Callout variant="tip" title={t("walkthrough.usb.whyTitle")}>
            {t.rich("walkthrough.usb.whyBody", { code })}
          </Callout>
        </Steps.Step>

        <Steps.Step title={t("walkthrough.pcie.title")}>
          <p className="mb-3 text-gray-800">{t.rich("walkthrough.pcie.body1", { code })}</p>
          <CopyableCode
            code={`# Appended to /etc/pve/lxc/<ctid>.conf — modern path
dev0: /dev/apex_0,gid=<APEX_GID>`}
            className="my-4"
          />
          <p className="mb-3 text-gray-800">{t.rich("walkthrough.pcie.body2", { code, hostLink })}</p>
          <CopyableCode
            code={`# Fallback when /dev/apex_0 isn't yet present on host
lxc.cgroup2.devices.allow: c 245:0 rwm
lxc.mount.entry: /dev/apex_0 dev/apex_0 none bind,optional,create=file`}
            className="my-4"
          />
          <Callout variant="troubleshoot" title={t("walkthrough.pcie.rebootTitle")}>
            {t.rich("walkthrough.pcie.rebootBody", { code })}
          </Callout>
        </Steps.Step>

        <Steps.Step title={t("walkthrough.drivers.title")}>
          <p className="mb-3 text-gray-800">{t.rich("walkthrough.drivers.body", { code })}</p>
          <ol className="list-decimal pl-6 space-y-1 text-gray-800 mb-3">
            {driverItems.map((_, idx) => (
              <li key={idx}>{t.rich(`walkthrough.drivers.items.${idx}`, { code })}</li>
            ))}
          </ol>
        </Steps.Step>

        <Steps.Step title={t("walkthrough.summary.title")}>
          <p className="mb-3 text-gray-800">{t("walkthrough.summary.body")}</p>
        </Steps.Step>
      </Steps>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("manual.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">{t("manual.body")}</p>

      <h3 className="text-lg font-semibold mt-6 mb-2 text-gray-900">{t("manual.usbHeading")}</h3>
      <CopyableCode
        code={`# On the HOST — persistent udev alias
cat > /etc/udev/rules.d/99-coral-usb.rules <<'EOF'
SUBSYSTEM=="usb", ATTRS{idVendor}=="1a6e", ATTRS{idProduct}=="089a", SYMLINK+="coral", MODE="0666"
SUBSYSTEM=="usb", ATTRS{idVendor}=="18d1", ATTRS{idProduct}=="9302", SYMLINK+="coral", MODE="0666"
EOF
udevadm control --reload-rules
udevadm trigger --subsystem-match=usb

# Append to /etc/pve/lxc/<ctid>.conf
# (container must be stopped to apply)
lxc.cgroup2.devices.allow: c 189:* rwm
lxc.mount.entry: /dev/bus/usb dev/bus/usb none bind,optional,create=dir`}
        className="my-4"
      />

      <h3 className="text-lg font-semibold mt-6 mb-2 text-gray-900">{t("manual.pcieHeading")}</h3>
      <CopyableCode
        code={`# On the HOST — PVE dev API (works in privileged AND unprivileged CTs)
# Append to /etc/pve/lxc/<ctid>.conf
dev0: /dev/apex_0,gid=$(getent group apex | cut -d: -f3)

# ─── OPTIONAL — fallback path ────────────────────────────────────
# Only use this block if /dev/apex_0 doesn't exist yet on the host
# (apex module not loaded — reboot still pending). The PVE dev API
# above is preferred when the device is present.
# ─────────────────────────────────────────────────────────────────
# lxc.cgroup2.devices.allow: c 245:0 rwm
# lxc.mount.entry: /dev/apex_0 dev/apex_0 none bind,optional,create=file`}
        className="my-4"
      />

      <h3 className="text-lg font-semibold mt-6 mb-2 text-gray-900">{t("manual.runtimeHeading")}</h3>
      <CopyableCode
        code={`# Assumes Debian / Ubuntu
apt-get update
apt-get install -y gnupg curl ca-certificates

# Google Coral APT repo
curl -fsSL https://packages.cloud.google.com/apt/doc/apt-key.gpg \\
  | gpg --dearmor -o /usr/share/keyrings/coral-edgetpu.gpg

echo 'deb [signed-by=/usr/share/keyrings/coral-edgetpu.gpg] https://packages.cloud.google.com/apt coral-edgetpu-stable main' \\
  > /etc/apt/sources.list.d/coral-edgetpu.list

apt-get update
apt-get install -y libedgetpu1-std
# Or for M.2 + maximum performance (runs hotter):
# apt-get install -y libedgetpu1-max`}
        className="my-4"
      />

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("verification.heading")}</h2>
      <p className="mb-3 text-gray-800 leading-relaxed">{t("verification.body")}</p>
      <CopyableCode
        code={`pct enter <ctid>

# USB Coral
lsusb | grep -E '1a6e:089a|18d1:9302'
ls /dev/bus/usb/

# M.2 Coral
ls -l /dev/apex_0
# Expect: crw-rw---- 1 root apex ... /dev/apex_0

# Runtime installed
dpkg -l libedgetpu1-std

# Frigate-style test: run a quick Python inference
python3 -c "from pycoral.utils.edgetpu import list_edge_tpus; print(list_edge_tpus())"
# Expect a non-empty list with at least one device`}
        className="my-4"
      />

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("troubleshoot.heading")}</h2>

      <Callout variant="troubleshoot" title={t("troubleshoot.apexTitle")}>
        {t.rich("troubleshoot.apexBody", { code })}
      </Callout>

      <Callout variant="troubleshoot" title={t("troubleshoot.replugTitle")}>
        {t.rich("troubleshoot.replugBody", { code })}
      </Callout>

      <Callout variant="troubleshoot" title={t("troubleshoot.alpineTitle")}>
        {t.rich("troubleshoot.alpineBody", { code })}
      </Callout>

      <Callout variant="troubleshoot" title={t("troubleshoot.frigateTitle")}>
        {t.rich("troubleshoot.frigateBody", { code })}
      </Callout>

      <Callout variant="tip" title={t("troubleshoot.logsTitle")}>
        {t.rich("troubleshoot.logsBody", { code })}
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
