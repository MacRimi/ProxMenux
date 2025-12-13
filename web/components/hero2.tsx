"use client"

import { Button } from "@/components/ui/button"
import { ArrowRight } from "lucide-react"
import Link from "next/link"
import Image from "next/image"

export default function Hero() {
  return (
    <div className="bg-gradient-to-b from-gray-900 to-gray-800 text-white">
      {/* Mobile version (visible only on small screens) */}
      <section className="md:hidden py-20 px-4 sm:px-6 text-center">
        <h1 className="text-4xl sm:text-5xl font-extrabold mb-6">
          ProxMenux{" "}
          <span className="block mt-2 bg-clip-text text-transparent bg-gradient-to-r from-blue-400 to-purple-500 font-bold">
            An Interactive Menu for Proxmox VE Management
          </span>
        </h1>
        <p className="text-base sm:text-lg mb-8 max-w-4xl mx-auto text-gray-300">
          ProxMenux is a management tool for Proxmox VE that simplifies system administration through an interactive
          menu, allowing you to execute commands and scripts with ease.
        </p>
        <div className="flex justify-center">
          <Button size="lg" className="bg-blue-500 hover:bg-blue-600" asChild>
            <Link href="/docs/installation">
              Install Now
              <ArrowRight className="ml-2 h-4 w-4" />
            </Link>
          </Button>
        </div>
      </section>

      {/* Desktop version (visible only on medium and large screens) */}
      <section className="hidden md:flex py-20 px-4 sm:px-6 lg:px-8 flex-col justify-center">
        <div className="flex items-center justify-center mb-8">
          <div className="flex items-center">
            <div className="w-40 h-40 lg:w-48 lg:h-48 xl:w-56 xl:h-56 relative">
              <Image
                src="https://raw.githubusercontent.com/MacRimi/ProxMenux/main/images/logo.png"
                alt="ProxMenux Logo"
                fill
                className="object-contain"
                sizes="(max-width: 1024px) 10rem, (max-width: 1280px) 12rem, 14rem"
              />
            </div>
            <div className="w-0.5 h-40 lg:h-48 xl:h-56 bg-white mx-6 self-center"></div>
            <div className="text-left max-w-md lg:max-w-lg xl:max-w-xl">
              <h1 className="text-4xl md:text-5xl lg:text-6xl font-extrabold text-white leading-tight">ProxMenux</h1>
              <p className="text-xl md:text-2xl lg:text-3xl xl:text-4xl mt-2 bg-clip-text text-transparent bg-gradient-to-r from-blue-400 to-purple-500 font-bold leading-tight">
                An Interactive Menu for Proxmox VE Management
              </p>
            </div>
          </div>
        </div>
        <p className="text-base md:text-lg lg:text-xl mb-8 max-w-2xl lg:max-w-3xl xl:max-w-4xl mx-auto text-gray-300 text-center leading-relaxed">
          ProxMenux is a management tool for Proxmox VE that simplifies system administration through an interactive
          menu, allowing you to execute commands and scripts with ease.
        </p>
        <div className="flex justify-center">
          <Button size="lg" className="bg-blue-500 hover:bg-blue-600" asChild>
            <Link href="/docs/installation">
              Install Now
              <ArrowRight className="ml-2 h-4 w-4" />
            </Link>
          </Button>
        </div>
      </section>
    </div>
  )
}

