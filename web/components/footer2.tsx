"use client"

import Link from "next/link"
import { MessageCircle } from "lucide-react"
import Image from "next/image"

export default function Footer() {
  return (
    <footer className="bg-gray-900 text-white py-12">
      <div className="container mx-auto px-4 sm:px-6 lg:px-8">
        <div className="flex flex-col md:flex-row justify-between">
          
             {/* Support Section - Left Side */}
          <div className="flex items-start mb-8 md:mb-0">
            <a
              href="https://ko-fi.com/G2G313ECAN"
              target="_blank"
              rel="noopener noreferrer"
              className="hover:opacity-90 transition-opacity"
            >
              <Image
                src="/images/design-mode/kofi.png"
                alt="Support me on Ko-fi"
                width={140}
                height={40}
                className="w-[140px]"
                loading="lazy"
              />
            </a>
          </div>

          {/* Connect Section - Right Side */}
          <div className="flex flex-col items-start md:items-end">
            <h4 className="text-lg font-semibold mb-4">Connect</h4>
            <p className="text-gray-400 mb-4 max-w-md md:text-right">
              Join the community discussions on GitHub to get help, share ideas, and contribute to the project. Every idea is welcome!
            </p>
            <Link
              href="https://github.com/MacRimi/ProxMenux/discussions"
              className="flex items-center text-blue-400 hover:text-blue-300 transition-colors duration-200"
              target="_blank"
              rel="noopener noreferrer"
            >
              <MessageCircle className="mr-2 h-5 w-5" />
              Join the Discussion
            </Link>
          </div>
        </div>

        {/* Copyright - Center */}
        <div className="mt-8 pt-8 border-t border-gray-800 text-center text-gray-400">
        <p>
          ProxMenux, an open-source and collaborative project by{' '}
          <a
            href="https://macrimi.pro"
            target="_blank"
            rel="noopener noreferrer"
            className="text-blue-400 hover:underline"
          >
            MacRimi
          </a>.
        </p>
      </div>
      </div>
    </footer>
  )
}
