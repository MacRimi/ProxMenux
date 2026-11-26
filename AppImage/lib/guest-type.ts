// A container created from an OCI image is shown, counted and filtered as
// OCI, apart from the other LXC.
export interface GuestTypeSource {
  type?: string
  update_check?: { is_oci_lxc?: boolean } | null
}

export function isOciGuest(vm: GuestTypeSource): boolean {
  return vm.type === "lxc" && Boolean(vm.update_check?.is_oci_lxc)
}
