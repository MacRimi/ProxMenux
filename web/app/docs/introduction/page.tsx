import Image from "next/image"
import Link from "next/link"
import { AlertTriangle, FileCode, Shield } from "lucide-react"

export default function IntroductionPage() {
  return (
    <div className="w-full max-w-4xl mx-auto px-4 py-8 text-gray-900">
      {/* Logo + Title Section */}
      <div className="flex items-start mb-6">
        <Image 
          src="https://macrimi.github.io/ProxMenux/logo.png" 
          alt="ProxMenux Logo" 
          width={80} 
          height={80} 
          className="mr-4"
        />
        <p className="mb-4">
        ProxMenux is a tool designed to make Proxmox VE accessible to all users, regardless of their experience and technical knowledge.
        </p>
      </div>

      <p className="mb-4">
      Designed with a menu-based interface, ProxMenux simplifies the execution of commands to perform actions on:
      </p>
      <ul className="list-disc list-inside mb-4 ml-4">
        <li>The Proxmox server</li>
        <li>Virtual machines (VMs)</li>
        <li>Containers (LXC)</li>
      </ul>

      <h2 className="text-2xl font-semibold mt-8 mb-4">Core Features</h2>
      <p className="mb-4">
        ProxMenux enables streamlined management of:
      </p>
      <ul className="list-disc list-inside mb-6 ml-4">
        <li>System resources</li>
        <li>Network and storage configurations</li>
        <li>VM and LXC container administration</li>
        <li>Hardware integration and optimizations</li>
        <li>Automated server maintenance</li>
      </ul>

      <h2 className="text-2xl font-semibold mt-8 mb-4">Key Advantages</h2>
      <ul className="list-disc list-inside mb-6 ml-4">
        <li>Intuitive menu-driven interface</li>
        <li>Simplification of management tasks</li>
      </ul>

      <p className="mt-6">
        The following sections provide detailed instructions on installing and using ProxMenux, along with comprehensive documentation on its available functionalities.
      </p>

      {/* Guides Link */}
      <p className="mt-6">
        For additional Proxmox-related information, including official documentation, forums, and discussions, visit the{" "}
        <Link href="/guides" className="text-blue-500 hover:underline">
          Guides
        </Link>{" "} 
        section.
      </p>

      {/* Security Notice */}
      <div>
          <h3 className="text-2xl font-semibold mt-8 mb-2 flex items-center">
            <AlertTriangle className="h-5 w-5 text-yellow-500 mr-2" />
            Security Information
          </h3>
          <p className="mb-3">
            Be careful when running scripts from the Internet. Always remember to check the source!
            All executable links follow our Code of Conduct.
          </p>
          <div className="flex flex-wrap gap-2">
            <a
              href="https://github.com/MacRimi/ProxMenux/tree/main/scripts" 
              className="inline-flex items-center px-3 py-2 text-sm font-medium rounded-md bg-blue-600 hover:bg-blue-700 text-white"
              target="_blank"
              rel="noopener noreferrer"
            >
              <FileCode className="h-4 w-4 mr-2" />
              View Source Code
            </a>
            <a
              href="https://github.com/MacRimi/ProxMenux?tab=coc-ov-file#-2-security--code-responsibility" 
              className="inline-flex items-center px-3 py-2 text-sm font-medium rounded-md bg-green-600 hover:bg-green-700 text-white"
              target="_blank"
              rel="noopener noreferrer"
            >
              <Shield className="h-4 w-4 mr-2" />
              Code of Conduct
            </a>
          </div>
        </div>

    </div>
  )
}
