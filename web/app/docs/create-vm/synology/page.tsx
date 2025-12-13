"use client"

import Image from "next/image"
import {
    Wrench,
    Target,
    CheckCircle,
    Github,
    Server,
    HardDrive,
    Download,
    Settings,
    Cpu,
    Zap,
    Sliders,
  } from "lucide-react"
import { useState } from "react"

export default function Page() {
  const [activeLoader, setActiveLoader] = useState("arc")

  return (
    <div className="container mx-auto px-4 py-8">
      <h1 className="text-3xl font-bold mb-6">Synology VM Creator Script</h1>

      <section className="mb-10">
        <h2 className="text-2xl font-semibold mb-4 flex items-center">
          <Server className="h-6 w-6 mr-2 text-blue-500" />
          Introduction
        </h2>
        <p className="mb-4">
          ProxMenux provides an automated script that creates and configures a virtual machine (VM) to install Synology
          DSM (DiskStation Manager) on Proxmox VE. This script simplifies the process by downloading and adding one of
          the available loaders to the VM boot, giving you the option between four different choices:
        </p>
        <ul className="list-disc pl-5 mb-4">
          <li>
            <a
              href="https://github.com/AuxXxilium/arc"
              target="_blank"
              rel="noopener noreferrer"
              className="text-blue-600 hover:underline"
            >
              AuxXxilium Arc
            </a>{" "}
          </li>
          <li>
            <a
              href="https://github.com/RROrg/rr"
              target="_blank"
              rel="noopener noreferrer"
              className="text-blue-600 hover:underline"
            >
              RedPill RR
            </a>{" "}
          </li>
          <li>
            <a
              href="https://github.com/PeterSuh-Q3/tinycore-redpill"
              target="_blank"
              rel="noopener noreferrer"
              className="text-blue-600 hover:underline"
            >
              TinyCore RedPill M-shell
            </a>{" "}
          </li>
          <li>
            Custom Loader – option to use a custom loader if you prefer to modify or create your own configuration
          </li>
        </ul>

        <p className="mb-4">The script simplifies the VM creation process by offering the following options:</p>
        <ul className="list-disc pl-5 mb-4">
          <li>Selection of default or advanced configuration</li>
          <li>Configuration of CPU, RAM, BIOS, and machine type</li>
          <li>Choice between virtual disk or physical disk passthrough</li>
        </ul>

        <div className="mt-8">
          <h3 className="text-xl font-semibold mb-3 flex items-center">
            <Settings className="h-5 w-5 mr-2 text-blue-500" />
            Default and Advanced Configuration
          </h3>
          <p className="mb-3">The script offers two configuration modes:</p>

          <h4 className="text-lg font-medium mt-12 mb-2 flex items-center">
            <Zap className="h-5 w-5 mr-2 text-green-500" />
            Default Configuration
          </h4>
          <p className="mb-3">
            If you select default configuration, the script will automatically apply the following values:
          </p>

          <div className="overflow-x-auto mb-4">
            <table className="min-w-full bg-white border border-gray-200">
              <thead>
                <tr>
                  <th className="py-2 px-4 border-b border-gray-200 bg-gray-50 text-left">Parameter</th>
                  <th className="py-2 px-4 border-b border-gray-200 bg-gray-50 text-left">Default Value</th>
                </tr>
              </thead>
              <tbody>
                <tr>
                  <td className="py-2 px-4 border-b border-gray-200">Machine Type</td>
                  <td className="py-2 px-4 border-b border-gray-200">q35</td>
                </tr>
                <tr>
                  <td className="py-2 px-4 border-b border-gray-200">BIOS Type</td>
                  <td className="py-2 px-4 border-b border-gray-200">OVMF (UEFI)</td>
                </tr>
                <tr>
                  <td className="py-2 px-4 border-b border-gray-200">CPU Type</td>
                  <td className="py-2 px-4 border-b border-gray-200">Host</td>
                </tr>
                <tr>
                  <td className="py-2 px-4 border-b border-gray-200">Core Count</td>
                  <td className="py-2 px-4 border-b border-gray-200">2</td>
                </tr>
                <tr>
                  <td className="py-2 px-4 border-b border-gray-200">RAM Size</td>
                  <td className="py-2 px-4 border-b border-gray-200">4096 MB</td>
                </tr>
                <tr>
                  <td className="py-2 px-4 border-b border-gray-200">Bridge</td>
                  <td className="py-2 px-4 border-b border-gray-200">vmbr0</td>
                </tr>
                <tr>
                  <td className="py-2 px-4 border-b border-gray-200">MAC Address</td>
                  <td className="py-2 px-4 border-b border-gray-200">Automatically generated</td>
                </tr>
                <tr>
                  <td className="py-2 px-4 border-b border-gray-200">Start VM on Completion</td>
                  <td className="py-2 px-4 border-b border-gray-200">No</td>
                </tr>
              </tbody>
            </table>
          </div>
          <p className="mb-4">
            If you want to customize the configuration, select the Advanced Settings option in the menu.
          </p>

          <h4 className="text-lg font-medium mt-12 mb-2 flex items-center">
            <Sliders className="h-5 w-5 mr-2 text-orange-500" />
            Advanced Configuration
          </h4>
          <p className="mb-3">
            If you select advanced configuration, the script will allow you to customize each parameter:
          </p>

          <div className="overflow-x-auto mb-4">
            <table className="min-w-full bg-white border border-gray-200">
              <thead>
                <tr>
                  <th className="py-2 px-4 border-b border-gray-200 bg-gray-50 text-left">Parameter</th>
                  <th className="py-2 px-4 border-b border-gray-200 bg-gray-50 text-left">Options</th>
                </tr>
              </thead>
              <tbody>
                <tr>
                  <td className="py-2 px-4 border-b border-gray-200">Machine Type</td>
                  <td className="py-2 px-4 border-b border-gray-200">q35 or i440fx</td>
                </tr>
                <tr>
                  <td className="py-2 px-4 border-b border-gray-200">BIOS Type</td>
                  <td className="py-2 px-4 border-b border-gray-200">OVMF (UEFI) or SeaBIOS (Legacy)</td>
                </tr>
                <tr>
                  <td className="py-2 px-4 border-b border-gray-200">CPU Type</td>
                  <td className="py-2 px-4 border-b border-gray-200">Host or KVM64</td>
                </tr>
                <tr>
                  <td className="py-2 px-4 border-b border-gray-200">Core Count</td>
                  <td className="py-2 px-4 border-b border-gray-200">Number of CPU cores</td>
                </tr>
                <tr>
                  <td className="py-2 px-4 border-b border-gray-200">RAM Size</td>
                  <td className="py-2 px-4 border-b border-gray-200">Amount of memory allocated to the VM</td>
                </tr>
                <tr>
                  <td className="py-2 px-4 border-b border-gray-200">Bridge</td>
                  <td className="py-2 px-4 border-b border-gray-200">Network bridge for connection</td>
                </tr>
                <tr>
                  <td className="py-2 px-4 border-b border-gray-200">MAC Address</td>
                  <td className="py-2 px-4 border-b border-gray-200">Custom MAC address</td>
                </tr>
                <tr>
                  <td className="py-2 px-4 border-b border-gray-200">VLAN</td>
                  <td className="py-2 px-4 border-b border-gray-200">VLAN tag (if used)</td>
                </tr>
                <tr>
                  <td className="py-2 px-4 border-b border-gray-200">MTU</td>
                  <td className="py-2 px-4 border-b border-gray-200">Maximum Transmission Unit size</td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>

        <div className="mt-8">
          <h3 className="text-xl font-semibold mb-3 flex items-center">
            <HardDrive className="h-5 w-5 mr-2 text-blue-500" />
            Disk Selection
          </h3>
          <p className="mb-3">
            Once the machine is configured, the script allows you to choose between two types of disks:
          </p>

          <h4 className="text-lg font-medium mt-4 mb-2">Virtual Disk</h4>
          <ul className="list-disc pl-5 mb-4">
            <li>The script lists the storage options available in Proxmox</li>
            <li>The user selects the disk and size in GB</li>
            <li>The virtual disk is automatically assigned to the VM. If more disks are configured, they will be added as <strong>SATA</strong> (e.g., sata0, sata1, etc.), up to a maximum of 6 virtual disks.</li>
          </ul>

          <h4 className="text-lg font-medium mt-4 mb-2">Physical Disk Passthrough</h4>
          <ul className="list-disc pl-5 mb-4">
            <li>The script detects all available physical disks</li>
            <li>The user selects the physical disk or disks they want to use.</li>
            <li>The physical disk is directly assigned to the VM via passthrough. If more disks are configured, they will be added as <strong>SATA</strong> (e.g., sata0, sata1, etc.), up to a maximum of 6 physical disks.</li>
          </ul>
        </div>

        <div className="mt-8">
        <h3 className="text-xl font-semibold mb-3 flex items-center">
            <Download className="h-5 w-5 mr-2 text-blue-500" />
            Loader Installation
        </h3>
        <p className="mb-3">
            The script automatically downloads and extracts the loader from the developer's repository. If the download fails, the script will display an error message.
        </p>
        <p className="mb-4">
            <strong>AuxXxilium Arc</strong>, <strong>RedPill RR</strong>, and <strong>TinyCore RedPill M-shell</strong>.  
            <span className="block mt-1">Downloads and extracts automatically.</span>
        </p>
        <p className="mb-4">
            For <strong>Custom Loader</strong>, the script searches for files in <code>/var/lib/vz/template/iso</code>. 
            If multiple files are found, you will be prompted to select the desired file.  
        </p>   
        <p className="mt-12 mb-4"></p>
        <p>You can upload custom loaders from the local storage options:</p>

        <ImageWithCaption
                src="/images/design-mode/add_loader.png" 
                alt="Add Custom Loader" 
                caption="Add Custom Loader"
              />
        </div>


        <div className="mt-16">
          <h3 className="text-xl font-semibold mb-3 flex items-center">
            <Cpu className="h-5 w-5 mr-2 text-blue-500" />
            VM Creation
          </h3>
          <p className="mb-3">Once the loader is downloaded, the script creates the VM using the following commands:</p>
          <ul className="list-disc pl-5 mb-4">
            <li>
              <code>qm create</code> – Creates the virtual machine with the configured parameters
            </li>
            <li>
              <code>qm importdisk</code> – Imports the boot loader disk to the VM. For greater compatibility the loader is imported as an IDE disk
            </li>
            <li>
              <code>qm set</code> – Assigns configuration values such as CPU, RAM, and storage
            </li>
            <li>
              <code>qm set -boot</code> – Configures the boot order
            </li>
          </ul>
        </div>
      </section>

      <section className="mb-10">
        <h2 className="text-2xl font-semibold mt-24 mb-4 flex items-center">
          <Wrench className="h-6 w-6 mr-2 text-blue-500" />
          Step-by-Step Boot Loader Configuration Guide
        </h2>
        <p className="mb-4">
        While all loaders share similarities, each one has its own structure and configuration methods. 
        This section provides a basic guide covering the 6 steps involved in setting up a Synology DSM loader. 
        The exact steps may vary depending on the loader and any changes introduced by the developer. 
        Therefore, understanding these common basic steps is crucial to correctly building and configuring 
        the loader of your choice for proper Synology DSM functionality.
        </p>


        {/* Selector de loader global */}
        <div className="bg-blue-50 p-4 rounded-lg mb-6">
          <h3 className="text-lg font-semibold mb-2">Select your loader type:</h3>
          <div className="flex space-x-4">
            <button
              onClick={() => setActiveLoader("arc")}
              className={`px-4 py-2 rounded-md font-medium ${
                activeLoader === "arc"
                  ? "bg-blue-500 text-white"
                  : "bg-white border border-gray-300 text-gray-700 hover:bg-gray-50"
              }`}
            >
              Arc Loader
            </button>
            <button
              onClick={() => setActiveLoader("rr")}
              className={`px-4 py-2 rounded-md font-medium ${
                activeLoader === "rr"
                  ? "bg-blue-500 text-white"
                  : "bg-white border border-gray-300 text-gray-700 hover:bg-gray-50"
              }`}
            >
              RR Loader
            </button>
            <button
              onClick={() => setActiveLoader("tinycore")}
              className={`px-4 py-2 rounded-md font-medium ${
                activeLoader === "tinycore"
                  ? "bg-blue-500 text-white"
                  : "bg-white border border-gray-300 text-gray-700 hover:bg-gray-50"
              }`}
            >
              TinyCore Loader
            </button>
          </div>
        </div>
      </section>

      <section className="mb-12 border-b pb-8">
        <h2 className="text-xl font-semibold mb-4 flex items-center" id="step1">
          <StepNumber number={1} />
          Start the VM and Access the Main Menu
        </h2>
        <p className="mb-4">
        Once the VM is created, start it. The first time you boot the VM, you'll access the loader's main menu to select 
        and configure the DSM model you want to build. Once the loader is created, this step will be skipped unless you 
        manually force a reconfiguration from the boot monitor. All loaders also have the option to configure the loader 
        via a web interface.
        </p>

        <div className="mt-6">
          {activeLoader === "arc" && (
            <div className="flex flex-col space-y-8">

              <p className="mt-16 mb-2">
                  <strong>Web interface</strong>, To access the web interface, simply open a web browser and enter 
                  the IP address shown in the VM's console output. For example, in our case: http://192.169.0.32.
                </p>

              <ImageWithCaption
                src="/images/design-mode/arc_1_0_1.png"
                alt="Arc Loader Web Interface"
                caption="Arc Loader Web Interface"
              />

            <p className="mt-16 mb-2">
                  <strong>Terminal interface</strong>, Access it directly from the VM's console output.
                </p>

              <ImageWithCaption
                src="/images/design-mode/arc_1_1_1.png"
                alt="Arc Loader Terminal Interface"
                caption="Arc Loader Terminal Interface"
              />
            </div>
          )}

          {activeLoader === "rr" && (
            <div className="flex flex-col space-y-8">
              
              <p className="mt-16 mb-2">
                <strong>Web interface</strong>, To access the web interface, simply open a web browser and enter 
                the IP address shown in the VM's console output, followed by port <strong>7681</strong>.  
                For example, in our case: <code>http://192.169.0.33:7681</code>.
              </p>

              <ImageWithCaption
                src="/images/design-mode/rr_2_0_2.png"
                alt="RR Command Example"
                caption="RR Loader Web Interface"
              />

              <p className="mt-16 mb-2">
                  <strong>Terminal interface</strong>, Access it directly from the VM's console output by typing <strong>menu.sh</strong> on the screen
                </p>

              <ImageWithCaption
                src="/images/design-mode/rr_2_1_1.png"
                alt="RR Loader Interface"
                caption="RR Loader Terminal Interface"
              />     
            </div>
          )}

          {activeLoader === "tinycore" && (
            <div className="flex flex-col space-y-8">

<p className="mt-16 mb-2">
                <strong>Web interface</strong>, To access the web interface, simply open a web browser and enter 
                the IP address shown in the VM's console output, followed by port <strong>7681</strong>.  
                For example, in our case: <code>http://192.169.0.35:7681</code>.
              </p>

              <ImageWithCaption
                src="/images/design-mode/tinycore_3_0_1.png"
                alt="TinyCore Loader Interface"
                caption="TinyCore Loader Web Interface"
              />

               <p className="mt-16 mb-2">
                <strong>Terminal interface</strong>, Access it directly from the VM's console output. Keep an eye on 
                the screen, as at some point it may prompt you to press a key to continue or ask if you want to change the language.
                </p>

              <ImageWithCaption
                src="/images/design-mode/tinycore_3_1_1.png"
                alt="TinyCore Loader Interface"
                caption="TinyCore Loader Terminal Interface"
              />
            </div>
          )}
        </div>
      </section>

      <section className="mb-12 border-b pb-8">
        <h2 className="text-xl font-semibold mb-4 flex items-center" id="step2">
          <StepNumber number={2} />
          Select Model
        </h2>
        <p className="mb-4">
          After loading the menu, select the Synology DSM model you want to install. Depending on the loader, you may
          sometimes need to expand the options to see more models.
        </p>

        <div className="mt-6">
          {activeLoader === "arc" && (
            <div className="flex flex-col space-y-8">
              <ImageWithCaption
                src="/images/design-mode/arc_1_2_1.png"
                alt="Arc Model Selection"
                caption="Arc Model Selection"
              />
            </div>
          )}

          {activeLoader === "rr" && (
            <div className="flex flex-col space-y-8">
              <ImageWithCaption
                src="/images/design-mode/rr_2_2_1.png"
                alt="RR Model Selection"
                caption="RR Model Selection"
              />
            </div>
          )}

          {activeLoader === "tinycore" && (
            <div className="flex flex-col space-y-8">
              <ImageWithCaption
                src="/images/design-mode/tinycore_3_2_1.png"
                alt="TinyCore Model Selection"
                caption="TinyCore Model Selection"
              />
            </div>
          )}
        </div>
        <p className="mt-4">In our example, we'll choose the SA6400 model.</p>
      </section>

      <section className="mb-12 border-b pb-8">
        <h2 className="text-xl font-semibold mb-4 flex items-center" id="step3">
          <StepNumber number={3} />
          Select DSM Version
        </h2>
        <p className="mb-4">
          After selecting the model, you need to choose the DSM version you want to install.
        </p>

        <div className="mt-6">
          {activeLoader === "arc" && (
            <div className="flex flex-col space-y-16">
              <ImageWithCaption
                src="/images/design-mode/arc_1_3_1.png"
                alt="Arc Version Selection - Step 1"
                caption="Arc Version Selection - Step 1"
              />
              <ImageWithCaption
                src="/images/design-mode/arc_1_3_2.png"
                alt="Arc Version Selection - Step 2"
                caption="Arc Version Selection - Step 2"
              />
            </div>
          )}

          {activeLoader === "rr" && (
            <div className="flex flex-col space-y-16">
              <ImageWithCaption
                src="/images/design-mode/rr_2_3_1.png"
                alt="RR Version Selection - Step 1"
                caption="RR Version Selection - Step 1"
              />
              <ImageWithCaption
                src="/images/design-mode/rr_2_3_2.png"
                alt="RR Version Selection - Step 2"
                caption="RR Version Selection - Step 2"
              />
              <ImageWithCaption
                src="/images/design-mode/rr_2_3_3.png"
                alt="RR Version Selection - Step 3"
                caption="RR Version Selection - Step 3"
              />
            </div>
          )}

          {activeLoader === "tinycore" && (
            <div className="flex flex-col space-y-16">
              <ImageWithCaption
                src="/images/design-mode/tinycore_3_3_1.png"
                alt="TinyCore Version Selection - Step 1"
                caption="TinyCore Version Selection - Step 1"
              />
              <ImageWithCaption
                src="/images/design-mode/tinycore_3_3_2.png"
                alt="TinyCore Version Selection - Step 2"
                caption="TinyCore Version Selection - Step 2"
              />
            </div>
          )}
        </div>
      </section>

      <section className="mb-12 border-b pb-8">
        <h2 className="text-xl font-semibold mb-4 flex items-center" id="step4">
          <StepNumber number={4} />
          Select Addons
        </h2>
        <p className="mb-4">This step allows you to add additional features or custom configurations to the loader.</p>

        <div className="mt-6">
          {activeLoader === "arc" && (
            <div className="flex flex-col space-y-16">
              <p className="mb-2">
                <strong>Arc</strong> gives you the option to configure automatically or manually adjust the settings. 
                If automatic configuration is selected, the loader will start applying the necessary settings and will 
                automatically reboot once the process is complete.
              </p>
              <ImageWithCaption
                src="/images/design-mode/arc_1_4_1.png"
                alt="Arc Auto Configuration"
                caption="Arc Auto Configuration"
              />
              <p className="mb-2">
                If we choose not to use automatic mode, we enter the menu to configure different options necessary for
                the loader:
              </p>
              <ImageWithCaption
                src="/images/design-mode/arc_1_4_2.png"
                alt="Arc Manual Configuration"
                caption="Arc Manual Configuration"
              />
              <ImageWithCaption
                src="/images/design-mode/arc_1_4_3.png"
                alt="Arc SN/Mac Configuration"
                caption="Arc SN/Mac Configuration"
              />
              <ImageWithCaption
                src="/images/design-mode/arc_1_4_4.png"
                alt="Arc Sata Portmap"
                caption="Arc Sata Portmap (use the recommended option)"
              />
              <ImageWithCaption
                src="/images/design-mode/arc_1_4_5.png"
                alt="Arc Addons Selection"
                caption="Arc Addons Selection"
              />
            </div>
          )}

          {activeLoader === "rr" && (
            <div className="flex flex-col space-y-8">
              <ImageWithCaption
                src="/images/design-mode/rr_2_4_1.png"
                alt="RR Addon Step 1"
                caption="RR Addon Step 1"
              />
              <ImageWithCaption
                src="/images/design-mode/rr_2_4_2.png"
                alt="RR Addon Step 2"
                caption="RR Addon Step 2 - Press to add addons"
              />
              <ImageWithCaption
                src="/images/design-mode/rr_2_4_3.png"
                alt="RR Addon Step 3"
                caption="RR Addon Step 3 - Select the one you want by clicking on it. If you want to add more, repeat the process from images 2.4.2 and 2.4.3"
              />
            </div>
          )}

          {activeLoader === "tinycore" && (
            <div className="flex flex-col space-y-8">
              <ImageWithCaption
                src="/images/design-mode/tinycore_3_4_1.png"
                alt="TinyCore SN Configuration"
                caption="TinyCore SN Configuration"
              />
              <ImageWithCaption
                src="/images/design-mode/tinycore_3_4_2.png"
                alt="TinyCore Random Option"
                caption="TinyCore Random Option - The random option is recommended"
              />
              <ImageWithCaption
                src="/images/design-mode/tinycore_3_4_3.png"
                alt="TinyCore MAC Configuration"
                caption="TinyCore MAC Configuration"
              />
              <ImageWithCaption
                src="/images/design-mode/tinycore_3_4_4.png"
                alt="TinyCore VM MAC"
                caption="TinyCore VM MAC - Choose to use your VM's MAC or a random one"
              />
            </div>
          )}
        </div>
      </section>

      <section className="mb-12 border-b pb-8">
        <h2 className="text-xl font-semibold mb-4 flex items-center" id="step5">
          <StepNumber number={5} />
          Build the Loader
        </h2>
        <p className="mb-4">
          Once you have selected the model, DSM version, and addons, proceed to build the loader. This process might
          take a few minutes depending on the loader and the selected configuration. To start, select the "Build the
          Loader" option.
        </p>

        <div className="mt-6">
          {activeLoader === "arc" && (
            <div className="flex flex-col space-y-8">
              <ImageWithCaption
                src="/images/design-mode/arc_1_5_1.png"
                alt="Arc Build Loader"
                caption="Arc Build Loader"
              />
            </div>
          )}

          {activeLoader === "rr" && (
            <div className="flex flex-col space-y-8">
              <ImageWithCaption
                src="/images/design-mode/rr_2_5_1.png"
                alt="RR Build Loader"
                caption="RR Build Loader"
              />
            </div>
          )}

          {activeLoader === "tinycore" && (
            <div className="flex flex-col space-y-8">
              <ImageWithCaption
                src="/images/design-mode/tinycore_3_5_1.png"
                alt="TinyCore Build Loader"
                caption="TinyCore Build Loader"
              />
            </div>
          )}
        </div>
      </section>

      <section className="mb-12 border-b pb-8">
        <h2 className="text-xl font-semibold mb-4 flex items-center" id="step6">
          <StepNumber number={6} />
          Boot the Loader
        </h2>
        <p className="mb-4">
          Once the loader has been built, it will prompt you to boot. The VM will restart with the configuration you've
          created and start the DSM installation.
        </p>

        <div className="mt-6">
          {activeLoader === "arc" && (
            <div className="flex flex-col space-y-8">
              <ImageWithCaption
                src="/images/design-mode/arc_1_6_1.png"
                alt="Arc Boot Loader"
                caption="Arc Boot Loader"
              />
            </div>
          )}

          {activeLoader === "rr" && (
            <div className="flex flex-col space-y-8">
              <ImageWithCaption
                src="/images/design-mode/rr_2_6_1.png"
                alt="RR Boot Loader"
                caption="RR Boot Loader"
              />
            </div>
          )}

          {activeLoader === "tinycore" && (
            <div className="flex flex-col space-y-8">
              <ImageWithCaption
                src="/images/design-mode/tinycore_3_6_1.png"
                alt="TinyCore Boot Loader"
                caption="TinyCore Boot Loader"
              />
            </div>
          )}
        </div>
      </section>

      {/* STARTING DSM INSTALLATION */}
      <section className="mb-8">
        <h2 className="text-xl font-semibold mb-4 flex items-center">
          <CheckCircle className="h-6 w-6 mr-3 text-green-500" />
          Starting the DSM Installation
        </h2>
        <p className="mb-4">Once the loader is booted, you can find your Synology device using:</p>
        <div className="bg-gray-100 p-4 rounded-md overflow-x-auto text-sm mb-4">
          <code>https://finds.synology.com</code>
        </div>
        <p className="mb-6">Follow the on-screen steps to complete the DSM installation.</p>
        <div className="flex flex-col space-y-8">
          <ImageWithCaption
            src="/images/design-mode/install_DSM.png"
            alt="DSM Setup"
            caption="DSM Setup Screen"
          />
          <p className="mt-8 mb-8">
          Please be patient – The process may take a few minutes to complete. The progress percentage will 
          update automatically as the setup progresses. A countdown will start once the installation 
          is nearing completion.
        </p>
          <ImageWithCaption
            src="/images/design-mode/finish_install_DSM.png"
            alt="Installation Complete"
            caption="Installation Complete"
          />
        </div>
      </section>

      <section className="mb-8">
        <h2 className="text-2xl font-semibold mt-20 mb-4 flex items-center">
          <Target className="h-6 w-6 mr-2 text-blue-500" />
          Tips
        </h2>
        <ul className="list-disc pl-5 space-y-4">
          <li>
            Keep in mind that available options may change depending on the loader version and developer updates. If you
            encounter issues during the loader creation process, consult the loader documentation:
          </li>

          <div className="flex flex-wrap gap-4 mt-2">
              <a
                href="https://github.com/AuxXxilium/arc"
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center px-3 py-2 text-sm font-medium rounded-md bg-gray-100 text-gray-800 hover:bg-gray-200 transition-colors"
              >
                <Github className="h-5 w-5 mr-2" />
                Arc Documentation
              </a>
              <a
                href="https://github.com/RROrg/rr"
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center px-3 py-2 text-sm font-medium rounded-md bg-gray-100 text-gray-800 hover:bg-gray-200 transition-colors"
              >
                <Github className="h-5 w-5 mr-2" />
                RR Documentation
              </a>
              <a
                href="https://github.com/PeterSuh-Q3/tinycore-redpill"
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center px-3 py-2 text-sm font-medium rounded-md bg-gray-100 text-gray-800 hover:bg-gray-200 transition-colors"
              >
                <Github className="h-5 w-5 mr-2" />
                TinyCore Documentation
              </a>
            </div>

          <li>
            Some older DSM models may have issues recognizing disks or the network card. It is recommended to use more
            recent models.
          </li>

          <div className="bg-blue-100 border-l-4 border-blue-500 text-blue-700 p-4 mb-4">
            <p className="font-semibold">Update:</p>
            <p>
            Some loaders offer the option to update the loader directly from the menu.
            </p>
          </div>

          <div className="bg-yellow-100 border-l-4 border-yellow-500 text-yellow-700 p-4 mb-4">
            <p className="font-semibold">Important:</p>
            <p>
            ProxMenux does not provide support for the different loaders.
            </p>
          </div>

        </ul>
      </section>
    </div>
  )
}



function ImageWithCaption({ src, alt, caption }: { src: string; alt: string; caption: string }) {
  return (
    <div className="flex flex-col items-center w-full max-w-[768px] mx-auto my-4">
      <div className="w-full rounded-md overflow-hidden">
        <Image
          src={src || "/placeholder.svg"}
          alt={alt}
          width={768}
          height={0}
          style={{ height: "auto" }}
          className="object-contain w-full"
          sizes="(max-width: 768px) 100vw, 768px"
        />
      </div>
      <span className="mt-2 text-sm text-gray-600">{caption}</span>
    </div>
  )
}

function StepNumber({ number }: { number: number }) {
  return (
    <div
      className="inline-flex items-center justify-center w-8 h-8 mr-3 text-white bg-blue-500 rounded-full"
      aria-hidden="true"
    >
      <span className="text-sm font-bold">{number}</span>
    </div>
  )
}
