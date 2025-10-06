export interface Temperature {
  name: string
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
  speed: number
  unit: string
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

export interface HardwareData {
  temperatures?: Temperature[]
  power_meter?: PowerMeter
  network_cards?: NetworkInterface[]
  storage_devices?: StorageDevice[]
  pci_devices?: PCIDevice[]
  fans?: Fan[]
  power_supplies?: PowerSupply[]
  ups?: UPS
}

export const fetcher = (url: string) => fetch(url).then((res) => res.json())
