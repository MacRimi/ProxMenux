export interface Temperature {
  name: string
  original_name?: string
  current: number
  high?: number
  critical?: number
  adapter?: string
  chip?: string
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

export interface GPUProcess {
  pid: string
  name: string
  memory: string
}

export interface GPU {
  slot: string
  name: string
  vendor: string
  type: string
  index?: number
  memory_total?: string
  memory_used?: string
  memory_free?: string
  temperature?: number
  power_draw?: string
  power_limit?: string
  utilization?: number
  memory_utilization?: number
  clock_graphics?: string
  clock_memory?: string
  driver_version?: string
  pcie_gen?: string
  pcie_width?: string
  processes?: GPUProcess[]
  intel_gpu_top_available?: boolean
  radeontop_available?: boolean
}

export interface Fan {
  name: string
  type: string
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
  status: string
  battery_charge?: number
  battery_runtime?: number
  load?: number
  input_voltage?: number
  output_voltage?: number
}

export interface DiskPartition {
  name: string
  size?: string
  fstype?: string
  mountpoint?: string
}

export interface DiskDetails {
  name: string
  type?: string
  driver?: string
  model?: string
  serial?: string
  size?: string
  block_size?: string
  scheduler?: string
  rotational?: boolean
  removable?: boolean
  read_only?: boolean
  smart_available?: boolean
  smart_enabled?: boolean
  smart_health?: string
  temperature?: number
  power_on_hours?: number
  partitions?: DiskPartition[]
}

export interface NetworkInterfaceDetails {
  name: string
  driver?: string
  driver_version?: string
  firmware_version?: string
  bus_info?: string
  link_detected?: string
  speed?: string
  duplex?: string
  mtu?: string
  mac_address?: string
  ip_addresses?: Array<{
    type: string
    address: string
  }>
  statistics?: {
    rx_bytes?: string
    rx_packets?: string
    tx_bytes?: string
    tx_packets?: string
  }
}

export interface HardwareData {
  temperatures?: Temperature[]
  power_meter?: PowerMeter
  network_cards?: NetworkInterface[]
  storage_devices?: StorageDevice[]
  pci_devices?: PCIDevice[]
  gpus?: GPU[]
  fans?: Fan[]
  power_supplies?: PowerSupply[]
  ups?: UPS
  cpu?: any
  motherboard?: any
  memory_modules?: any[]
}

export const fetcher = (url: string) => fetch(url).then((res) => res.json())
