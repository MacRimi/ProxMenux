import { fetchApi } from "@/lib/api-config"

export interface Temperature {
  name: string
  original_name?: string
  current: number
  high?: number
  critical?: number
  adapter?: string
  type?: "cpu" | "gpu" | "nvme" | "hdd" | "ssd" | "storage" | "pci" | "other"
  device?: string
  devices?: string[]
  model?: string
  serial?: string
}

export interface PowerMeter {
  name: string
  watts: number
  adapter?: string
}

export interface NetworkInterface {
  name: string
  type: string
  speed?: string
  status?: string
}

export interface StorageDevice {
  name: string
  type: string
  size?: string
  model?: string
  driver?: string
  interface?: string
  serial?: string
  family?: string
  firmware?: string
  rotation_rate?: number | string
  form_factor?: string
  sata_version?: string
  pcie_gen?: string // e.g., "PCIe 4.0"
  pcie_width?: string // e.g., "x4"
  pcie_max_gen?: string // Maximum supported PCIe generation
  pcie_max_width?: string // Maximum supported PCIe lanes
  sas_version?: string // e.g., "SAS-3"
  sas_speed?: string // e.g., "12Gb/s"
  link_speed?: string // Generic link speed info
}

export interface PCIDevice {
  slot: string
  type: string
  device: string
  vendor: string
  class: string
  driver?: string
  kernel_module?: string
  irq?: string
  memory_address?: string
  link_speed?: string
  capabilities?: string[]
  gpu_memory?: string
  gpu_driver_version?: string
  gpu_cuda_version?: string
  gpu_compute_capability?: string
  gpu_power_draw?: string
  gpu_temperature?: number
  gpu_utilization?: number
  gpu_memory_used?: string
  gpu_memory_total?: string
  gpu_clock_speed?: string
  gpu_memory_clock?: string
}

export interface Fan {
  name: string
  original_name?: string
  speed: number
  unit: string
  adapter?: string
}

export interface PowerSupply {
  name: string
  watts: number
  status?: string
}

export interface UPS {
  name: string
  host?: string
  is_remote?: boolean
  connection_type?: string
  status: string
  model?: string
  manufacturer?: string
  serial?: string
  device_type?: string
  firmware?: string
  driver?: string
  battery_charge?: string
  battery_charge_raw?: number
  battery_voltage?: string
  battery_date?: string
  time_left?: string
  time_left_seconds?: number
  load_percent?: string
  load_percent_raw?: number
  input_voltage?: string
  input_frequency?: string
  output_voltage?: string
  output_frequency?: string
  real_power?: string
  apparent_power?: string
  [key: string]: any
}

export interface CoralTPU {
  type: "pcie" | "usb"
  name: string
  vendor: string
  vendor_id: string
  device_id: string
  slot?: string           // PCIe only, e.g. "0000:0c:00.0"
  bus_device?: string     // USB only, e.g. "002:007"
  form_factor?: string    // "M.2 / Mini PCIe (x1)" | "USB Accelerator" | ...
  interface_speed?: string // "PCIe 2.5GT/s x1" | "USB 3.0" | ...
  kernel_driver?: string | null
  usb_driver?: string | null
  kernel_modules?: {
    gasket: boolean
    apex: boolean
  }
  device_nodes?: string[]
  edgetpu_runtime?: string
  programmed?: boolean     // USB only: runtime has interacted with the device
  drivers_ready: boolean
  // Thermal data — PCIe/M.2 only (apex driver). Always null for USB Coral.
  temperature?: number | null           // °C current die temperature
  temperature_trips?: number[] | null   // trip_point0/1/2_temp, ordered warn→critical
  thermal_warnings?: Array<{
    name: string                        // e.g. "hw_temp_warn1"
    threshold_c: number | null
    enabled: boolean
  }> | null
}

export interface UsbDevice {
  bus_device: string       // "002:007"
  vendor_id: string        // "18d1"
  product_id: string       // "9302"
  vendor: string
  name: string
  class_code: string       // "ff"
  class_label: string      // "Vendor Specific", "HID", "Mass Storage", ...
  speed_mbps: number
  speed_label: string      // "USB 3.0" | "USB 2.0" | ...
  serial?: string
  driver?: string
}

export interface GPU {
  slot: string
  name: string
  vendor: string
  type: string
  pci_class?: string
  pci_driver?: string
  pci_kernel_module?: string
  driver_version?: string
  memory_total?: string
  memory_used?: string
  memory_free?: string
  temperature?: number
  power_draw?: string
  power_limit?: string
  utilization_gpu?: number
  utilization_memory?: number
  clock_graphics?: string
  clock_memory?: string
  engine_render?: number
  engine_blitter?: number
  engine_video?: number
  engine_video_enhance?: number
  pcie_gen?: string
  pcie_width?: string
  fan_speed?: number
  fan_unit?: string
  processes?: Array<{
    pid: string
    name: string
    memory: string
  }>
  has_monitoring_tool?: boolean
  note?: string
  // SR-IOV state — populated from sysfs (physfn symlink + sriov_{num,total}vfs).
  // "vf"         — this slot is a Virtual Function; sriov_physfn is its PF.
  // "pf-active"  — this slot is a Physical Function with sriov_vf_count > 0.
  // "pf-idle"    — SR-IOV capable PF but no VFs currently active.
  // "none"       — not involved in SR-IOV.
  sriov_role?: "vf" | "pf-active" | "pf-idle" | "none"
  sriov_physfn?: string
  sriov_vf_count?: number
  sriov_totalvfs?: number
  // SR-IOV detail — only populated by the /api/gpu/<slot>/realtime endpoint
  // when the modal is open (scanning guest configs is too expensive for the
  // hardware snapshot path).
  sriov_vfs?: SriovVfDetail[]        // filled when role === "pf-active"
  sriov_consumer?: SriovConsumer | null  // filled when role === "vf"
}

export interface SriovVfDetail {
  bdf: string                        // e.g. "0000:00:02.1"
  driver: string                     // current kernel driver (i915, vfio-pci, ...)
  render_node: string                // "" when the VF does not expose a DRM node
  consumer: SriovConsumer | null     // which guest is using this VF, if any
}

export interface SriovConsumer {
  type: "vm" | "lxc"
  id: string                         // VMID or CTID
  name: string                       // VM name / LXC hostname
  running: boolean
}

export interface DiskHardwareInfo {
  type?: string
  driver?: string
  interface?: string
  model?: string
  serial?: string
  family?: string
  firmware?: string
  rotation_rate?: string
  form_factor?: string
  sata_version?: string
}

export interface NetworkHardwareInfo {
  driver?: string
  kernel_modules?: string
  subsystem?: string
  max_link_speed?: string
  max_link_width?: string
  current_link_speed?: string
  current_link_width?: string
  interface_name?: string
  interface_speed?: string
  mac_address?: string
}

export interface HardwareData {
  cpu?: {
    model?: string
    cores_per_socket?: number
    sockets?: number
    total_threads?: number
    l3_cache?: string
    virtualization?: string
  }
  motherboard?: {
    manufacturer?: string
    model?: string
    bios?: {
      vendor?: string
      version?: string
      date?: string
    }
  }
  memory_modules?: Array<{
    slot: string
    size?: string
    type?: string
    speed?: string
    manufacturer?: string
  }>
  temperatures?: Temperature[]
  power_meter?: PowerMeter
  network_cards?: NetworkInterface[]
  storage_devices?: StorageDevice[]
  pci_devices?: PCIDevice[]
  gpus?: GPU[]
  fans?: Fan[]
  power_supplies?: PowerSupply[]
  ups?: UPS | UPS[]
  coral_tpus?: CoralTPU[]
  usb_devices?: UsbDevice[]
}

export const fetcher = async (url: string) => {
  // Extract just the endpoint from the URL if it's a full URL
  const endpoint = url.startsWith("http") ? new URL(url).pathname : url
  return fetchApi(endpoint)
}
