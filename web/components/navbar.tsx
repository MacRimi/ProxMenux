"use client"

import Link from "next/link"
import Image from "next/image"
import { Book, GitBranch, FileText, Github, Menu, Rss } from "lucide-react"
import { useState } from "react"

export default function Navbar() {
  const [isMenuOpen, setIsMenuOpen] = useState(false)

  const navItems = [
    { href: "/docs/introduction", icon: <Book className="h-4 w-4" />, label: "Documentation" },
    { href: "/changelog", icon: <FileText className="h-4 w-4" />, label: "Changelog" },
    { href: "/guides", icon: <GitBranch className="h-4 w-4" />, label: "Guides" },
    { href: "https://github.com/MacRimi/ProxMenux", icon: <Github className="h-4 w-4" />, label: "GitHub" },
  ]

  return (
    <header className="fixed top-0 left-0 right-0 z-50 bg-background/95 backdrop-blur border-b border-border/40">
      <div className="container mx-auto px-4">
        <div className="flex items-center justify-between h-16">
          <Link href="/" className="flex items-center space-x-2">
            <Image
              src="https://raw.githubusercontent.com/MacRimi/ProxMenux/main/images/logo.png"
              alt="ProxMenux Logo"
              width={32}
              height={32}
              className="w-8 h-8"
            />
            <span className="text-xl font-bold">ProxMenux</span>
          </Link>

          {/* Desktop menu */}
          <nav className="hidden md:flex items-center space-x-6 text-sm font-medium">
            {navItems.map((item) => (
              <Link
                key={item.href}
                href={item.href}
                className="flex items-center space-x-2 transition-colors hover:text-primary"
                {...(item.label === "GitHub" ? { target: "_blank", rel: "noopener noreferrer" } : {})}
              >
                {item.icon}
                <span>{item.label}</span>
              </Link>
            ))}

            {/* RSS Feed Link */}
            <Link
              href="https://macrimi.github.io/ProxMenux/rss.xml"
              className="flex items-center space-x-2 transition-colors hover:text-primary text-orange-600 hover:text-orange-700"
              target="_blank"
              rel="noopener noreferrer"
              title="RSS Feed"
            >
              <Rss className="h-4 w-4" />
              <span>RSS</span>
            </Link>
          </nav>

          {/* Mobile menu button */}
          <button className="md:hidden p-2" onClick={() => setIsMenuOpen(!isMenuOpen)}>
            <Menu className="h-6 w-6" />
          </button>
        </div>

        {/* Mobile menu */}
        {isMenuOpen && (
          <nav className="md:hidden py-4">
            {navItems.map((item) => (
              <Link
                key={item.href}
                href={item.href}
                className="flex items-center space-x-2 py-2 transition-colors hover:text-primary"
                onClick={() => setIsMenuOpen(false)}
                {...(item.label === "GitHub" ? { target: "_blank", rel: "noopener noreferrer" } : {})}
              >
                {item.icon}
                <span>{item.label}</span>
              </Link>
            ))}

            {/* RSS Feed Link - Mobile */}
            <Link
              href="https://macrimi.github.io/ProxMenux/rss.xml"
              className="flex items-center space-x-2 py-2 transition-colors hover:text-primary text-orange-600 hover:text-orange-700"
              onClick={() => setIsMenuOpen(false)}
              target="_blank"
              rel="noopener noreferrer"
              title="RSS Feed"
            >
              <Rss className="h-4 w-4" />
              <span>RSS</span>
            </Link>
          </nav>
        )}
      </div>
    </header>
  )
}
