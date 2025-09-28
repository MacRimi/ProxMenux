import { type NextRequest, NextResponse } from "next/server"

// This will be the bridge between Next.js and the Flask server
// For now, we'll return mock data that simulates what the Flask server would provide

export async function GET(request: NextRequest) {
  const { searchParams } = new URL(request.url)
  const endpoint = searchParams.get("endpoint")

  // Mock data that would come from the Flask server running on port 8008
  const mockData = {
    system: {
      cpu_usage: 67.3,
      memory_usage: 49.4,
      temperature: 52,
      uptime: "15d 7h 23m",
      load_average: [1.23, 1.45, 1.67],
    },
    storage: {
      total: 2000,
      used: 1250,
      available: 750,
      disks: [
        { name: "/dev/sda", type: "HDD", size: 1000, used: 650, health: "healthy", temp: 42 },
        { name: "/dev/sdb", type: "HDD", size: 1000, used: 480, health: "healthy", temp: 38 },
        { name: "/dev/sdc", type: "SSD", size: 500, used: 120, health: "healthy", temp: 35 },
        { name: "/dev/nvme0n1", type: "NVMe", size: 1000, used: 340, health: "warning", temp: 55 },
      ],
    },
    network: {
      interfaces: [
        { name: "vmbr0", type: "Bridge", status: "up", ip: "192.168.1.100/24", speed: "1000 Mbps" },
        { name: "enp1s0", type: "Physical", status: "up", ip: "192.168.1.101/24", speed: "1000 Mbps" },
      ],
      traffic: {
        incoming: 89,
        outgoing: 67,
      },
    },
    vms: [
      {
        id: 100,
        name: "web-server-01",
        status: "running",
        os: "Ubuntu 22.04",
        cpu: 4,
        memory: 8192,
        disk: 50,
        uptime: "15d 7h 23m",
        cpu_usage: 45,
        memory_usage: 62,
        disk_usage: 78,
      },
    ],
  }

  try {
    // In the real implementation, this would make a request to the Flask server
    // const response = await fetch(`http://localhost:8008/api/${endpoint}`)
    // const data = await response.json()

    // For now, return mock data based on the endpoint
    switch (endpoint) {
      case "system":
        return NextResponse.json(mockData.system)
      case "storage":
        return NextResponse.json(mockData.storage)
      case "network":
        return NextResponse.json(mockData.network)
      case "vms":
        return NextResponse.json(mockData.vms)
      default:
        return NextResponse.json(mockData)
    }
  } catch (error) {
    return NextResponse.json({ error: "Failed to fetch data from Flask server" }, { status: 500 })
  }
}
