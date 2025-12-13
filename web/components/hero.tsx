"use client"

import { Button } from "@/components/ui/button"
import { ArrowRight } from "lucide-react"
import Link from "next/link"


export default function Hero() {
  return (
    <section className="py-20 px-4 sm:px-6 lg:px-8 text-center">
      <h1 className="text-4xl sm:text-5xl md:text-6xl font-extrabold mb-6">
        ProxMenux{" "}
        <span className="bg-clip-text text-transparent bg-gradient-to-r from-blue-400 to-purple-500">
        An Interactive Menu for Proxmox VE Management
        </span>
      </h1>
      <p className="text-base sm:text-lg md:text-xl mb-8 max-w-4xl mx-auto text-gray-300">
      ProxMenux is a management tool for Proxmox VE that simplifies system administration 
      through an interactive menu, allowing you to execute commands and scripts with ease.
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
  )
}
