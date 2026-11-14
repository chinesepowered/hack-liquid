#!/usr/bin/env bash
# Isolated laptop <-> board network over the IQ-9075's USB-C port (USB NCM gadget).
# The demo control/UI link the hackathon allows: no internet, no forwarding, just the two hosts.
# Windows 11 binds its inbox NCM driver and gives itself a 169.254.x.x link-local address;
# the board takes 169.254.7.2/16 on the same link, so no DHCP and no laptop admin rights are needed.
#   sudo scripts/usb_link.sh [udc]     then on the laptop: ssh ubuntu@169.254.7.2
set -euo pipefail
ADDR=169.254.7.2/16
G=/sys/kernel/config/usb_gadget/capy

modprobe libcomposite
mountpoint -q /sys/kernel/config || mount -t configfs none /sys/kernel/config

if [ ! -d "$G" ]; then
  mkdir -p "$G" && cd "$G"
  echo 0x1d6b > idVendor          # Linux Foundation
  echo 0x0104 > idProduct         # Multifunction Composite Gadget
  echo 0x0200 > bcdUSB
  mkdir -p strings/0x409
  echo capytower0001 > strings/0x409/serialnumber
  echo "Team chinese" > strings/0x409/manufacturer
  echo "Capy Tower USB link" > strings/0x409/product
  mkdir -p configs/c.1/strings/0x409
  echo NCM > configs/c.1/strings/0x409/configuration
  echo 250 > configs/c.1/MaxPower
  mkdir -p functions/ncm.usb0
  ln -s functions/ncm.usb0 configs/c.1/
fi
cd "$G"

UDC="${1:-}"
if [ -z "$UDC" ]; then UDC=$(ls /sys/class/udc | head -1); fi
if [ "$(cat UDC 2>/dev/null)" != "$UDC" ]; then
  echo "" > UDC 2>/dev/null || true
  echo "$UDC" > UDC
fi

IF=$(cat functions/ncm.usb0/ifname)
command -v nmcli >/dev/null && nmcli dev set "$IF" managed no 2>/dev/null || true
ip addr replace "$ADDR" dev "$IF"
ip link set "$IF" up
echo "gadget on UDC $UDC, interface $IF, address $ADDR, udc state: $(cat /sys/class/udc/$UDC/state)"
