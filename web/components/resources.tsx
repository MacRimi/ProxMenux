"use client"

import { Book, GitBranch, FileText, Github } from "lucide-react"
import { Link } from "@/i18n/navigation"
import NextLink from "next/link"
import { useTranslations } from "next-intl"

export default function Resources() {
  const t = useTranslations("resources")

  // External link to GitHub stays on next/link to avoid the locale
  // prefix; the three internal links use the locale-aware Link so they
  // route under /[locale]/ automatically.
  const resources = [
    { key: "documentation", icon: <Book className="h-6 w-6" />,       link: "/docs/introduction", external: false },
    { key: "changelog",     icon: <FileText className="h-6 w-6" />,   link: "/changelog",          external: false },
    { key: "guides",        icon: <GitBranch className="h-6 w-6" />,  link: "/guides",             external: false },
    { key: "github",        icon: <Github className="h-6 w-6" />,     link: "https://github.com/MacRimi/ProxMenux", external: true },
  ] as const

  return (
    <section className="py-20 bg-gray-900">
      <div className="container mx-auto px-4">
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-8">
          {resources.map((resource) => {
            const title = t(`${resource.key}.title`)
            const description = t(`${resource.key}.description`)
            const inner = (
              <div className="bg-gray-800 p-6 rounded-lg shadow-lg hover:bg-gray-700 transition-colors duration-200 h-full flex flex-col justify-between">
                <div className="flex items-center mb-4">
                  {resource.icon}
                  <h3 className="text-xl font-semibold ml-2">{title}</h3>
                </div>
                <p className="text-gray-400 min-h-[48px]">{description}</p>
              </div>
            )
            return resource.external ? (
              <NextLink
                key={resource.key}
                href={resource.link}
                target="_blank"
                rel="noopener noreferrer"
                className="block h-full"
              >
                {inner}
              </NextLink>
            ) : (
              <Link key={resource.key} href={resource.link} className="block h-full">
                {inner}
              </Link>
            )
          })}
        </div>
      </div>
    </section>
  )
}
