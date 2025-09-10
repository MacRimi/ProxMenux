import Link from "next/link"
import { BookOpen, ExternalLink, Shield, Activity, Database, FileCode, ArrowLeft } from "lucide-react"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import Footer2 from "@/components/footer2"

export default function LinuxResourcesPage() {
  const resourceCategories = [
    {
      title: "Linux General",
      icon: <BookOpen className="h-6 w-6 text-blue-500" />,
      resources: [
        {
          title: "TLDR Pages",
          url: "https://tldr.sh/",
          description:
            "Terminal commands explained briefly with practical examples. Ideal for quickly remembering how to use tar, find, rsync, etc.",
        },
        {
          title: "Explainshell",
          url: "https://explainshell.com/",
          description:
            "Enter a command and this site breaks it down explaining each part. Very useful for learning complex commands.",
        },
        {
          title: "Cheat.sh",
          url: "https://cheat.sh/",
          description:
            "Online service to quickly search commands from browser or terminal (curl cheat.sh/tar). Very powerful and practical.",
        },
      ],
    },
    {
      title: "Security and Administration",
      icon: <Shield className="h-6 w-6 text-blue-500" />,
      resources: [
        {
          title: "SSH Hardening Guide",
          url: "https://www.ssh.com/academy/ssh/security",
          description:
            "Advanced guide to secure SSH access. Covers ciphers, versions, authentication, and other recommended practices.",
        },
        {
          title: "Fail2ban Wiki (GitHub)",
          url: "https://github.com/fail2ban/fail2ban/wiki",
          description: "Official documentation and usage examples for Fail2ban, an essential tool for servers.",
        },
      ],
    },
    {
      title: "Monitoring and Diagnostics",
      icon: <Activity className="h-6 w-6 text-blue-500" />,
      resources: [
        {
          title: "nmon Performance Monitor",
          url: "http://nmon.sourceforge.net/pmwiki.php",
          description: "Advanced system monitoring tool, with documentation on its usage.",
        },
        {
          title: "htop Official",
          url: "https://htop.dev/",
          description: "Official page of htop, one of the most used tools for viewing processes and resource usage.",
        },
      ],
    },
    {
      title: "ZFS and Storage",
      icon: <Database className="h-6 w-6 text-blue-500" />,
      resources: [
        {
          title: "OpenZFS Documentation",
          url: "https://openzfs.github.io/openzfs-docs/",
          description:
            "Official and modern guide on ZFS, ideal for administrators using Proxmox with this file system.",
        },
        {
          title: "ZFS Cheatsheet (DigitalOcean)",
          url: "https://www.digitalocean.com/community/tutorials/how-to-use-zfs-on-ubuntu-20-04",
          description: "Clear and simple explanation of basic ZFS usage in Linux.",
        },
      ],
    },
    {
      title: "Extra: General Cheatsheets",
      icon: <FileCode className="h-6 w-6 text-blue-500" />,
      resources: [
        {
          title: "OverAPI.com",
          url: "https://overapi.com/linux",
          description: "Collection of interactive cheatsheets on multiple technologies, including Linux commands.",
        },
        {
          title: "DevHints.io Linux",
          url: "https://devhints.io/bash",
          description:
            "Bash shortcuts and basic scripting, useful for automating tasks in Proxmox and other environments.",
        },
      ],
    },
  ]

  return (
    <div className="min-h-screen bg-white text-gray-900">
      <div className="container mx-auto px-4 py-16" style={{ maxWidth: "980px" }}>
        <div className="mb-8">
          <Link href="/guides" className="flex items-center text-blue-500 hover:text-blue-700 transition-colors mb-6">
            <ArrowLeft className="mr-2 h-4 w-4" />
            Back to Guides
          </Link>

          <h1 className="text-4xl font-bold mb-4 text-black">Linux Resources</h1>

          <p className="text-lg mb-8 text-gray-700">
            A collection of useful resources for learning Linux commands, security practices, monitoring tools, and
            more. These resources complement the commands available in ProxMenux and will help you deepen your knowledge
            of Linux system administration.
          </p>
        </div>

        <div className="space-y-10 mb-16">
          {resourceCategories.map((category, index) => (
            <div key={index} className="mb-8">
              <div className="flex items-center gap-3 mb-4">
                {category.icon}
                <h2 className="text-2xl font-bold text-black">{category.title}</h2>
              </div>

              <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                {category.resources.map((resource, resourceIndex) => (
                  <ResourceCard key={resourceIndex} resource={resource} />
                ))}
              </div>
            </div>
          ))}
        </div>
      </div>
      <Footer2 />
    </div>
  )
}

interface ResourceProps {
  resource: {
    title: string
    url: string
    description: string
  }
}

function ResourceCard({ resource }: ResourceProps) {
  return (
    <Card className="transition-all duration-300 hover:shadow-md hover:border-blue-300 bg-white text-black border-2 border-gray-200">
      <CardHeader className="pb-2">
        <CardTitle className="text-xl text-black flex items-center justify-between">
          {resource.title}
          <a
            href={resource.url}
            target="_blank"
            rel="noopener noreferrer"
            className="text-blue-500 hover:text-blue-700"
            aria-label={`Visit ${resource.title} (opens in a new window)`}
          >
            <ExternalLink className="h-5 w-5" />
          </a>
        </CardTitle>
      </CardHeader>
      <CardContent>
        <CardDescription className="text-base text-gray-600">{resource.description}</CardDescription>
        <div className="mt-4">
          <a
            href={resource.url}
            target="_blank"
            rel="noopener noreferrer"
            className="text-sm text-blue-500 hover:text-blue-700 flex items-center"
          >
            Visit resource <ExternalLink className="ml-1 h-3 w-3" />
          </a>
        </div>
      </CardContent>
    </Card>
  )
}
