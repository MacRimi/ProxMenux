import type { Metadata } from "next"
import Link from "next/link"
import Image from "next/image"
import { ArrowLeft, Download, Package, Code, Server, Clock, ExternalLink } from "lucide-react"

export const metadata: Metadata = {
  title: "ProxMenux Documentation: UUP Dump ISO Creator",
  description:
    "Guide for using the UUP Dump ISO Creator utility in ProxMenux to download and create Windows installation media directly from Microsoft's Windows Update servers.",
  openGraph: {
    title: "ProxMenux Documentation: UUP Dump ISO Creator",
    description:
      "Guide for using the UUP Dump ISO Creator utility in ProxMenux to download and create Windows installation media directly from Microsoft's Windows Update servers.",
    type: "article",
    url: "https://macrimi.github.io/ProxMenux/docs/utilities/uup-dump-iso-creator",
    images: [
      {
        url: "https://macrimi.github.io/ProxMenux/utils/uup-dump-iso-creator.png",
        width: 1200,
        height: 630,
        alt: "ProxMenux UUP Dump ISO Creator",
      },
    ],
  },
  twitter: {
    card: "summary_large_image",
    title: "ProxMenux Documentation: UUP Dump ISO Creator",
    description:
      "Guide for using the UUP Dump ISO Creator utility in ProxMenux to download and create Windows installation media directly from Microsoft's Windows Update servers.",
    images: ["https://macrimi.github.io/ProxMenux/utils/uup-dump-iso-creator.png"],
  },
}

interface ImageWithCaptionProps {
  src: string
  alt: string
  caption: string
}

function ImageWithCaption({ src, alt, caption }: ImageWithCaptionProps) {
  return (
    <div className="flex flex-col items-center w-full max-w-[768px] mx-auto my-4">
      <div className="w-full rounded-md overflow-hidden border border-gray-200">
        <Image
          src={src || "/placeholder.svg?height=400&width=768&query=UUP Dump ISO Creator"}
          alt={alt}
          width={768}
          height={400}
          style={{ height: "auto" }}
          className="object-contain w-full"
          sizes="(max-width: 768px) 100vw, 768px"
        />
      </div>
      <span className="mt-2 text-sm text-gray-600">{caption}</span>
    </div>
  )
}

export default function UUPDumpISOCreatorPage() {
  return (
    <div className="container mx-auto py-10 px-4 bg-white text-black">
      <div className="mb-4">

        <div className="flex items-center gap-3 mb-6">
          <Download className="h-8 w-8 mr-2 text-blue-500" />
          <h1 className="text-3xl font-bold text-black">UUP Dump ISO Creator</h1>
        </div>

        <div className="space-y-4 mt-6">
          <p className="text-lg text-black">
            The UUP Dump ISO Creator script is a ProxMenux utility that allows you to download and create Windows
            installation media directly from Microsoft's Windows Update servers. This option provides access to the
            latest Windows builds, including Insider Preview versions.
          </p>
        </div>
      </div>

      <ImageWithCaption
        src="https://macrimi.github.io/ProxMenux/utils/uup-dump-iso-creator.png"
        alt="UUP Dump ISO Creator"
        caption="UUP Dump ISO Creator in ProxMenux"
      />

      <div className="mt-8">
        <h2 className="text-2xl font-bold mb-4 text-black">What is UUP Dump?</h2>
        <p className="mb-4">
          UUP Dump is a service that allows users to download Unified Update Platform (UUP) files directly from
          Microsoft's Windows Update servers. These files can be converted into complete, official Windows installation
          ISO images.
        </p>

        <p className="mb-4">The main advantages of using UUP Dump include:</p>
        <ul className="list-disc pl-5 mb-4">
          <li>Access to the latest Windows versions, including Insider builds</li>
          <li>Ability to download specific Windows versions that are no longer officially available</li>
          <li>Obtaining clean, official ISO images directly from Microsoft's servers</li>
          <li>Support for multiple Windows editions (Home, Pro, Enterprise, etc.)</li>
          <li>Ability to select specific languages</li>
        </ul>
      </div>

      <div className="mt-8">
        <h2 className="text-2xl font-bold mb-4 text-black">Script Functionality</h2>
        <p className="mb-4">
          The ProxMenux UUP Dump ISO Creator script automates the entire process of downloading and creating Windows ISO
          images. The main features of the script include:
        </p>

        <div className="space-y-8 mt-6">
          <div className="border rounded-lg p-6 bg-gray-50 hover:shadow-md transition-shadow">
            <div className="flex items-center gap-3 mb-4">
              <Package className="h-6 w-6 text-blue-500" />
              <h3 className="text-xl font-semibold">Dependency Management</h3>
            </div>
            <p className="mb-3">
              The script automatically verifies and installs all necessary dependencies for the download and conversion
              process:
            </p>
            <ul className="list-disc pl-5 space-y-1 mb-4">
              <li>
                <code className="bg-gray-100 px-1 py-0.5 rounded">curl</code> - For downloading files
              </li>
              <li>
                <code className="bg-gray-100 px-1 py-0.5 rounded">aria2</code> - Advanced download manager
              </li>
              <li>
                <code className="bg-gray-100 px-1 py-0.5 rounded">cabextract</code> - For extracting CAB files
              </li>
              <li>
                <code className="bg-gray-100 px-1 py-0.5 rounded">wimtools</code> - For manipulating WIM files
              </li>
              <li>
                <code className="bg-gray-100 px-1 py-0.5 rounded">genisoimage</code> - For creating ISO images
              </li>
              <li>
                <code className="bg-gray-100 px-1 py-0.5 rounded">chntpw</code> - For modifying Windows registries
              </li>
            </ul>
            <div className="bg-gray-100 p-3 rounded-md overflow-x-auto">
              <pre className="text-sm">
                <code>apt-get install curl aria2 cabextract wimtools genisoimage chntpw</code>
              </pre>
            </div>
          </div>

          <div className="border rounded-lg p-6 bg-gray-50 hover:shadow-md transition-shadow">
            <div className="flex items-center gap-3 mb-4">
              <Code className="h-6 w-6 text-blue-500" />
              <h3 className="text-xl font-semibold">Conversion Process</h3>
            </div>
            <p className="mb-3">
              The script handles the entire process of converting UUP files to a bootable ISO image:
            </p>
            <ul className="list-disc pl-5 space-y-1">
              <li>Downloading the official UUP Dump converter script</li>
              <li>Generating the file list to download based on the provided URL</li>
              <li>Downloading all necessary files using aria2 (parallel download)</li>
              <li>Converting the downloaded files to a bootable ISO image</li>
              <li>Cleaning up temporary files after creation</li>
            </ul>
          </div>

          <div className="border rounded-lg p-6 bg-gray-50 hover:shadow-md transition-shadow">
            <div className="flex items-center gap-3 mb-4">
              <Server className="h-6 w-6 text-blue-500" />
              <h3 className="text-xl font-semibold">Proxmox Integration</h3>
            </div>
            <p className="mb-3">The script integrates seamlessly with the Proxmox VE environment:</p>
            <ul className="list-disc pl-5 space-y-1 mb-4">
              <li>Automatic detection of the ISO storage directory in Proxmox</li>
              <li>Storage of the resulting ISO image in the correct location</li>
              <li>Immediate availability of the ISO for use in VM creation</li>
              <li>Compatibility with different Proxmox storage configurations</li>
            </ul>
            <p className="mb-2">The script automatically detects the ISO storage directory in Proxmox by:</p>
            <p className="text-sm text-gray-600">
              If none is found, uses the default directory /var/lib/vz/template/iso
            </p>
          </div>

          <div className="border rounded-lg p-6 bg-gray-50 hover:shadow-md transition-shadow">
            <div className="flex items-center gap-3 mb-4">
              <Clock className="h-6 w-6 text-blue-500" />
              <h3 className="text-xl font-semibold">Download Process</h3>
            </div>
            <p className="mb-3">
              The script uses aria2 to download files with optimized configurations. The typical processing time is
              approximately 10 minutes, depending on your internet connection speed and server performance.
            </p>
            <div className="bg-gray-100 p-3 rounded-md overflow-x-auto mb-3">
              <pre className="text-sm">
                <code>
                  aria2c --no-conf --console-log-level=warn --log-level=info --log="aria2_download.log" -x16 -s16 -j5 -c
                  -R -d"$destDir" -i"$tempScript"
                </code>
              </pre>
            </div>
            <p className="text-sm text-gray-600">
              Where:
              <br />
              <code>-x16</code>: Maximum 16 connections per server
              <br />
              <code>-s16</code>: Splits each file into 16 segments
              <br />
              <code>-j5</code>: Downloads 5 files in parallel
              <br />
              <code>-c</code>: Continues partial downloads if possible
              <br />
              <code>-R</code>: Retries failed downloads
            </p>
          </div>
        </div>
      </div>

      <div className="mt-12">
        <h2 className="text-2xl font-bold mb-6 text-black">Step-by-Step Guide: Getting the UUP Dump URL</h2>
        <p className="mb-6">
          Before using the UUP Dump ISO Creator script, you'll need to obtain a specific UUP Dump URL that contains the
          necessary parameters (id, pack, edition). Follow these steps to generate the correct URL:
        </p>

        <div className="space-y-10">
          <div>
            <h3 className="text-xl font-semibold mb-4 flex items-center">
              <span className="bg-blue-500 text-white rounded-full w-8 h-8 flex items-center justify-center mr-3">
                1
              </span>
              Select Windows Version
            </h3>
            <p className="mb-4">
              Visit the UUP Dump website (
              <a
                href="https://uupdump.net/"
                target="_blank"
                rel="noopener noreferrer"
                className="text-blue-500 hover:text-blue-700"
              >
                https://uupdump.net/
              </a>
              ) and select the Windows version you want to download.
            </p>
            <ImageWithCaption
              src="https://macrimi.github.io/ProxMenux/iso-creator/step-1-select-version-windows.png"
              alt="Select Windows Version"
              caption="UUP Dump main page for selecting Windows version"
            />
          </div>

          <div>
            <h3 className="text-xl font-semibold mb-4 flex items-center">
              <span className="bg-blue-500 text-white rounded-full w-8 h-8 flex items-center justify-center mr-3">
                2
              </span>
              Select Specific Build
            </h3>
            <p className="mb-4">
              Choose the specific Windows build you want to download. You can select from the latest builds, Insider
              Preview builds, or specific versions.
            </p>
            <ImageWithCaption
              src="https://macrimi.github.io/ProxMenux/iso-creator/step-2-select-version-windows.png"
              alt="Select Specific Build"
              caption="Selection of the specific Windows build"
            />
          </div>

          <div>
            <h3 className="text-xl font-semibold mb-4 flex items-center">
              <span className="bg-blue-500 text-white rounded-full w-8 h-8 flex items-center justify-center mr-3">
                3
              </span>
              Select Language
            </h3>
            <p className="mb-4">
              Choose the language for the Windows image. You can select any language available for that specific build.
            </p>
            <ImageWithCaption
              src="https://macrimi.github.io/ProxMenux/iso-creator/step-3-select-version-windows.png"
              alt="Select Language"
              caption="Selection of the language for the Windows image"
            />
          </div>

          <div>
            <h3 className="text-xl font-semibold mb-4 flex items-center">
              <span className="bg-blue-500 text-white rounded-full w-8 h-8 flex items-center justify-center mr-3">
                4
              </span>
              Select Editions
            </h3>
            <p className="mb-4">
              Select the Windows editions you want to include in the ISO image. You can choose one or multiple editions
              (Home, Pro, Enterprise, etc.).
            </p>
            <ImageWithCaption
              src="https://macrimi.github.io/ProxMenux/iso-creator/step-4-select-version-windows.png"
              alt="Select Editions"
              caption="Selection of Windows editions to include"
            />
          </div>

          <div>
            <h3 className="text-xl font-semibold mb-4 flex items-center">
              <span className="bg-blue-500 text-white rounded-full w-8 h-8 flex items-center justify-center mr-3">
                5
              </span>
              Get Download URL
            </h3>
            <p className="mb-4">
              On the final page, you'll see download options. What you need is the URL that appears in your browser,
              which should contain the parameters <code className="bg-gray-100 px-1 py-0.5 rounded">id</code>,{" "}
              <code className="bg-gray-100 px-1 py-0.5 rounded">pack</code>, and{" "}
              <code className="bg-gray-100 px-1 py-0.5 rounded">edition</code>.
            </p>
            <ImageWithCaption
              src="https://macrimi.github.io/ProxMenux/iso-creator/step-5-select-version-windows.png"
              alt="Get Download URL"
              caption="Final page with the URL containing the necessary parameters"
            />
          </div>
        </div>
      </div>

      <div className="mt-12">
        <h2 className="text-2xl font-bold mb-6 text-black">Using the UUP Dump ISO Creator Script</h2>
        <p className="mb-6">
          Once you have the UUP Dump URL, you can use the ProxMenux UUP Dump ISO Creator script to download and create
          the ISO image:
        </p>

        <div className="space-y-10">
          <div>
            <h3 className="text-xl font-semibold mb-4 flex items-center">
              <span className="bg-blue-500 text-white rounded-full w-8 h-8 flex items-center justify-center mr-3">
                1
              </span>
              Paste the UUP Dump URL
            </h3>
            <p className="mb-4">
              When prompted, paste the complete UUP Dump URL you obtained in the previous steps. The script will verify
              that the URL contains all the necessary parameters.
            </p>
            <ImageWithCaption
              src="https://macrimi.github.io/ProxMenux/iso-creator/add-url-iso-creator.png"
              alt="Paste UUP Dump URL"
              caption="Window for pasting the UUP Dump URL"
            />
          </div>

          <div>
            <h3 className="text-xl font-semibold mb-4 flex items-center">
              <span className="bg-blue-500 text-white rounded-full w-8 h-8 flex items-center justify-center mr-3">
                2
              </span>
              Start the UUP Dump ISO Creator Script
            </h3>
            <p className="mb-4">Access the Utilities section in ProxMenux and select "UUP Dump ISO Creator".</p>
            <ImageWithCaption
              src="https://macrimi.github.io/ProxMenux/iso-creator/start-uupdump-iso-creator.png"
              alt="Start UUP Dump ISO Creator"
              caption="Starting the UUP Dump ISO Creator script in ProxMenux"
            />
          </div>

          <div>
            <h3 className="text-xl font-semibold mb-4 flex items-center">
              <span className="bg-blue-500 text-white rounded-full w-8 h-8 flex items-center justify-center mr-3">
                3
              </span>
              Process Completion
            </h3>
            <p className="mb-4">
              Once the process is complete, the script will display a success message and the location of the created
              ISO image. The ISO will be immediately available for use in creating virtual machines in Proxmox.
            </p>
            <ImageWithCaption
              src="https://macrimi.github.io/ProxMenux/iso-creator/end-uupdump-iso-creator.png"
              alt="Process Completion"
              caption="Successful completion message of the ISO creation process"
            />
          </div>
        </div>
      </div>

    </div>
  )
}
