export interface Temperature {
  name: string
  original_name?: string
  current: number
  high?: number
  critical?: number
  adapter?: string
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
}

export const fetcher = (url: string) => fetch(url).then((res) => res.json())
