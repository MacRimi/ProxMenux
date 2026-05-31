import type { Metadata } from "next"
import { getTranslations, getMessages, setRequestLocale } from "next-intl/server"
import { Link } from "@/i18n/navigation"
import { DocHeader } from "@/components/ui/doc-header"
import { Callout } from "@/components/ui/callout"
import CopyableCode from "@/components/CopyableCode"

export async function generateMetadata({
  params,
}: {
  params: Promise<{ locale: string }>
}): Promise<Metadata> {
  const { locale } = await params
  const t = await getTranslations({ locale, namespace: "docs.postInstall.system.meta" })
  return { title: t("title"), description: t("description") }
}

type LimitRow = { file: string; sets: string }
type RelatedItem = { label: string; href: string; tail: string }

export default async function PostInstallSystemPage({
  params,
}: {
  params: Promise<{ locale: string }>
}) {
  const { locale } = await params
  setRequestLocale(locale)
  const t = await getTranslations({ locale, namespace: "docs.postInstall.system" })

  const messages = (await getMessages({ locale })) as unknown as {
    docs: { postInstall: { system: {
      journald: { keyItems: string[] }
      limits: { rows: LimitRow[] }
      kexec: { installsItems: string[] }
      related: { items: RelatedItem[] }
    } } }
  }
  const keyItems = messages.docs.postInstall.system.journald.keyItems
  const limitRows = messages.docs.postInstall.system.limits.rows
  const installsItems = messages.docs.postInstall.system.kexec.installsItems
  const relatedItems = messages.docs.postInstall.system.related.items

  const code = (chunks: React.ReactNode) => <code>{chunks}</code>
  const strong = (chunks: React.ReactNode) => <strong>{chunks}</strong>
  const em = (chunks: React.ReactNode) => <em>{chunks}</em>
  const kexecLink = (chunks: React.ReactNode) => (
    <Link href="/docs/post-install/system" className="text-blue-700 hover:underline">{chunks}</Link>
  )
  const uninstallLink = (chunks: React.ReactNode) => (
    <Link href="/docs/post-install/uninstall" className="text-blue-700 hover:underline">{chunks}</Link>
  )

  return (
    <div>
      <DocHeader
        title={t("header.title")}
        section={t("header.section")}
      />

      <Callout variant="info" title={t("intro.title")}>
        {t.rich("intro.body", { strong })}
      </Callout>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("journald.heading")}</h2>

      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("journald.intro", { code })}
      </p>

      <h3 className="text-lg font-semibold mt-6 mb-2 text-gray-900">{t("journald.keyTitle")}</h3>
      <ul className="list-disc pl-6 space-y-1 text-gray-800 mb-4">
        {keyItems.map((_, idx) => (
          <li key={idx}>{t.rich(`journald.keyItems.${idx}`, { code })}</li>
        ))}
      </ul>

      <Callout variant="tip" title={t("journald.tipTitle")}>
        {t.rich("journald.tipBody", { code })}
      </Callout>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("logrotate.heading")}</h2>

      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("logrotate.intro", { code })}
      </p>

      <CopyableCode
        code={`# /etc/logrotate.conf — ProxMenux-optimized
daily
su root adm
rotate 7
create
compress
size 10M
delaycompress
copytruncate

include /etc/logrotate.d`}
        className="my-4"
      />

      <Callout variant="tip" title={t("logrotate.tipTitle")}>
        {t.rich("logrotate.tipBody", { code, em })}
      </Callout>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("limits.heading")}</h2>

      <p className="mb-4 text-gray-800 leading-relaxed">{t("limits.intro")}</p>

      <div className="my-4 overflow-x-auto">
        <table className="min-w-full border border-gray-200 text-sm">
          <thead className="bg-gray-100">
            <tr>
              <th className="border border-gray-200 px-3 py-2 text-left text-gray-900">{t("limits.headerFile")}</th>
              <th className="border border-gray-200 px-3 py-2 text-left text-gray-900">{t("limits.headerSets")}</th>
            </tr>
          </thead>
          <tbody className="text-gray-800">
            {limitRows.map((row, idx) => (
              <tr key={row.file}>
                <td className="border border-gray-200 px-3 py-2"><code>{row.file}</code></td>
                <td className="border border-gray-200 px-3 py-2">{t.rich(`limits.rows.${idx}.sets`, { code })}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <Callout variant="tip" title={t("limits.tipTitle")}>
        {t.rich("limits.tipBody", { code })}
      </Callout>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("memory.heading")}</h2>

      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("memory.intro", { code })}
      </p>

      <CopyableCode
        code={`# /etc/sysctl.d/99-memory.conf
vm.swappiness = 10               # Avoid swapping unless truly necessary
vm.dirty_ratio = 15              # Start writeback sooner (default 20)
vm.dirty_background_ratio = 5    # Start async writeback earlier (default 10)
vm.overcommit_memory = 1         # Allow overcommit (needed by many applications)
vm.max_map_count = 262144        # Enough for modern apps (ES, Docker, some games)
vm.compaction_proactiveness = 20 # Only on kernels that support it`}
        className="my-4"
      />

      <Callout variant="warning" title={t("memory.warnTitle")}>
        {t.rich("memory.warnBody", { code })}
      </Callout>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("kexec.heading")}</h2>

      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("kexec.intro", { code, em })}
      </p>

      <h3 className="text-lg font-semibold mt-6 mb-2 text-gray-900">{t("kexec.installsTitle")}</h3>
      <ul className="list-disc pl-6 space-y-1 text-gray-800 mb-4">
        {installsItems.map((_, idx) => (
          <li key={idx}>{t.rich(`kexec.installsItems.${idx}`, { code })}</li>
        ))}
      </ul>

      <p className="mb-3 text-gray-800 leading-relaxed">
        {t.rich("kexec.usageIntro", { code })}
      </p>
      <CopyableCode
        code={`reboot-quick           # kexec into the already-loaded kernel
# Equivalent:
systemctl kexec`}
        className="my-4"
      />

      <Callout variant="warning" title={t("kexec.warnTitle")}>
        {t.rich("kexec.warnBody", { code })}
      </Callout>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("panic.heading")}</h2>

      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("panic.intro", { strong })}
      </p>

      <CopyableCode
        code={`# /etc/sysctl.d/99-kernelpanic.conf
kernel.core_pattern = /var/crash/core.%t.%p   # where to drop core dumps
kernel.panic = 10                             # reboot 10s after a panic
kernel.panic_on_oops = 1                      # oops → treated as panic
kernel.hardlockup_panic = 1                   # hard lockup → panic → reboot`}
        className="my-4"
      />

      <Callout variant="tip" title={t("panic.tipTitle")}>
        {t.rich("panic.tipBody", { em, link: kexecLink })}
      </Callout>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("verify.heading")}</h2>
      <p className="mb-3 text-gray-800 leading-relaxed">{t("verify.intro")}</p>
      <CopyableCode
        code={`# journald: actual size in use and limit
journalctl --disk-usage

# logrotate: check config is active (no errors)
logrotate -d /etc/logrotate.conf 2>&1 | head -20

# System limits: check a few effective values
sysctl fs.inotify.max_user_watches fs.file-max vm.swappiness vm.dirty_ratio
ulimit -n     # inside a new root shell

# kexec: service enabled
systemctl is-enabled kexec-pve

# kernel panic config
sysctl kernel.panic kernel.panic_on_oops kernel.hardlockup_panic`}
        className="my-4"
      />

      <Callout variant="tip" title={t("verify.tipTitle")}>
        {t.rich("verify.tipBody", { code, link: uninstallLink })}
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
