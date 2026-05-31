"use client"

import { Button } from "@/components/ui/button"
import { Star } from "lucide-react"
import { useTranslations } from "next-intl"

export default function SupportProject() {
  const t = useTranslations("supportProject")
  const handleClick = () => {
    window.open("https://github.com/MacRimi/ProxMenux", "_blank")
  }

  return (
    <section className="py-16 bg-gray-900">
      <div className="container mx-auto px-4 text-center">
        <h2 className="text-3xl font-bold mb-6">{t("heading")}</h2>
        <p className="text-xl mb-8">
          {t.rich("body", {
            strong: (chunks) => <span className="font-bold">{chunks}</span>,
          })}
        </p>
        <div className="flex justify-center items-center">
          <Button className="bg-yellow-400 text-gray-900 hover:bg-yellow-500" onClick={handleClick}>
            <Star className="mr-2" />
            {t("button")}
          </Button>
        </div>
      </div>
    </section>
  )
}

