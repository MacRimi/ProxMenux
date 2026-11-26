import { isOciGuest } from "./guest-type"

export interface VMSearchable {
  vmid: number
  name: string
  type: string
  tags?: string
  description?: string
  ip?: string
  ips?: string[]
  app_watches?: Array<{ name?: string | null }>
  update_check?: { is_oci_lxc?: boolean } | null
}

export interface VMTypeSynonyms {
  lxc: string
  qemu: string
}

export function normalizeVmSearchValue(value: unknown): string {
  return String(value ?? "")
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLocaleLowerCase()
}

export function matchesVmSearch(
  vm: VMSearchable,
  terms: string[],
  typeSynonyms: VMTypeSynonyms,
): boolean {
  if (terms.length === 0) return true
  const searchable = normalizeVmSearchValue([
    vm.name,
    vm.vmid,
    vm.type,
    vm.type === "lxc" ? typeSynonyms.lxc : typeSynonyms.qemu,
    isOciGuest(vm) ? "oci" : "",
    vm.tags,
    vm.description,
    vm.ip,
    ...(vm.ips || []),
    ...(vm.app_watches || []).map((app) => app.name || ""),
  ].join(" "))
  return terms.every((term) => searchable.includes(term))
}
