# Immich ML prerequisites and native GPU setup; no host driver installation.
validate_immich_ml_profile() {
  ML_CPU_ARGS=(--cores 2)
  ML_MEMORY=2048
  case "$ML_ACCELERATION" in
    cpu) ;;
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

configure_immich_ml_gpu() {
  case "$ML_ACCELERATION" in
    openvino)
      oci_quiet pct set "$ML_ID" --dev0 "path=${ML_RENDER_DEVICE},gid=$(stat -c %g "$ML_RENDER_DEVICE"),mode=0660"
      ;;
    cuda)
      # Isolate the shared standalone installer's runtime context from the stack.
      (
        VMID=$ML_ID
        CONF="/etc/pve/lxc/${ML_ID}.conf"
        UNPRIVILEGED_FLAG=1
        DEVICE='{"kind":"nvidia-runtime","runtime_mode":"dynamic"}'
        NVIDIA_GID_ENV=""
        DEVICE_INDEX=0
        fragment=$(mktemp)
        trap 'rm -f "$fragment"' EXIT
        printf '%s\n' '{"environment":[{"name":"NVIDIA_DRIVER_CAPABILITIES","value":"compute,utility"}]}' >"$fragment"
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
      ;;
  esac
}

validate_immich_ml_runtime() {
  [[ $ML_ACCELERATION != cpu ]] || return 0
  msg_info "$(translate "Checking the GPU of the machine learning container...")"
  oci_quiet pct exec "$ML_ID" -- python -c '
import ctypes
import sys
import onnxruntime as ort
profile = sys.argv[1]
if profile == "openvino":
    assert "OpenVINOExecutionProvider" in ort.get_available_providers()
    devices = ort.capi._pybind_state.get_available_openvino_device_ids()
    assert any(device.startswith("GPU") for device in devices), devices
else:
    assert profile == "cuda"
    assert "CUDAExecutionProvider" in ort.get_available_providers()
    driver = ctypes.CDLL("libcuda.so.1")
    assert driver.cuInit(0) == 0, "CUDA driver initialization failed"
print("Immich ML GPU runtime:", profile, "available; model inference is tested separately")
' "$ML_ACCELERATION" || return
  msg_ok "$(translate "GPU available for machine learning:") $ML_ACCELERATION"
}
