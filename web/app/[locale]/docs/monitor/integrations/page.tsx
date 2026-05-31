import type { Metadata } from "next"
import { getTranslations, getMessages, setRequestLocale } from "next-intl/server"
import { Link } from "@/i18n/navigation"
import Image from "next/image"
import { ExternalLink } from "lucide-react"
import { DocHeader } from "@/components/ui/doc-header"
import { Callout } from "@/components/ui/callout"
import CopyableCode from "@/components/CopyableCode"

export async function generateMetadata({
  params,
}: {
  params: Promise<{ locale: string }>
}): Promise<Metadata> {
  const { locale } = await params
  const t = await getTranslations({ locale, namespace: "docs.monitor.integrations.meta" })
  return {
    title: t("title"),
    description: t("description"),
    keywords: [
      "proxmox homepage integration",
      "proxmox home assistant",
      "proxmox grafana",
      "proxmox prometheus",
      "proxmox uptime kuma",
      "proxmox dashboard",
      "proxmenux integrations",
      "proxmox custom api widget",
      "proxmox rest sensor",
    ],
    alternates: { canonical: "https://proxmenux.com/docs/monitor/integrations" },
    openGraph: {
      title: t("ogTitle"),
      description: t("ogDescription"),
      type: "article",
      url: "https://proxmenux.com/docs/monitor/integrations",
    },
    twitter: {
      card: "summary",
      title: t("twitterTitle"),
      description: t("twitterDescription"),
    },
  }
}

type Row2 = { query: string; confirms: string }
type Row3 = { panel: string; promql: string }
type WhereNextItem = { label: string; href: string; tail: string }

export default async function MonitorIntegrationsPage({
  params,
}: {
  params: Promise<{ locale: string }>
}) {
  const { locale } = await params
  setRequestLocale(locale)
  const t = await getTranslations({ locale, namespace: "docs.monitor.integrations" })

  const messages = (await getMessages({ locale })) as unknown as {
    docs: { monitor: { integrations: {
      auth: { httpsItems: string[] }
      homeAssistant: {
        altViewSteps: string[]
        twoEditorsItems: string[]
        logoBrokenSteps: string[]
      }
      grafana: { verifyRows: Row2[]; panelRows: Row3[] }
      uptimeKuma: { kumaSteps: string[] }
      whereNext: { items: WhereNextItem[] }
    } } }
  }
  const i = messages.docs.monitor.integrations
  const httpsItems = i.auth.httpsItems
  const altViewSteps = i.homeAssistant.altViewSteps
  const twoEditorsItems = i.homeAssistant.twoEditorsItems
  const logoBrokenSteps = i.homeAssistant.logoBrokenSteps
  const verifyRows = i.grafana.verifyRows
  const panelRows = i.grafana.panelRows
  const kumaSteps = i.uptimeKuma.kumaSteps
  const whereNextItems = i.whereNext.items

  const code = (chunks: React.ReactNode) => <code>{chunks}</code>
  const strong = (chunks: React.ReactNode) => <strong>{chunks}</strong>
  const em = (chunks: React.ReactNode) => <em>{chunks}</em>
  const apiLink = (chunks: React.ReactNode) => (
    <Link href="/docs/monitor/api" className="text-blue-600 hover:underline">{chunks}</Link>
  )
  const accessLink = (chunks: React.ReactNode) => (
    <Link href="/docs/monitor/access-auth" className="text-blue-600 hover:underline">{chunks}</Link>
  )
  const promAnchor = (chunks: React.ReactNode) => (
    <Link href="/docs/monitor/api#prometheus" className="text-blue-600 hover:underline">{chunks}</Link>
  )
  const notifEventsLink = (chunks: React.ReactNode) => (
    <Link href="/docs/monitor/notifications" className="text-blue-600 hover:underline">{chunks}</Link>
  )
  const pveLink = (chunks: React.ReactNode) => (
    <Link href="/docs/monitor/notifications#pve-webhook-integration" className="text-blue-600 hover:underline">{chunks}</Link>
  )
  const ext = (href: string) => (chunks: React.ReactNode) =>
    (
      <a href={href} target="_blank" rel="noopener noreferrer" className="text-blue-600 hover:underline inline-flex items-center gap-1">
        {chunks}
        <ExternalLink className="w-3 h-3" />
      </a>
    )

  return (
    <div>
      <DocHeader
        title={t("header.title")}
        description={t("header.description")}
        section={t("header.section")}
        estimatedMinutes={20}
      />

      <Callout variant="info" title={t("intro.title")}>
        {t.rich("intro.body", { link: apiLink })}
      </Callout>

      <h2 id="authentication" className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("auth.heading")}</h2>

      <p className="mb-4 text-gray-800 leading-relaxed">{t("auth.intro")}</p>

      <h3 className="text-lg font-semibold mt-6 mb-2 text-gray-900">{t("auth.optAtitle")}</h3>

      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("auth.optAbody1", { strong, em })}
      </p>

      <p className="mb-4 text-gray-800 leading-relaxed">{t("auth.optAbody2")}</p>

      <CopyableCode
        code={`curl -H "Authorization: Bearer <api-token>" http://<host>:8008/api/system | jq`}
        className="my-4"
      />

      <h3 className="text-lg font-semibold mt-6 mb-2 text-gray-900">{t("auth.optBtitle")}</h3>

      <p className="mb-4 text-gray-800 leading-relaxed">{t("auth.optBbody")}</p>

      <CopyableCode
        code={`# 1. Exchange credentials for a JWT
curl -X POST http://<host>:8008/api/auth/login \\
  -H "Content-Type: application/json" \\
  -d '{"username":"admin","password":"<your-password>","totp_token":"123456"}' | jq -r '.token'

# 2. Use the returned token exactly like an API token
curl -H "Authorization: Bearer <returned-token>" http://<host>:8008/api/system | jq`}
        className="my-4"
      />

      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("auth.outro", { link: accessLink })}
      </p>

      <Callout variant="info" title={t("auth.httpsTitle")}>
        {t.rich("auth.httpsIntro", { code, strong })}
        <ul className="list-disc pl-6 space-y-1 mb-0 mt-2">
          {httpsItems.map((_, idx) => (
            <li key={idx}>{t.rich(`auth.httpsItems.${idx}`, { strong, code })}</li>
          ))}
        </ul>
      </Callout>

      <h2 id="homepage" className="text-2xl font-semibold mt-10 mb-4 text-gray-900">
        <a href={t("homepage.headingHref")} target="_blank" rel="noopener noreferrer" className="text-blue-600 hover:underline inline-flex items-center gap-1">
          {t("homepage.heading")}<ExternalLink className="w-5 h-5" />
        </a>
      </h2>

      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("homepage.intro", { code })}
      </p>

      <Callout variant="tip" title={t("homepage.iconCalloutTitle")}>
        {t.rich("homepage.iconCalloutBody", {
          code,
          a1: ext("https://dashboardicons.com"),
          a2: ext("https://dashboardicons.com/icons/external/proxmenux"),
        })}
      </Callout>

      <figure className="my-6">
        <Image src="/monitor/integrations/homepage.png" alt={t("homepage.imageAlt")} width={2000} height={1062} className="rounded-lg border border-gray-200 shadow-sm w-full h-auto mx-auto max-w-2xl" />
        <figcaption className="text-sm text-gray-500 mt-2 text-center italic">{t.rich("homepage.imageCaption", { code })}</figcaption>
      </figure>

      <h3 className="text-lg font-semibold mt-6 mb-2 text-gray-900">{t("homepage.basicTitle")}</h3>

      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("homepage.basicIntro", { code })}
      </p>

      <CopyableCode
        code={`- ProxMenux Monitor:
    href: http://proxmox.example.tld:8008/
    icon: proxmenux.png
    widget:
      type: customapi
      url: http://proxmox.example.tld:8008/api/system
      refreshInterval: 10000
      mappings:
        - field: uptime
          label: Uptime
          icon: lucide:clock-4
          format: text
        - field: cpu_usage
          label: CPU
          icon: lucide:cpu
          format: percent
        - field: memory_usage
          label: RAM
          icon: lucide:memory-stick
          format: percent
        - field: temperature
          label: Temp
          icon: lucide:thermometer-sun
          format: number
          suffix: °C`}
        className="my-4"
      />

      <h3 className="text-lg font-semibold mt-6 mb-2 text-gray-900">{t("homepage.authedTitle")}</h3>

      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("homepage.authedIntro", { strong, code })}
      </p>

      <CopyableCode
        code={`- ProxMenux Monitor:
    href: http://proxmox.example.tld:8008/
    icon: proxmenux.png
    widget:
      type: customapi
      url: http://proxmox.example.tld:8008/api/system
      headers:
        Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.abc123def456ghi789
      refreshInterval: 10000
      mappings:
        - field: uptime
          label: Uptime
          icon: lucide:clock-4
          format: text
        - field: cpu_usage
          label: CPU
          icon: lucide:cpu
          format: percent
        - field: memory_usage
          label: RAM
          icon: lucide:memory-stick
          format: percent
        - field: temperature
          label: Temp
          icon: lucide:thermometer-sun
          format: number
          suffix: °C`}
        className="my-4"
      />

      <p className="mb-4 text-gray-800 leading-relaxed">{t("homepage.authedOutro")}</p>

      <h3 className="text-lg font-semibold mt-6 mb-2 text-gray-900">{t("homepage.multiTitle")}</h3>

      <p className="mb-4 text-gray-800 leading-relaxed">{t("homepage.multiIntro")}</p>

      <CopyableCode
        code={`- ProxMenux System:
    href: http://proxmox.example.tld:8008/
    icon: lucide:server
    description: Proxmox VE Host
    widget:
      type: customapi
      url: http://proxmox.example.tld:8008/api/system
      headers:
        Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.abc123def456ghi789
      refreshInterval: 5000
      mappings:
        - field: cpu_usage
          label: CPU
          icon: lucide:cpu
          format: percent
        - field: memory_usage
          label: RAM
          icon: lucide:memory-stick
          format: percent
        - field: temperature
          label: Temp
          icon: lucide:thermometer-sun
          format: number
          suffix: °C

- ProxMenux Storage:
    href: http://proxmox.example.tld:8008/#/storage
    icon: lucide:hard-drive
    description: Storage Overview
    widget:
      type: customapi
      url: http://proxmox.example.tld:8008/api/storage/summary
      headers:
        Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.abc123def456ghi789
      refreshInterval: 30000
      mappings:
        - field: total
          label: Total
          icon: lucide:database
          format: number
          suffix: " TB"
        - field: used
          label: Used
          icon: lucide:folder
          format: number
          suffix: " GB"
        - field: disk_count
          label: Disks
          icon: lucide:hard-drive
          format: number

- ProxMenux Network:
    href: http://proxmox.example.tld:8008/#/network
    icon: lucide:network
    description: Network Stats
    widget:
      type: customapi
      url: http://proxmox.example.tld:8008/api/network/summary
      headers:
        Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.abc123def456ghi789
      refreshInterval: 5000
      mappings:
        - field: traffic.bytes_recv
          label: Received
          icon: lucide:download
          format: bytes
        - field: traffic.bytes_sent
          label: Sent
          icon: lucide:upload
          format: bytes
        - field: physical_active_count
          label: NICs up
          icon: lucide:network
          format: number`}
        className="my-4"
      />

      <Callout variant="tip" title={t("homepage.multiCalloutTitle")}>
        {t.rich("homepage.multiCalloutBody", { code })}
      </Callout>

      <h2 id="home-assistant" className="text-2xl font-semibold mt-10 mb-4 text-gray-900">
        <a href={t("homeAssistant.headingHref")} target="_blank" rel="noopener noreferrer" className="text-blue-600 hover:underline inline-flex items-center gap-1">
          {t("homeAssistant.heading")}<ExternalLink className="w-5 h-5" />
        </a>
      </h2>

      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("homeAssistant.intro", { code, link: apiLink })}
      </p>

      <figure className="my-6">
        <Image src="/monitor/integrations/home-assistant.png" alt={t("homeAssistant.imageAlt")} width={2000} height={1200} className="rounded-lg border border-gray-200 shadow-sm w-full h-auto mx-auto max-w-2xl" />
        <figcaption className="text-sm text-gray-500 mt-2 text-center italic">{t("homeAssistant.imageCaption")}</figcaption>
      </figure>

      <h3 className="text-lg font-semibold mt-6 mb-2 text-gray-900">{t("homeAssistant.step1Title")}</h3>

      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("homeAssistant.step1Body", { code })}
      </p>

      <CopyableCode
        code={`# secrets.yaml — add this file to .gitignore
proxmenux_token_header: "Bearer <your_actual_api_token_here>"`}
        className="my-4"
      />

      <h3 className="text-lg font-semibold mt-6 mb-2 text-gray-900">{t("homeAssistant.step2Title")}</h3>

      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("homeAssistant.step2Body", { code })}
      </p>

      <CopyableCode
        code={`rest:
  # ─── Block 1: system resources (CPU, memory, temperature, uptime, host info) ───
  - resource: http://<proxmenux-host>:8008/api/system
    headers:
      Authorization: !secret proxmenux_token_header
    scan_interval: 30
    sensor:
      - name: "ProxMenux CPU"
        unique_id: proxmenux_cpu
        value_template: "{{ value_json.cpu_usage }}"
        unit_of_measurement: "%"
        state_class: measurement
        icon: mdi:cpu-64-bit
      - name: "ProxMenux RAM"
        unique_id: proxmenux_ram
        value_template: "{{ value_json.memory_usage }}"
        unit_of_measurement: "%"
        state_class: measurement
        icon: mdi:memory
      - name: "ProxMenux Memory Used"
        unique_id: proxmenux_memory_used
        value_template: "{{ value_json.memory_used }}"
        unit_of_measurement: "GB"
        state_class: measurement
        icon: mdi:memory
      - name: "ProxMenux Memory Total"
        unique_id: proxmenux_memory_total
        value_template: "{{ value_json.memory_total }}"
        unit_of_measurement: "GB"
        icon: mdi:memory
      - name: "ProxMenux CPU Temperature"
        unique_id: proxmenux_cpu_temperature
        value_template: "{{ value_json.temperature }}"
        unit_of_measurement: "°C"
        device_class: temperature
        state_class: measurement
      - name: "ProxMenux Uptime"
        unique_id: proxmenux_uptime
        value_template: "{{ value_json.uptime }}"
        icon: mdi:clock-outline
      - name: "ProxMenux Load 1m"
        unique_id: proxmenux_load_1m
        value_template: "{{ value_json.load_average[0] | round(2) }}"
        state_class: measurement
        icon: mdi:gauge
      - name: "ProxMenux Available Updates"
        unique_id: proxmenux_available_updates
        value_template: "{{ value_json.available_updates }}"
        state_class: measurement
        icon: mdi:package-up
      - name: "ProxMenux Host"
        unique_id: proxmenux_host
        value_template: "{{ value_json.hostname }}"
        json_attributes:
          - kernel_version
          - proxmox_version
          - cpu_cores
          - cpu_threads

  # ─── Block 2: Health Monitor (overall + per-category + active errors) ───
  - resource: http://<proxmenux-host>:8008/api/health/full
    headers:
      Authorization: !secret proxmenux_token_header
    scan_interval: 60
    sensor:
      - name: "ProxMenux Health"
        unique_id: proxmenux_health_overall
        value_template: "{{ value_json.health.overall }}"
        json_attributes_path: "$.health"
        json_attributes:
          - summary
          - details
        icon: mdi:heart-pulse
      - name: "ProxMenux Active Errors"
        unique_id: proxmenux_active_errors
        value_template: "{{ value_json.active_errors | length }}"
        state_class: measurement
        icon: mdi:alert-circle
        json_attributes:
          - active_errors
      - name: "ProxMenux Dismissed Errors"
        unique_id: proxmenux_dismissed_errors
        value_template: "{{ value_json.dismissed | length }}"
        state_class: measurement
        icon: mdi:alert-circle-outline

  # ─── Block 3: VMs and containers ───
  - resource: http://<proxmenux-host>:8008/api/vms
    headers:
      Authorization: !secret proxmenux_token_header
    scan_interval: 60
    sensor:
      - name: "ProxMenux VMs Total"
        unique_id: proxmenux_vms_total
        value_template: "{{ value_json | length }}"
        state_class: measurement
        icon: mdi:server
        json_attributes:
          - vms
      - name: "ProxMenux VMs Running"
        unique_id: proxmenux_vms_running
        value_template: >
          {{ value_json | selectattr('status', 'eq', 'running') | list | length }}
        state_class: measurement
        icon: mdi:play-circle
      - name: "ProxMenux VMs Stopped"
        unique_id: proxmenux_vms_stopped
        value_template: >
          {{ value_json | selectattr('status', 'eq', 'stopped') | list | length }}
        state_class: measurement
        icon: mdi:stop-circle

  # ─── Block 4: Storage summary ───
  - resource: http://<proxmenux-host>:8008/api/storage/summary
    headers:
      Authorization: !secret proxmenux_token_header
    scan_interval: 300
    sensor:
      - name: "ProxMenux Storage Total"
        unique_id: proxmenux_storage_total
        value_template: "{{ value_json.total }}"
        unit_of_measurement: "TB"
        icon: mdi:harddisk
      - name: "ProxMenux Storage Used"
        unique_id: proxmenux_storage_used
        value_template: "{{ value_json.used }}"
        unit_of_measurement: "GB"
        state_class: measurement
        icon: mdi:harddisk
      - name: "ProxMenux Storage Available"
        unique_id: proxmenux_storage_available
        value_template: "{{ value_json.available }}"
        unit_of_measurement: "GB"
        state_class: measurement
      - name: "ProxMenux Disk Count"
        unique_id: proxmenux_disk_count
        value_template: "{{ value_json.disk_count }}"

  # ─── Block 5: Network summary ───
  - resource: http://<proxmenux-host>:8008/api/network/summary
    headers:
      Authorization: !secret proxmenux_token_header
    scan_interval: 30
    sensor:
      - name: "ProxMenux Net Rx Bytes"
        unique_id: proxmenux_net_rx_bytes
        value_template: "{{ value_json.traffic.bytes_recv }}"
        unit_of_measurement: "B"
        device_class: data_size
        state_class: total_increasing
      - name: "ProxMenux Net Tx Bytes"
        unique_id: proxmenux_net_tx_bytes
        value_template: "{{ value_json.traffic.bytes_sent }}"
        unit_of_measurement: "B"
        device_class: data_size
        state_class: total_increasing
      - name: "ProxMenux Physical NICs Up"
        unique_id: proxmenux_physical_nics_up
        value_template: >
          {{ value_json.physical_active_count }} / {{ value_json.physical_total_count }}
        icon: mdi:ethernet
      - name: "ProxMenux Bridges Up"
        unique_id: proxmenux_bridges_up
        value_template: >
          {{ value_json.bridge_active_count }} / {{ value_json.bridge_total_count }}
        icon: mdi:bridge

  # ─── Block 6: ProxMenux update availability ───
  - resource: http://<proxmenux-host>:8008/api/proxmenux/update-status
    headers:
      Authorization: !secret proxmenux_token_header
    scan_interval: 3600
    sensor:
      - name: "ProxMenux Monitor Update"
        unique_id: proxmenux_monitor_update
        value_template: >
          {{ 'update available' if (value_json.stable or value_json.beta) else 'up to date' }}
        json_attributes:
          - stable
          - stable_version
          - beta
          - beta_version
        icon: mdi:update`}
        className="my-4"
      />

      <h3 className="text-lg font-semibold mt-6 mb-2 text-gray-900">{t("homeAssistant.step3Title")}</h3>

      <p className="mb-4 text-gray-800 leading-relaxed">{t("homeAssistant.step3Body")}</p>

      <CopyableCode
        code={`# configuration.yaml — add alongside the rest: block above
# All four template entities live under one template: section (HA modern syntax).
# If you already have a template: section elsewhere, merge the lists into it
# rather than declaring template: a second time.

template:
  - binary_sensor:
      - name: "ProxMenux Healthy"
        default_entity_id: binary_sensor.proxmenux_is_healthy
        device_class: problem
        delay_off: 30
        state: "{{ states('sensor.proxmenux_health') == 'OK' }}"
      - name: "ProxMenux Critical"
        default_entity_id: binary_sensor.proxmenux_has_critical
        device_class: safety
        state: "{{ states('sensor.proxmenux_health') == 'CRITICAL' }}"
  - sensor:
      - name: "ProxMenux Memory Free"
        unique_id: proxmenux_memory_free
        unit_of_measurement: "GB"
        state_class: measurement
        state: >
          {{ (states('sensor.proxmenux_memory_total') | float
              - states('sensor.proxmenux_memory_used') | float) | round(1) }}
      - name: "ProxMenux Storage Usage Percent"
        unique_id: proxmenux_storage_usage_percent
        unit_of_measurement: "%"
        state_class: measurement
        state: >
          {% set used = states('sensor.proxmenux_storage_used') | float %}
          {% set free = states('sensor.proxmenux_storage_available') | float %}
          {% set total = used + free %}
          {{ (used / total * 100) | round(1) if total > 0 else 0 }}`}
        className="my-4"
      />

      <h3 className="text-lg font-semibold mt-6 mb-2 text-gray-900">{t("homeAssistant.step4Title")}</h3>

      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("homeAssistant.step4Body", { em })}
      </p>

      <Callout variant="warning" title={t("homeAssistant.replaceTitle")}>
        {t.rich("homeAssistant.replaceBody", { em, code })}
      </Callout>

      <h3 className="text-lg font-semibold mt-6 mb-2 text-gray-900">{t("homeAssistant.step5Title")}</h3>

      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("homeAssistant.step5Body", { strong, em })}
      </p>

      <CopyableCode
        code={`type: vertical-stack
cards:
  # Header — ProxMenux logo + live health status overlay
  - type: picture-entity
    entity: sensor.proxmenux_health
    name: ProxMenux Monitor
    image: https://cdn.jsdelivr.net/gh/homarr-labs/dashboard-icons/svg/proxmenux.svg
    show_state: true

  # Quick KPIs
  - type: glance
    title: ProxMenux — at a glance
    columns: 4
    entities:
      - entity: sensor.proxmenux_health
        name: Health
      - entity: sensor.proxmenux_cpu
        name: CPU
      - entity: sensor.proxmenux_ram
        name: RAM
      - entity: sensor.proxmenux_cpu_temperature
        name: Temp

  # System detail
  - type: entities
    title: System
    entities:
      - entity: sensor.proxmenux_host
        name: Hostname
      - entity: sensor.proxmenux_uptime
        name: Uptime
      - entity: sensor.proxmenux_load_1m
        name: Load avg (1m)
      - entity: sensor.proxmenux_memory_used
        name: RAM used
      - entity: sensor.proxmenux_memory_total
        name: RAM total
      - entity: sensor.proxmenux_memory_free
        name: RAM free
      - entity: sensor.proxmenux_available_updates
        name: APT updates pending

  # VMs / CTs
  - type: glance
    title: "VMs & Containers"
    columns: 3
    entities:
      - entity: sensor.proxmenux_vms_total
        name: Total
      - entity: sensor.proxmenux_vms_running
        name: Running
      - entity: sensor.proxmenux_vms_stopped
        name: Stopped

  # Storage
  - type: entities
    title: Storage
    entities:
      - entity: sensor.proxmenux_storage_total
        name: Total disks (TB)
      - entity: sensor.proxmenux_storage_used
        name: Used (GB)
      - entity: sensor.proxmenux_storage_available
        name: Available (GB)
      - entity: sensor.proxmenux_storage_usage_percent
        name: Usage
      - entity: sensor.proxmenux_disk_count
        name: Disk count

  # Network
  - type: entities
    title: Network
    entities:
      - entity: sensor.proxmenux_physical_nics_up
        name: Physical interfaces
      - entity: sensor.proxmenux_bridges_up
        name: Bridges
      - entity: sensor.proxmenux_net_rx_bytes
        name: Received
      - entity: sensor.proxmenux_net_tx_bytes
        name: Sent

  # Health detail — only render when there are active errors
  - type: conditional
    conditions:
      - entity: sensor.proxmenux_active_errors
        state_not: "0"
    card:
      type: entities
      title: Active health issues
      entities:
        - entity: sensor.proxmenux_active_errors
          name: Active error count
        - entity: sensor.proxmenux_dismissed_errors
          name: Dismissed (in suppression window)
        - entity: binary_sensor.proxmenux_has_critical
          name: Critical present?`}
        className="my-4"
      />

      <Callout variant="tip" title={t("homeAssistant.viewTipTitle")}>
        {t.rich("homeAssistant.viewTipBody", { em, code })}
        <pre className="mt-2 rounded-md bg-white border border-slate-200 p-3 overflow-x-auto text-xs font-mono text-gray-800">{`- title: ProxMenux Monitor
  icon: mdi:server
  cards:
    # ... paste the cards from the vertical-stack above, without the
    # outer "type: vertical-stack" wrapper, indented one extra level
`}</pre>
        {t("homeAssistant.viewTipOutro")}
      </Callout>

      <h4 className="text-base font-semibold mt-8 mb-2 text-gray-900">{t("homeAssistant.altViewTitle")}</h4>

      <p className="mb-4 text-gray-800 leading-relaxed">{t("homeAssistant.altViewIntro")}</p>

      <ol className="list-decimal pl-6 mb-4 text-gray-800 leading-relaxed space-y-1">
        {altViewSteps.map((_, idx) => (
          <li key={idx}>{t.rich(`homeAssistant.altViewSteps.${idx}`, { em })}</li>
        ))}
      </ol>

      <Callout variant="warning" title={t("homeAssistant.twoEditorsTitle")}>
        {t("homeAssistant.twoEditorsIntro")}
        <ul className="list-disc pl-6 mb-0 mt-2 space-y-1">
          {twoEditorsItems.map((_, idx) => (
            <li key={idx}>{t.rich(`homeAssistant.twoEditorsItems.${idx}`, { strong, em, code })}</li>
          ))}
        </ul>
        {t.rich("homeAssistant.twoEditorsOutro", { em, code })}
      </Callout>

      <CopyableCode
        code={`title: ProxMenux Monitor
path: proxmenux
icon: mdi:server
cards:
  # Header — full width
  - type: picture-entity
    entity: sensor.proxmenux_health
    name: ProxMenux Monitor
    image: https://cdn.jsdelivr.net/gh/homarr-labs/dashboard-icons/svg/proxmenux.svg
    show_state: true

  # Quick KPIs — full width
  - type: glance
    title: ProxMenux — at a glance
    columns: 4
    entities:
      - entity: sensor.proxmenux_health
        name: Health
      - entity: sensor.proxmenux_cpu
        name: CPU
      - entity: sensor.proxmenux_ram
        name: RAM
      - entity: sensor.proxmenux_cpu_temperature
        name: Temp

  # System detail
  - type: entities
    title: System
    entities:
      - entity: sensor.proxmenux_host
        name: Hostname
      - entity: sensor.proxmenux_uptime
        name: Uptime
      - entity: sensor.proxmenux_load_1m
        name: Load avg (1m)
      - entity: sensor.proxmenux_memory_used
        name: RAM used
      - entity: sensor.proxmenux_memory_total
        name: RAM total
      - entity: sensor.proxmenux_memory_free
        name: RAM free
      - entity: sensor.proxmenux_available_updates
        name: APT updates pending

  # VMs / CTs
  - type: glance
    title: "VMs & Containers"
    columns: 3
    entities:
      - entity: sensor.proxmenux_vms_total
        name: Total
      - entity: sensor.proxmenux_vms_running
        name: Running
      - entity: sensor.proxmenux_vms_stopped
        name: Stopped

  # Storage
  - type: entities
    title: Storage
    entities:
      - entity: sensor.proxmenux_storage_total
        name: Total disks (TB)
      - entity: sensor.proxmenux_storage_used
        name: Used (GB)
      - entity: sensor.proxmenux_storage_available
        name: Available (GB)
      - entity: sensor.proxmenux_storage_usage_percent
        name: Usage
      - entity: sensor.proxmenux_disk_count
        name: Disk count

  # Network
  - type: entities
    title: Network
    entities:
      - entity: sensor.proxmenux_physical_nics_up
        name: Physical interfaces
      - entity: sensor.proxmenux_bridges_up
        name: Bridges
      - entity: sensor.proxmenux_net_rx_bytes
        name: Received
      - entity: sensor.proxmenux_net_tx_bytes
        name: Sent

  # Health detail — only render when there are active errors
  - type: conditional
    conditions:
      - entity: sensor.proxmenux_active_errors
        state_not: "0"
    card:
      type: entities
      title: Active health issues
      entities:
        - entity: sensor.proxmenux_active_errors
          name: Active error count
        - entity: sensor.proxmenux_dismissed_errors
          name: Dismissed (in suppression window)
        - entity: binary_sensor.proxmenux_has_critical
          name: Critical present?`}
        className="my-4"
      />

      <figure className="my-6">
        <Image src="/monitor/integrations/home-assistant-view.png" alt={t("homeAssistant.viewImageAlt")} width={2210} height={1606} className="rounded-lg border border-gray-200 shadow-sm w-full h-auto mx-auto max-w-3xl" />
        <figcaption className="text-sm text-gray-500 mt-2 text-center italic">{t.rich("homeAssistant.viewImageCaption", { em })}</figcaption>
      </figure>

      <Callout variant="tip" title={t("homeAssistant.twoColTipTitle")}>
        {t.rich("homeAssistant.twoColTipBody", { em, code })}
        <pre className="mt-2 rounded-md bg-white border border-slate-200 p-3 overflow-x-auto text-xs font-mono text-gray-800">{`  - type: horizontal-stack
    cards:
      - type: entities
        title: System
        entities: [...]
      - type: glance
        title: "VMs & Containers"
        entities: [...]`}</pre>
        {t("homeAssistant.twoColTipOutro")}
      </Callout>

      <h3 className="text-lg font-semibold mt-6 mb-2 text-gray-900">{t("homeAssistant.step6Title")}</h3>

      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("homeAssistant.step6Body", { code })}
      </p>

      <CopyableCode
        code={`# automations.yaml
- alias: "ProxMenux — health degraded to WARNING"
  trigger:
    - platform: state
      entity_id: sensor.proxmenux_health
      to: "WARNING"
  action:
    - service: notify.mobile_app_<your_phone>
      data:
        title: "Proxmox: warning"
        message: >
          {{ state_attr('sensor.proxmenux_health', 'summary') }}

- alias: "ProxMenux — health CRITICAL"
  trigger:
    - platform: state
      entity_id: sensor.proxmenux_health
      to: "CRITICAL"
  action:
    - service: notify.mobile_app_<your_phone>
      data:
        title: "🚨 Proxmox CRITICAL"
        message: >
          {{ state_attr('sensor.proxmenux_health', 'summary') }}
    - service: persistent_notification.create
      data:
        title: "Proxmox CRITICAL"
        message: >
          {{ state_attr('sensor.proxmenux_health', 'summary') }}
        notification_id: proxmenux_critical

- alias: "ProxMenux — VM unexpectedly stopped"
  trigger:
    - platform: numeric_state
      entity_id: sensor.proxmenux_vms_stopped
      above: 0
      for: "00:02:00"
  action:
    - service: notify.mobile_app_<your_phone>
      data:
        title: "Proxmox: VM stopped"
        message: >
          {{ states('sensor.proxmenux_vms_stopped') }} VM(s) currently stopped`}
        className="my-4"
      />

      <h3 className="text-lg font-semibold mt-6 mb-2 text-gray-900">{t("homeAssistant.logoTitle")}</h3>

      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("homeAssistant.logoBody", {
          a1: ext("https://dashboardicons.com"),
          a2: ext("https://dashboardicons.com/icons/external/proxmenux"),
        })}
      </p>

      <Callout variant="tip" title={t("homeAssistant.logoBrokenTitle")}>
        {t("homeAssistant.logoBrokenIntro")}
        <ol className="list-decimal pl-6 mb-0 mt-2 space-y-1">
          {logoBrokenSteps.map((_, idx) => (
            <li key={idx}>
              {t.rich(`homeAssistant.logoBrokenSteps.${idx}`, {
                code,
                a: ext("https://cdn.jsdelivr.net/gh/homarr-labs/dashboard-icons/svg/proxmenux.svg"),
              })}
            </li>
          ))}
        </ol>
      </Callout>

      <Callout variant="tip" title={t("homeAssistant.scanTipTitle")}>
        {t.rich("homeAssistant.scanTipBody", { code })}
      </Callout>

      <h2 id="prometheus-grafana" className="text-2xl font-semibold mt-10 mb-4 text-gray-900">
        <a href={t("grafana.promHref")} target="_blank" rel="noopener noreferrer" className="text-blue-600 hover:underline inline-flex items-center gap-1">
          Prometheus<ExternalLink className="w-5 h-5" />
        </a>{" "}+{" "}
        <a href={t("grafana.grafanaHref")} target="_blank" rel="noopener noreferrer" className="text-blue-600 hover:underline inline-flex items-center gap-1">
          Grafana<ExternalLink className="w-5 h-5" />
        </a>
      </h2>

      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("grafana.intro", { code })}
      </p>

      <figure className="my-6">
        <Image src="/monitor/integrations/grafana.png" alt={t("grafana.imageAlt")} width={2000} height={1327} className="rounded-lg border border-gray-200 shadow-sm w-full h-auto mx-auto max-w-2xl" />
        <figcaption className="text-sm text-gray-500 mt-2 text-center italic">{t.rich("grafana.imageCaption", { link: promAnchor })}</figcaption>
      </figure>

      <h3 className="text-lg font-semibold mt-6 mb-2 text-gray-900">{t("grafana.step1Title")}</h3>

      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("grafana.step1Body", { code })}
      </p>

      <CopyableCode
        code={`# /etc/prometheus/prometheus.yml
scrape_configs:
  - job_name: 'proxmenux'
    metrics_path: /api/prometheus
    scheme: https              # http if TLS isn't enabled in the Monitor
    scrape_interval: 30s
    authorization:
      type: Bearer
      credentials: 'your_actual_api_token_here'
    static_configs:
      - targets:
          - 'pve01.lan:8008'
          - 'pve02.lan:8008'
          - 'pve03.lan:8008'`}
        className="my-4"
      />

      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("grafana.step1After", { code, em })}
      </p>

      <Callout variant="tip" title={t("grafana.tokenTipTitle")}>
        {t.rich("grafana.tokenTipBody", { code })}
      </Callout>

      <h3 className="text-lg font-semibold mt-6 mb-2 text-gray-900">{t("grafana.step2Title")}</h3>

      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("grafana.step2Body", { code, em })}
      </p>

      <div className="overflow-x-auto mb-6">
        <table className="w-full text-sm border border-gray-200 rounded-md">
          <thead className="bg-gray-50 text-gray-900">
            <tr>
              <th className="text-left px-3 py-2 border-b border-gray-200">{t("grafana.headerQuery")}</th>
              <th className="text-left px-3 py-2 border-b border-gray-200">{t("grafana.headerConfirms")}</th>
            </tr>
          </thead>
          <tbody className="text-gray-800">
            {verifyRows.map((row, idx) => (
              <tr key={row.query} className={idx < verifyRows.length - 1 ? "border-b border-gray-100" : ""}>
                <td className="px-3 py-2 align-top font-mono text-xs">{row.query}</td>
                <td className="px-3 py-2 align-top">{t.rich(`grafana.verifyRows.${idx}.confirms`, { code })}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <Callout variant="info" title={t("grafana.calloutTitle")}>
        {t.rich("grafana.calloutBody", { em, code })}
      </Callout>

      <h3 className="text-lg font-semibold mt-6 mb-2 text-gray-900">{t("grafana.step3Title")}</h3>

      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("grafana.step3Body", { em, code })}
      </p>

      <h3 className="text-lg font-semibold mt-6 mb-2 text-gray-900">{t("grafana.step4Title")}</h3>

      <p className="mb-4 text-gray-800 leading-relaxed">{t("grafana.step4Body")}</p>

      <div className="overflow-x-auto mb-6">
        <table className="w-full text-sm border border-gray-200 rounded-md">
          <thead className="bg-gray-50 text-gray-900">
            <tr>
              <th className="text-left px-3 py-2 border-b border-gray-200">{t("grafana.headerPanel")}</th>
              <th className="text-left px-3 py-2 border-b border-gray-200">{t("grafana.headerPromql")}</th>
            </tr>
          </thead>
          <tbody className="text-gray-800">
            {panelRows.map((row, idx) => (
              <tr key={row.panel} className={idx < panelRows.length - 1 ? "border-b border-gray-100" : ""}>
                <td className="px-3 py-2 align-top">{row.panel}</td>
                <td className="px-3 py-2 align-top font-mono text-xs">{row.promql}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("grafana.outro", { em, code })}
      </p>

      <h2 id="uptime-kuma" className="text-2xl font-semibold mt-10 mb-4 text-gray-900">
        <a href={t("uptimeKuma.href")} target="_blank" rel="noopener noreferrer" className="text-blue-600 hover:underline inline-flex items-center gap-1">
          Uptime Kuma<ExternalLink className="w-5 h-5" />
        </a>{" "}and other status checkers
      </h2>

      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("uptimeKuma.intro", { code })}
      </p>

      <h3 className="text-lg font-semibold mt-6 mb-2 text-gray-900">{t("uptimeKuma.kumaTitle")}</h3>

      <ol className="list-decimal pl-6 mb-4 text-gray-800 leading-relaxed space-y-1">
        {kumaSteps.map((_, idx) => (
          <li key={idx}>{t.rich(`uptimeKuma.kumaSteps.${idx}`, { em, code })}</li>
        ))}
      </ol>

      <CopyableCode
        code={`# Verify the response shape — no token required
curl http://pve01.lan:8008/api/system-info | jq
# → { "hostname": "...", "uptime": "...", "health": { "status": "healthy", ... }, ... }

# A failing scriptable check (non-zero when the Monitor isn't reporting healthy)
curl -s http://pve01.lan:8008/api/system-info | jq -e '.health.status == "healthy"'`}
        className="my-4"
      />

      <h3 className="text-lg font-semibold mt-6 mb-2 text-gray-900">{t("uptimeKuma.healthchecksTitle")}</h3>

      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("uptimeKuma.healthchecksBody", { code })}
      </p>

      <Callout variant="info" title={t("uptimeKuma.richTitle")}>
        {t.rich("uptimeKuma.richBody", { code })}
      </Callout>

      <h2 id="custom-workflows" className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("workflows.heading")}</h2>

      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("workflows.intro", { em, code })}
      </p>

      <CopyableCode
        code={`# A nightly cron job reports it ran longer than its threshold
curl -X POST http://proxmox.example.tld:8008/api/notifications/send \\
  -H "Authorization: Bearer your_actual_api_token_here" \\
  -H "Content-Type: application/json" \\
  -d '{
    "event_type":"system_problem",
    "severity":"WARNING",
    "title":"Nightly rsync took 4h27m",
    "body":"The nightly-rsync job exceeded the 2h alert threshold. Check the source storage.",
    "data":{
      "service_name":"nightly-rsync",
      "hostname":"backup-host"
    }
  }'`}
        className="my-4"
      />

      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("workflows.n8nBody", { em, code })}
      </p>

      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("workflows.severityBody", { code, link: notifEventsLink })}
      </p>

      <h2 id="pve-webhook" className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("pveWebhook.heading")}</h2>

      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("pveWebhook.intro1", { em })}
      </p>

      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("pveWebhook.intro2", { code, link: pveLink })}
      </p>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("whereNext.heading")}</h2>
      <ul className="list-disc pl-6 text-gray-800 leading-relaxed space-y-1">
        {whereNextItems.map((item) => (
          <li key={item.href}>
            <Link href={item.href} className="text-blue-600 hover:underline">
              {item.label}
            </Link>
            {item.tail}
          </li>
        ))}
      </ul>
    </div>
  )
}
