# ProxMenux Monitor

A modern, responsive dashboard for monitoring Proxmox VE systems built with Next.js and React.

## Features

- **System Overview**: Real-time monitoring of CPU, memory, temperature, and active VMs/LXC containers
- **Storage Management**: Visual representation of storage distribution and disk performance metrics
- **Network Monitoring**: Network interface statistics and performance graphs
- **Virtual Machines**: Comprehensive view of VMs and LXC containers with resource usage
- **System Logs**: Real-time system log monitoring and filtering
- **Dark/Light Theme**: Toggle between themes with Proxmox-inspired design
- **Responsive Design**: Works seamlessly on desktop and mobile devices
- **Onboarding Experience**: Interactive welcome carousel for first-time users

## Technology Stack

- **Frontend**: Next.js 15, React 19, TypeScript
- **Styling**: Tailwind CSS with custom Proxmox-inspired theme
- **Charts**: Recharts for data visualization
- **UI Components**: Radix UI primitives with shadcn/ui
- **Backend**: Flask server for system data collection
- **Packaging**: AppImage for easy distribution

## Onboarding Images

To customize the onboarding experience, place your screenshot images in `public/images/onboarding/`:

- `imagen1.png` - Overview section screenshot
- `imagen2.png` - Storage section screenshot
- `imagen3.png` - Network section screenshot
- `imagen4.png` - VMs & LXCs section screenshot
- `imagen5.png` - Hardware section screenshot
- `imagen6.png` - System Logs section screenshot

**Recommended image specifications:**
- Format: PNG or JPG
- Size: 1200x800px or similar 3:2 aspect ratio
- Quality: High-quality screenshots with representative data

The onboarding carousel will automatically show on first visit and can be dismissed or marked as "Don't show again".
