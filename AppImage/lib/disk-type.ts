// Shared classifier for physical-disk type. Lives here because the
// Storage page and the Hardware page used to ship their own copies
// and silently drifted — old SSDs (e.g. OCZ-SOLID2) that don't expose
// a SMART rotation rate fell through Hardware's HDD-as-default branch
// and got mislabelled, while the Storage page got it right.
//
// Backend convention for `rotation_rate`:
//   undefined / null / 0  → SSD (no platters reported)
//   -1                     → HDD detected via /sys rotational flag,
//                            but the drive doesn't expose RPM
//   > 0                    → HDD with known RPM
//   string "Solid State"   → SSD (smartctl wording on a few vendors)

export type DiskType = "NVMe" | "SSD" | "HDD"

export function getDiskType(
  diskName: string,
  rotationRate: number | string | null | undefined,
): DiskType {
  if (diskName.startsWith("nvme")) return "NVMe"
  if (rotationRate === -1) return "HDD"
  if (typeof rotationRate === "string") {
    if (rotationRate.includes("Solid State")) return "SSD"
    const parsed = Number.parseInt(rotationRate, 10)
    if (Number.isNaN(parsed) || parsed === 0) return "SSD"
    return "HDD"
  }
  if (rotationRate == null || rotationRate === 0) return "SSD"
  return "HDD"
}
