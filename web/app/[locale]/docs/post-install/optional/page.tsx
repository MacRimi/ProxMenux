import type { Metadata } from "next"
import { getTranslations, getMessages, setRequestLocale } from "next-intl/server"
import { Plus } from "lucide-react"
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

function StepNumber({ number }: { number: number }) {
  return (
    <div className="inline-flex items-center justify-center w-8 h-8 mr-3 text-white bg-blue-500 rounded-full">
      <span className="text-sm font-bold">{number}</span>
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
      testing: { doesItems: string[] }
      fastfetch: { doesItems: string[]; customItems: string[]; logos: Logo[] }
      figurine: { doesItems: string[] }
    } } }
  }
  const cephItems = messages.docs.postInstall.optional.ceph.doesItems
  const amdItems = messages.docs.postInstall.optional.amd.doesItems
  const haItems = messages.docs.postInstall.optional.ha.doesItems
  const testingItems = messages.docs.postInstall.optional.testing.doesItems
  const fastfetchItems = messages.docs.postInstall.optional.fastfetch.doesItems
  const fastfetchCustomItems = messages.docs.postInstall.optional.fastfetch.customItems
  const fastfetchLogos = messages.docs.postInstall.optional.fastfetch.logos
  const figurineItems = messages.docs.postInstall.optional.figurine.doesItems

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

      <h3 className="text-xl font-semibold mt-16 mb-4 flex items-center">
        <StepNumber number={1} />
        {t("ceph.title")}
      </h3>
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
# Add Ceph repository
echo "deb https://download.proxmox.com/debian/ceph-squid $(lsb_release -cs) no-subscription" > /etc/apt/sources.list.d/ceph-squid.list

# Update package lists
apt-get update

# Install Ceph
pveceph install

# Verify installation
pveceph status
      `}
      />

      <h3 className="text-xl font-semibold mt-16 mb-4 flex items-center">
        <StepNumber number={2} />
        {t("amd.title")}
      </h3>
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
# Set kernel parameter
sed -i 's/GRUB_CMDLINE_LINUX_DEFAULT="/GRUB_CMDLINE_LINUX_DEFAULT="idle=nomwait /g' /etc/default/grub
update-grub

# Configure KVM
echo "options kvm ignore_msrs=Y" >> /etc/modprobe.d/kvm.conf
echo "options kvm report_ignored_msrs=N" >> /etc/modprobe.d/kvm.conf

# Install latest Proxmox VE kernel
apt-get install pve-kernel-$(uname -r | cut -d'-' -f1-2)
      `}
      />

      <h3 className="text-xl font-semibold mt-16 mb-4 flex items-center">
        <StepNumber number={3} />
        {t("ha.title")}
      </h3>
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

      <h3 className="text-xl font-semibold mt-16 mb-4 flex items-center">
        <StepNumber number={4} />
        {t("testing.title")}
      </h3>
      <p className="mb-4">{t("testing.intro")}</p>
      <p className="mb-4">{t("testing.doesIntro")}</p>
      <ul className="list-disc pl-5 mb-4">
        {testingItems.map((_, idx) => (
          <li key={idx}>{t(`testing.doesItems.${idx}`)}</li>
        ))}
      </ul>
      <p className="mb-4">{t("testing.howUse")}</p>
      <p className="text-lg mb-2">{t("testing.manualIntro")}</p>
      <CopyableCode
        code={`
    # Add Proxmox testing repository
    echo "deb http://download.proxmox.com/debian/pve $(lsb_release -cs) pvetest" | sudo tee /etc/apt/sources.list.d/pve-testing-repo.list

    # Update package lists
    sudo apt update
      `}
      />
      <p className="mt-4 text-sm text-gray-600">
        <strong>{t("testing.noteLabel")}</strong> {t("testing.noteBody")}
      </p>
      <p className="mt-4 text-yellow-600">
        <strong>{t("testing.warnLabel")}</strong> {t("testing.warnBody")}
      </p>

      <h3 className="text-xl font-semibold mt-16 mb-4 flex items-center">
        <StepNumber number={5} />
        {t("fastfetch.title")}
      </h3>

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
# Download and install the latest version of Fastfetch
FASTFETCH_URL=$(curl -s https://api.github.com/repos/fastfetch-cli/fastfetch/releases/latest | grep "browser_download_url.*fastfetch-linux-amd64.deb" | cut -d '"' -f 4)
wget -q -O /tmp/fastfetch.deb "$FASTFETCH_URL"
dpkg -i /tmp/fastfetch.deb
apt-get install -f -y

# Configure Fastfetch (logo selection remains interactive)
# The configuration is done through a series of jq commands

# Set Fastfetch to run at login
echo "clear && fastfetch" >> ~/.bashrc
      `}
      />

      <h3 className="text-xl font-semibold mt-16 mb-4 flex items-center">
        <StepNumber number={6} />
        {t("figurine.title")}
      </h3>

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

      <section className="mt-12 p-4 bg-blue-100 rounded-md">
        <h2 className="text-xl font-semibold mb-2">{t("autoApplication.title")}</h2>
        <p>{t("autoApplication.body")}</p>
      </section>
    </div>
  )
}
