import type { Metadata } from "next"
import { getTranslations, getMessages, setRequestLocale } from "next-intl/server"
import { Plus, ExternalLink } from "lucide-react"
import CopyableCode from "@/components/CopyableCode"

export async function generateMetadata({
  params,
}: {
  params: Promise<{ locale: string }>
}): Promise<Metadata> {
  const { locale } = await params
  const t = await getTranslations({ locale, namespace: "docs.postInstall.optional.meta" })
  return {
    title: t("title"),
    description: t("description"),
    openGraph: {
      title: t("ogTitle"),
      description: t("ogDescription"),
      type: "article",
      url: "https://macrimi.github.io/ProxMenux/docs/post-install/optional",
      images: [
        {
          url: "https://macrimi.github.io/ProxMenux/optional-settings-image.png",
          width: 1200,
          height: 630,
          alt: t("ogImageAlt"),
        },
      ],
    },
    twitter: {
      card: "summary_large_image",
      title: t("ogTitle"),
      description: t("ogDescription"),
      images: ["https://macrimi.github.io/ProxMenux/optional-settings-image.png"],
    },
  }
}

type Logo = { name: string; alt: string; src: string }

function StepHeading({ number, label, title }: { number: number; label: string; title: string }) {
  return (
    <div className="flex items-center gap-3 mt-16 mb-4">
      <span className="inline-flex items-center rounded-full border border-blue-200 bg-blue-50 px-2.5 py-0.5 text-xs font-semibold text-blue-800">
        {label} {number}
      </span>
      <h3 className="text-xl font-semibold m-0">{title}</h3>
    </div>
  )
}

export default async function OptionalSettingsPage({
  params,
}: {
  params: Promise<{ locale: string }>
}) {
  const { locale } = await params
  setRequestLocale(locale)
  const t = await getTranslations({ locale, namespace: "docs.postInstall.optional" })

  const messages = (await getMessages({ locale })) as unknown as {
    docs: { postInstall: { optional: {
      ceph: { doesItems: string[] }
      amd: { doesItems: string[] }
      ha: { doesItems: string[] }
      pveam: { doesItems: string[] }
      fastfetch: { doesItems: string[]; customItems: string[]; logos: Logo[] }
      figurine: { doesItems: string[] }
      log2ram: { doesItems: string[] }
    } } }
  }
  const cephItems = messages.docs.postInstall.optional.ceph.doesItems
  const amdItems = messages.docs.postInstall.optional.amd.doesItems
  const haItems = messages.docs.postInstall.optional.ha.doesItems
  const pveamItems = messages.docs.postInstall.optional.pveam.doesItems
  const fastfetchItems = messages.docs.postInstall.optional.fastfetch.doesItems
  const fastfetchCustomItems = messages.docs.postInstall.optional.fastfetch.customItems
  const fastfetchLogos = messages.docs.postInstall.optional.fastfetch.logos
  const figurineItems = messages.docs.postInstall.optional.figurine.doesItems
  const log2ramItems = messages.docs.postInstall.optional.log2ram.doesItems

  const code = (chunks: React.ReactNode) => <code>{chunks}</code>
  const strong = (chunks: React.ReactNode) => <strong>{chunks}</strong>
  const em = (chunks: React.ReactNode) => <em>{chunks}</em>

  return (
    <div className="container mx-auto px-4 py-8">
      <div className="flex items-center mb-6">
        <Plus className="h-8 w-8 mr-2 text-blue-500" />
        <h1 className="text-3xl font-bold">{t("title")}</h1>
      </div>
      <p className="mb-4">
        {t.rich("intro", { strong })}
      </p>
      <h2 className="text-2xl font-semibold mt-8 mb-4">{t("available")}</h2>

      <StepHeading number={1} label={t("stepLabel")} title={t("ceph.title")} />
      <p className="mb-4">{t("ceph.intro")}</p>
      <p className="mb-4">{t("ceph.doesIntro")}</p>
      <ul className="list-disc pl-5 mb-4">
        {cephItems.map((_, idx) => (
          <li key={idx}>{t(`ceph.doesItems.${idx}`)}</li>
        ))}
      </ul>
      <p className="mb-4">{t("ceph.howUse")}</p>
      <p className="text-lg mb-2">{t("ceph.automates")}</p>
      <CopyableCode
        code={`
# On Proxmox VE 9 (Debian trixie) — deb822 format
cat > /etc/apt/sources.list.d/ceph.sources <<'EOF'
Types: deb
URIs: http://download.proxmox.com/debian/ceph-squid
Suites: trixie
Components: no-subscription
Signed-By: /usr/share/keyrings/proxmox-archive-keyring.gpg
EOF

# On Proxmox VE 8 (Debian bookworm) — legacy one-liner
# echo "deb https://download.proxmox.com/debian/ceph-squid $(lsb_release -cs) no-subscription" \\
#   > /etc/apt/sources.list.d/ceph-squid.list

# Update package lists
apt-get update

# Install Ceph
pveceph install

# Verify installation
pveceph status
      `}
      />

      <StepHeading number={2} label={t("stepLabel")} title={t("amd.title")} />
      <p className="mb-4">{t("amd.intro")}</p>
      <p className="mb-4">{t("amd.doesIntro")}</p>
      <ul className="list-disc pl-5 mb-4">
        {amdItems.map((_, idx) => (
          <li key={idx}>{t(`amd.doesItems.${idx}`)}</li>
        ))}
      </ul>
      <p className="mb-4">{t("amd.howUse")}</p>
      <p className="text-lg mb-2">{t("amd.automates")}</p>
      <CopyableCode
        code={`
# Set kernel parameter — GRUB path
sed -i 's/GRUB_CMDLINE_LINUX_DEFAULT="/GRUB_CMDLINE_LINUX_DEFAULT="idle=nomwait /g' /etc/default/grub
update-grub

# Set kernel parameter — systemd-boot path (ZFS-on-root)
# Adds 'idle=nomwait' to /etc/kernel/cmdline and runs:
# proxmox-boot-tool refresh

# Configure KVM
echo "options kvm ignore_msrs=Y" >> /etc/modprobe.d/kvm.conf
echo "options kvm report_ignored_msrs=N" >> /etc/modprobe.d/kvm.conf
      `}
      />

      <StepHeading number={3} label={t("stepLabel")} title={t("ha.title")} />
      <p className="mb-4">{t("ha.intro")}</p>
      <p className="mb-4">{t("ha.doesIntro")}</p>
      <ul className="list-disc pl-5 mb-4">
        {haItems.map((_, idx) => (
          <li key={idx}>{t(`ha.doesItems.${idx}`)}</li>
        ))}
      </ul>
      <p className="mb-4">{t("ha.howUse")}</p>
      <p className="text-lg mb-2">{t("ha.automates")}</p>
      <CopyableCode
        code={`
systemctl enable --now pve-ha-lrm pve-ha-crm corosync
      `}
      />

      <StepHeading number={4} label={t("stepLabel")} title={t("pveam.title")} />
      <p className="mb-4">{t.rich("pveam.intro", { code })}</p>
      <p className="mb-4">{t("pveam.doesIntro")}</p>
      <ul className="list-disc pl-5 mb-4">
        {pveamItems.map((_, idx) => (
          <li key={idx}>{t.rich(`pveam.doesItems.${idx}`, { code })}</li>
        ))}
      </ul>
      <p className="mb-4">{t("pveam.howUse")}</p>
      <p className="text-lg mb-2">{t("pveam.automates")}</p>
      <CopyableCode
        code={`
pveam update
      `}
      />

      <StepHeading number={5} label={t("stepLabel")} title={t("fastfetch.title")} />

      <p className="mb-4">{t("fastfetch.intro")}</p>

      <p className="mb-4">
        <strong>{t("fastfetch.doesLabel")}</strong>
      </p>
      <ul className="list-disc pl-5 mb-4">
        {fastfetchItems.map((_, idx) => (
          <li key={idx}>{t.rich(`fastfetch.doesItems.${idx}`, { strong, em })}</li>
        ))}
      </ul>

      <div className="bg-yellow-100 border-l-4 border-yellow-500 text-yellow-700 p-4 mb-4">
        <p className="font-semibold">{t("fastfetch.importantLabel")}</p>
        <p>
          {t.rich("fastfetch.importantBody", { strong, code })}
        </p>
      </div>

      <div className="bg-blue-100 border-l-4 border-blue-500 text-blue-700 p-4 mb-4">
        <p className="font-semibold">{t("fastfetch.customLabel")}</p>
        <p>
          {t.rich("fastfetch.customBody1", { code })}
        </p>
        <p>
          {t.rich("fastfetch.customBody2", { code })}
        </p>
        <p>{t("fastfetch.customBody3")}</p>
        <ul className="list-disc pl-5 mt-2">
          {fastfetchCustomItems.map((_, idx) => (
            <li key={idx}>{t.rich(`fastfetch.customItems.${idx}`, { code })}</li>
          ))}
        </ul>
      </div>

      <p className="mb-4">
        <strong>{t("fastfetch.examplesLabel")}</strong>
      </p>

      <div className="grid grid-cols-2 md:grid-cols-3 gap-4">
        {fastfetchLogos.map((logo) => (
          <div key={logo.name}>
            <p className="font-semibold text-center">{logo.name}</p>
            <img
              src={logo.src}
              alt={logo.alt}
              className="rounded shadow-lg"
            />
          </div>
        ))}
      </div>

      <p className="text-lg mb-2">{t("fastfetch.automates")}</p>
      <CopyableCode
        code={`
# Remove any previous install so the newest .deb lands clean
apt-get remove --purge -y fastfetch 2>/dev/null
rm -f /usr/bin/fastfetch /usr/local/bin/fastfetch

# Download and install the latest .deb via the GitHub Releases API
FASTFETCH_URL=$(curl -sSf --connect-timeout 5 --max-time 15 \\
  https://api.github.com/repos/fastfetch-cli/fastfetch/releases/latest \\
  | jq -r '.assets[] | select(.name | test("fastfetch-linux-amd64.deb")) | .browser_download_url')
wget -q -O /tmp/fastfetch.deb "$FASTFETCH_URL"
dpkg -i /tmp/fastfetch.deb
apt-get install -f -y

# Configure Fastfetch (logo selection remains interactive)
# The configuration is done through a series of jq commands.
# A custom "System optimised by ProxMenux" line is prepended
# to the modules array so it shows above the standard sections.

# Wire Fastfetch into ~/.bashrc — inside a marker block so the
# same block can be replaced on re-run without polluting the file.
# The block is guarded so it only runs on interactive shells that
# actually have the fastfetch binary available.
cat >> ~/.bashrc <<'EOF'
# BEGIN FASTFETCH
if [[ $- == *i* ]] && command -v fastfetch >/dev/null 2>&1; then
    clear
    fastfetch
fi
# END FASTFETCH
EOF
      `}
      />

      <StepHeading number={6} label={t("stepLabel")} title={t("figurine.title")} />

      <p className="mb-4">{t("figurine.intro")}</p>

      <p className="mb-4">
        <strong>{t("figurine.doesLabel")}</strong>
      </p>
      <ul className="list-disc pl-5 mb-4">
        {figurineItems.map((_, idx) => (
          <li key={idx}>{t(`figurine.doesItems.${idx}`)}</li>
        ))}
      </ul>

      <div className="bg-blue-100 border-l-4 border-blue-500 text-blue-700 p-4 mb-4">
        <p className="font-semibold">{t("figurine.practicalLabel")}</p>
        <p>{t("figurine.practicalBody")}</p>
      </div>

      <p className="mb-4">
        <strong>{t("figurine.exampleLabel")}</strong>
      </p>

      <div className="mb-6 flex justify-center">
        <img
          src="https://macrimi.github.io/ProxMenux/figurine/figurine.png"
          alt={t("figurine.imageAlt")}
          className="rounded-md shadow-lg border border-gray-200"
          style={{ maxWidth: "100%" }}
        />
      </div>

      <p className="text-lg mb-2">{t("figurine.automates")}</p>
      <CopyableCode
        code={`
# Check for previous installation and remove if found
if command -v figurine &> /dev/null; then
  rm -f "/usr/local/bin/figurine"
fi

# Download and install Figurine
version="2.0.0"
file="figurine_linux_amd64_v\${version}.tar.gz"
url="https://github.com/arsham/figurine/releases/download/v\${version}/\${file}"
wget -qO "/tmp/\${file}" "\${url}"
tar -xf "/tmp/\${file}" -C "/tmp"
mv "/tmp/deploy/figurine" "/usr/local/bin/figurine"
chmod +x "/usr/local/bin/figurine"

# Create welcome message script
cat << 'EOF' > "/etc/profile.d/figurine.sh"
/usr/local/bin/figurine -f "3d.flf" $(hostname)
EOF
chmod +x "/etc/profile.d/figurine.sh"
  `}
      />

      <p className="mt-4">{t("figurine.outro")}</p>

      <StepHeading number={7} label={t("stepLabel")} title={t("log2ram.title")} />

      <p className="mb-4">
        {t.rich("log2ram.intro", { code, em })}
      </p>

      <p className="mb-4 flex items-center gap-1 text-sm">
        <strong className="mr-1">{t("log2ram.upstreamLabel")}</strong>
        <a
          href={t("log2ram.upstreamUrl")}
          target="_blank"
          rel="noopener noreferrer"
          className="text-blue-600 hover:underline inline-flex items-center gap-1"
        >
          {t("log2ram.upstreamLinkLabel")}
          <ExternalLink className="h-3.5 w-3.5" aria-hidden="true" />
        </a>
      </p>

      <p className="mb-4">
        <strong>{t("log2ram.doesLabel")}</strong>
      </p>
      <ul className="list-disc pl-5 mb-4">
        {log2ramItems.map((_, idx) => (
          <li key={idx}>{t.rich(`log2ram.doesItems.${idx}`, { code, em })}</li>
        ))}
      </ul>

      <p className="mb-2">
        <strong>{t("log2ram.howUseLabel")}</strong> {t("log2ram.howUseBody")}
      </p>

      <p className="text-lg mt-6 mb-2">
        <strong>{t("log2ram.verifyLabel")}</strong>
      </p>
      <CopyableCode code={t.raw("log2ram.verifyCode") as string} />

      <section className="mt-12 p-4 bg-blue-100 rounded-md">
        <h2 className="text-xl font-semibold mb-2">{t("autoApplication.title")}</h2>
        <p>{t("autoApplication.body")}</p>
      </section>
    </div>
  )
}
