"use client"

import Link from "next/link"
import { MessageCircle } from "lucide-react"
import Image from "next/image"
import { useTranslations } from "next-intl"

export default function Footer() {
  const t = useTranslations("footer")

  return (
    <footer className="bg-gray-900 text-white py-12">
      <div className="container mx-auto px-4 sm:px-6 lg:px-8">
        <div className="flex flex-col md:flex-row justify-between">
          {/* Support Section - Left Side */}
          <div className="flex flex-col items-start mb-8 md:mb-0">
            <h4 className="text-lg font-semibold mb-4">{t("sponsorHeading")}</h4>
            <p className="text-gray-400 mb-4 max-w-md">{t("sponsorBody")}</p>
            <a
              href="https://ko-fi.com/G2G313ECAN"
              target="_blank"
              rel="noopener noreferrer"
              className="hover:opacity-90 transition-opacity flex items-center"
            >
              <Image
                src="https://raw.githubusercontent.com/MacRimi/ProxMenux/main/images/kofi.png"
                alt={t("sponsorAlt")}
                width={140}
                height={40}
                className="w-[140px]"
                style={{ height: "auto" }}
                loading="lazy"
                unoptimized
              />
            </a>
          </div>

          {/* Connect Section - Right Side */}
          <div className="flex flex-col items-start md:items-end">
            <h4 className="text-lg font-semibold mb-4">{t("connectHeading")}</h4>
            <p className="text-gray-400 mb-4 max-w-md md:text-right">{t("connectBody")}</p>
            <Link
              href="https://github.com/MacRimi/ProxMenux/discussions"
              className="flex items-center text-blue-400 hover:text-blue-300 transition-colors duration-200"
              target="_blank"
              rel="noopener noreferrer"
            >
              <MessageCircle className="mr-2 h-5 w-5" />
              {t("joinDiscussion")}
            </Link>
          </div>
        </div>

        {/* Copyright - Center */}
        <div className="mt-8 pt-8 border-t border-gray-800 text-center text-gray-400">
          <p>
            {t("copyrightPrefix")}{" "}
            <a
              href="https://macrimi.pro"
              target="_blank"
              rel="noopener noreferrer"
              className="text-blue-400 hover:underline"
            >
              MacRimi
            </a>
            {t("copyrightSuffix")}
          </p>
        </div>
      </div>
    </footer>
  )
}
