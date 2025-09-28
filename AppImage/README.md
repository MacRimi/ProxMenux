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

## Technology Stack

- **Frontend**: Next.js 15, React 19, TypeScript
- **Styling**: Tailwind CSS with custom Proxmox-inspired theme
- **Charts**: Recharts for data visualization
- **UI Components**: Radix UI primitives with shadcn/ui
- **Backend**: Flask server for system data collection
- **Packaging**: AppImage for easy distribution

## Development

\`\`\`bash
# Install dependencies
npm install

# Start development server
npm run dev

# Build for production
npm run build
\`\`\`

## Building AppImage

\`\`\`bash
# Make build script executable
chmod +x scripts/build_appimage.sh

# Build AppImage
./scripts/build_appimage.sh
\`\`\`

## Translation Support

The project includes a translation system for multi-language support:

\`\`\`bash
# Build translation AppImage
chmod +x scripts/build_translate_appimage.sh
./scripts/build_translate_appimage.sh
\`\`\`

## License

MIT License - see LICENSE file for details.
