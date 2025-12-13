"use client"

import CopyableCode from "@/components/CopyableCode"
import Image from "next/image"
import Link from "next/link"
import { AlertTriangle, FileCode, Shield } from "lucide-react"

export default function InstallationPage() {
  const installationCode = `bash -c \"$(wget -qLO - https://raw.githubusercontent.com/MacRimi/ProxMenux/main/install_proxmenux.sh)\"`

  return (
    <div className="w-full max-w-4xl mx-auto px-4 py-8 text-gray-900">
      <h1 className="text-3xl font-bold mb-6">Installing ProxMenux</h1>

      <h2 className="text-xl font-semibold mt-6 mb-2">Installation</h2>
      <p className="mb-2">To install ProxMenux, simply run the following command in your Proxmox server terminal:</p>
      <div className="w-full mb-4">
        <CopyableCode code={installationCode} />
      </div>

        {/* Security Notice */}
        <div className="my-4 text-sm">
          <p className="flex items-center mb-2">
            <AlertTriangle className="h-4 w-4 text-yellow-500 mr-2 flex-shrink-0" />
            <span>Be careful when copying scripts from the internet. Always remember to check the source!</span>
          </p>
          <p className="flex items-center mb-2">
            <FileCode className="h-4 w-4 text-blue-500 mr-2 flex-shrink-0" />
            <span>You can <a href="https://github.com/MacRimi/ProxMenux/blob/main/install_proxmenux.sh" className="text-blue-600 hover:underline" target="_blank" rel="noopener noreferrer">review the source code</a> before execution.</span>
          </p>
          <p className="flex items-center">
            <Shield className="h-4 w-4 text-green-500 mr-2 flex-shrink-0" />
            <span>All executable links follow our <a href="https://github.com/MacRimi/ProxMenux?tab=coc-ov-file#-2-security--code-responsibility" className="text-blue-600 hover:underline" target="_blank" rel="noopener noreferrer">Code of Conduct</a>.</span>
          </p>
        </div>
   
      <p className="mt-8 mb-4">During installation, ProxMenux will automatically install and configure the following dependencies:</p>
      <ul className="list-disc list-inside mb-4">
        <li>whiptail - for interactive menus</li>
        <li>curl - for downloading remote files</li>
        <li>jq - for handling JSON data</li>
        <li>Python 3 and virtual environment - required for translations</li>
        <li>Google Translate (googletrans) - for multi-language support</li>
      </ul>

      <h2 className="text-xl font-semibold mt-6 mb-2">Installation Progress</h2>
      <p className="mb-2">The installation process will look like this:</p>
      <div className="w-full mb-4">
        <Image src="https://macrimi.github.io/ProxMenux/install/install.png" alt="ProxMenux Installation" width={800} height={400} className="rounded shadow-lg" />
      </div>

      <h2 className="text-xl font-semibold mt-6 mb-2">How to Use</h2>
      <p className="mb-2">Once installed, launch <strong>ProxMenux</strong> by running:</p>
      <div className="w-full mb-4">
        <CopyableCode code="menu" />
      </div>

      <h2 className="text-xl font-semibold mt-6 mb-2">First Execution and Language Selection</h2>
      <p className="mb-4">
        On the first execution, you will be prompted to define the language for ProxMenux. The recommended language is English. Translations are generated automatically using a predefined translation package and Google Translate. Automatic translations may contain errors, so English is the preferred language for accuracy.
      </p>

      <h2 className="text-xl font-semibold mt-6 mb-2">Uninstalling ProxMenux</h2>
      <p className="mb-4">
        If you ever need to uninstall ProxMenux, there is a function in the Settings section designed for this purpose. For detailed instructions on how to uninstall, please refer to the{" "}
        <Link href="/docs/settings/uninstall-proxmenux" className="text-blue-600 hover:underline">
          uninstall documentation
        </Link>.
      </p>

      <h2 className="text-xl font-semibold mt-8 mb-4">Troubleshooting</h2>
      <p className="mb-4">
        If you encounter any issues during installation or usage, please check the {" "}
        <a href="https://github.com/MacRimi/ProxMenux/issues" className="text-blue-600 hover:underline">
          GitHub Issues
        </a>{" "}
        page or open a new issue if your problem isn't already addressed.
      </p>
    </div>
  )
}