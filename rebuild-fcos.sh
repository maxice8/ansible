#!/bin/sh
set -e

VM_NAME="fcos-test"
BU_FILE="config.bu"
IGN_FILE="config.ign"
BASE_IMAGE="$HOME/.local/share/libvirt/images/fedora-coreos-43.20260301.3.1-qemu.x86_64.qcow2"

podman run --interactive --rm quay.io/coreos/butane:release --strict < "$BU_FILE" > "$IGN_FILE"
echo "compiled $BU_FILE to $IGN_FILE"

sudo virsh -c qemu:///system destroy "$VM_NAME" >/dev/null 2>&1 || true
sudo virsh -c qemu:///system undefine "$VM_NAME" --remove-all-storage >/dev/null 2>&1 || true
echo "cleaned up existing vms..."

virt-install \
  --connect qemu:///system \
  --name "$VM_NAME" \
  --memory 2048 \
  --vcpus 2 \
  --os-variant fedora-coreos-next \
  --import \
  --disk size=20,backing_store="$BASE_IMAGE" \
  --network network=default \
  --graphics spice \
  --qemu-commandline="-fw_cfg name=opt/com.coreos/config,file=$PWD/$IGN_FILE" \
  --quiet \
  --noautoconsole
echo "provisioned $VM_NAME, waiting for ip address..."

IP=""
# Loop up to 30 times, waiting 2 seconds each time (60 seconds total timeout)
for _ in $(seq 1 30); do
    # Ask libvirt specifically for the DHCP lease of this exact VM
    IP=$(sudo virsh -c qemu:///system domifaddr "$VM_NAME" --source lease 2>/dev/null | grep ipv4 | awk '{print $4}' | cut -d/ -f1 | head -n 1)
    
    if [ -n "$IP" ]; then
        break
    fi
    sleep 2
done

if [ -n "$IP" ]; then
    echo "done. ip: $IP"
else
    echo "done. (timed out waiting for ip - check virt-manager console)"
fi
