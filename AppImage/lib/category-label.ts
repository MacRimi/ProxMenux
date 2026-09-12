type Translate = (key: string) => string

// Category values come from the community-scripts catalog and are also
// persisted with application links. Keep those raw values intact for
// filtering and storage; translate only what is displayed in the UI.
const CATEGORY_KEY_BY_VALUE: Record<string, string> = {
  "*Arr Suite": "arrSuite",
  "AI / Coding & Dev-Tools": "aiCodingDevTools",
  "Adblock & DNS": "adblockDns",
  "Authentication & Security": "authenticationSecurity",
  "Automation & Scheduling": "automationScheduling",
  "Backup & Recovery": "backupRecovery",
  "Business & ERP": "businessErp",
  "Communication & Community": "communicationCommunity",
  "Containers & Docker": "containersDocker",
  "Dashboards & Frontends": "dashboardsFrontends",
  "Databases": "databases",
  "Documents & Notes": "documentsNotes",
  "Files & Downloads": "filesDownloads",
  "Finance & Budgeting": "financeBudgeting",
  "Gaming & Leisure": "gamingLeisure",
  "Host Management": "hostManagement",
  "IoT & Smart Home": "iotSmartHome",
  "Media & Streaming": "mediaStreaming",
  "Messaging & Queues": "messagingQueues",
  "Miscellaneous": "miscellaneous",
  "Monitoring & Analytics": "monitoringAnalytics",
  "NVR & Cameras": "nvrCameras",
  "Network & Firewall": "networkFirewall",
  "Operating Systems & Appliances": "operatingSystemsAppliances",
  "Productivity & Workflows": "productivityWorkflows",
  "Remote Access & VPN": "remoteAccessVpn",
  "Webservers & Proxies": "webserversProxies",
  "ZigBee, Z-Wave & Matter": "zigbeeZwaveMatter",
}

export function getCategoryLabel(t: Translate, value: string): string {
  const key = CATEGORY_KEY_BY_VALUE[value.trim()]
  return key ? t(`apps.categoryLabels.${key}`) : value
}
