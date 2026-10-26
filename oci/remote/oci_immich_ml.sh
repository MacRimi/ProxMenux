# Immich ML prerequisites and native GPU setup; no host driver installation.
validate_immich_ml_profile() {
  ML_CPU_ARGS=(--cores 4)
  ML_MEMORY=4096
  ML_ROOTFS_SIZE=12
  case "$ML_ACCELERATION" in
    cpu) ;;
    rocm)
      ML_RENDER_DEVICE=$(jq -er '.machine_learning.render_device' "$DEPLOYMENT_FILE")
      [[ $ML_RENDER_DEVICE =~ ^/dev/dri/renderD[0-9]+$ && -c $ML_RENDER_DEVICE ]] \
        || die "$(translate "The selected AMD render device does not exist:") $ML_RENDER_DEVICE"
      [[ $(cat "/sys/class/drm/${ML_RENDER_DEVICE##*/}/device/vendor") == 0x1002 ]] \
        || die "$(translate "ROCm requires the render device of an AMD GPU")"
      [[ -c /dev/kfd ]] || die "$(translate "ROCm requires /dev/kfd on the host")"
      ML_MEMORY=8192
      # The ROCm image carries the whole AMD runtime and is several times
      # larger than the others.
      ML_ROOTFS_SIZE=40
      ;;
    openvino)
      ML_RENDER_DEVICE=$(jq -er '.machine_learning.render_device' "$DEPLOYMENT_FILE")
      [[ $ML_RENDER_DEVICE =~ ^/dev/dri/renderD[0-9]+$ && -c $ML_RENDER_DEVICE ]] \
        || die "$(translate "The selected Intel render device does not exist:") $ML_RENDER_DEVICE"
      [[ $(cat "/sys/class/drm/${ML_RENDER_DEVICE##*/}/device/vendor") == 0x8086 ]] \
        || die "$(translate "OpenVINO requires the render device of an Intel GPU")"
      ML_CPU_ARGS=(--cpulimit 4)
      ML_MEMORY=8192
      ;;
    cuda)
      command -v nvidia-container-cli >/dev/null 2>&1 \
        || die "$(translate "CUDA requires the NVIDIA Container Toolkit on the host")"
      command -v nvidia-smi >/dev/null 2>&1 \
        || die "$(translate "CUDA requires a working NVIDIA driver")"
      local inventory version capability
      inventory=$(nvidia-smi --query-gpu=driver_version,compute_cap --format=csv,noheader) \
        || die "$(translate "Could not check the NVIDIA GPU")"
      [[ -n $inventory ]] || die "$(translate "No NVIDIA GPU is available")"
      while IFS=, read -r version capability; do
        [[ $version =~ ^[0-9]+\.[0-9]+(\.[0-9]+)?$ ]] \
          || die "$(translate "Could not read the NVIDIA driver version")"
        (( ${version%%.*} >= 545 )) || die "$(translate "Immich CUDA requires NVIDIA driver 545 or later")"
        capability=${capability//[[:space:]]/}
        [[ $capability =~ ^[0-9]+\.[0-9]+$ ]] \
          || die "$(translate "Could not read the CUDA compute capability")"
        awk -v value="$capability" 'BEGIN {exit !(value >= 5.2)}' \
          || die "$(translate "Immich requires CUDA compute capability 5.2 or later")"
      done <<<"$inventory"
      [[ -r $SCRIPT_DIR/nvidia_lxc_mount_lab.sh ]] || die "$(translate "The dynamic NVIDIA hook is missing")"
      ML_CPU_ARGS=(--cores 4)
      ML_MEMORY=8192
      ;;
    *) die "$(translate "Machine learning profile not implemented; it is not replaced by CPU:") $ML_ACCELERATION" ;;
  esac
  local cores allocation default_allocation
  default_allocation=cpuset
  [[ $ML_ACCELERATION != openvino ]] || default_allocation=quota
  cores=$(jq -er --argjson fallback "${ML_CPU_ARGS[1]}" '.machine_learning.resources.cores // $fallback' "$DEPLOYMENT_FILE")
  ML_MEMORY=$(jq -er --argjson fallback "$ML_MEMORY" '.machine_learning.resources.memory_mb // $fallback' "$DEPLOYMENT_FILE")
  ML_SWAP=$(jq -er '.machine_learning.resources.swap_mb // 1024' "$DEPLOYMENT_FILE")
  allocation=$(jq -er --arg fallback "$default_allocation" '.machine_learning.resources.cpu_allocation // $fallback' "$DEPLOYMENT_FILE")
  [[ $cores =~ ^[1-9][0-9]*$ && $ML_MEMORY =~ ^[1-9][0-9]*$ && $ML_SWAP =~ ^(0|[1-9][0-9]*)$ ]] \
    || die "$(translate "Invalid machine learning resources")"
  case "$allocation" in
    quota) ML_CPU_ARGS=(--cpulimit "$cores") ;;
    cpuset)
      [[ $ML_ACCELERATION != openvino ]] || die "$(translate "OpenVINO requires a CPU quota to keep the CPU topology")"
      ML_CPU_ARGS=(--cores "$cores")
      ;;
    *) die "$(translate "Invalid machine learning CPU allocation:") $allocation" ;;
  esac
}

# Gives one container of the stack the NVIDIA GPU through the dynamic hook.
# Arguments: VMID CAPABILITIES
configure_immich_nvidia() {
  # Isolate the shared standalone installer's runtime context from the stack.
  (
    VMID=$1
    CONF="/etc/pve/lxc/${VMID}.conf"
    UNPRIVILEGED_FLAG=1
    DEVICE='{"kind":"nvidia-runtime","runtime_mode":"dynamic"}'
    NVIDIA_GID_ENV=""
    DEVICE_INDEX=0
    while grep -q "^dev${DEVICE_INDEX}:" "$CONF"; do DEVICE_INDEX=$((DEVICE_INDEX + 1)); done
    fragment=$(mktemp)
    trap 'rm -f "$fragment"' EXIT
    jq -nc --arg capabilities "$2" \
      '{environment:[{name:"NVIDIA_DRIVER_CAPABILITIES",value:$capabilities}]}' >"$fragment"
    DEPLOYMENT_FILE=$fragment
    add_character_device() {
      local path=$1 mode gid
      [[ -c $path && $path == /dev/nvidia* ]] || die "$(translate "Invalid NVIDIA device:") $path"
      mode="0$(stat -c %a "$path")"
      gid=$(stat -c %g "$path")
      oci_quiet pct set "$VMID" "--dev${DEVICE_INDEX}" "path=${path},mode=${mode},gid=${gid},deny-write=0"
      DEVICE_INDEX=$((DEVICE_INDEX + 1))
    }
    configure_nvidia_runtime
  )
}

configure_immich_ml_gpu() {
  case "$ML_ACCELERATION" in
    openvino)
      oci_quiet pct set "$ML_ID" --dev0 "path=${ML_RENDER_DEVICE},gid=$(stat -c %g "$ML_RENDER_DEVICE"),mode=0660"
      ;;
    rocm)
      oci_quiet pct set "$ML_ID" --dev0 "path=${ML_RENDER_DEVICE},gid=$(stat -c %g "$ML_RENDER_DEVICE"),mode=0660"
      oci_quiet pct set "$ML_ID" --dev1 "path=/dev/kfd,gid=$(stat -c %g /dev/kfd),mode=0660"
      ;;
    cuda)
      configure_immich_nvidia "$ML_ID" "compute,utility"
      ;;
  esac
}

# The generation of the AMD GPU as the compute driver names it, e.g. gfx1030.
amd_gfx_arch() {
  local target
  target=$(awk '$1 == "gfx_target_version" && $2 > 0 {print $2}' \
    /sys/class/kfd/kfd/topology/nodes/*/properties 2>/dev/null | sort -n | tail -1)
  [[ -n $target ]] || return 1
  printf 'gfx%d%d%x' $((target / 10000)) $((target / 100 % 100)) $((target % 100))
}

validate_immich_ml_runtime() {
  [[ $ML_ACCELERATION != cpu ]] || return 0
  msg_info "$(translate "Checking the GPU of the machine learning container...")"
  if [[ $ML_ACCELERATION == rocm ]]; then
    # The provider being present says nothing about this GPU: the image
    # carries kernels for some generations, and on any other every inference
    # aborts.
    local arch
    if [[ -n ${ML_GFX_OVERRIDE:-} ]]; then
      # ROCm is told to treat this GPU as the generation of its family.
      arch="gfx${ML_GFX_OVERRIDE//./}"
    else
      arch=$(amd_gfx_arch) || arch=""
    fi
    if [[ -n $arch ]]; then
      # Listed first: a match ends grep early, and with pipefail the listing
      # it cut short would read as a failure.
      local kernels
      kernels=$(pct exec "$ML_ID" -- sh -c 'ls /opt/rocm/lib/rocblas/library 2>/dev/null' || true)
      grep -Eq "[_-]${arch}\\.(dat|co|hsaco)" <<<"$kernels" || {
          oci_log "The ROCm image has no kernels for $arch"
          msg_warn "$(translate "The ROCm image has no support for the AMD GPU of this host:") $arch"
          return 1
        }
    fi
  fi
  oci_quiet pct exec "$ML_ID" -- python -c '
import ctypes
import sys
import onnxruntime as ort
profile = sys.argv[1]
if profile == "openvino":
    assert "OpenVINOExecutionProvider" in ort.get_available_providers()
    devices = ort.capi._pybind_state.get_available_openvino_device_ids()
    assert any(device.startswith("GPU") for device in devices), devices
elif profile == "rocm":
    assert "MIGraphXExecutionProvider" in ort.get_available_providers(), ort.get_available_providers()
else:
    assert profile == "cuda"
    assert "CUDAExecutionProvider" in ort.get_available_providers()
    driver = ctypes.CDLL("libcuda.so.1")
    assert driver.cuInit(0) == 0, "CUDA driver initialization failed"
print("Immich ML GPU runtime:", profile, "available; model inference is tested separately")
' "$ML_ACCELERATION" || return
  if [[ $ML_ACCELERATION == rocm ]]; then
    # One real inference on the GPU: the provider alone does not prove it.
    python3 "${SCRIPT_DIR}/oci_rocm_check.py" "$ML_ID" >>"${OCI_LOG:-/dev/null}" 2>&1 || {
      msg_warn "$(translate "The AMD GPU did not complete a test inference with ROCm")"
      return 1
    }
  fi
  msg_ok "$(translate "GPU available for machine learning:") $ML_ACCELERATION"
}
