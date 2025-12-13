"use client"

import { Button } from "@/components/ui/button"
import { Star } from "lucide-react"

export default function SupportProject() {
  const handleClick = () => {
    window.open("https://github.com/MacRimi/ProxMenux", "_blank")
  }

  return (
    <section className="py-16 bg-gray-900">
      <div className="container mx-auto px-4 text-center">
        <h2 className="text-3xl font-bold mb-6">Support the Project!</h2>
        <p className="text-xl mb-8">
          If you find <span className="font-bold">ProxMenux</span> useful, consider giving it a ⭐ on GitHub to help
          others discover it!
        </p>
        <div className="flex justify-center items-center">
          <Button className="bg-yellow-400 text-gray-900 hover:bg-yellow-500" onClick={handleClick}>
            <Star className="mr-2" />
            Star on GitHub
          </Button>
        </div>
      </div>
    </section>
  )
}

