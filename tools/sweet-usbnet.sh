#!/bin/sh
# Host side of the phone's USB Ethernet (kernel sweetusb=2, patches 0075-0077, 0105).
#   tools/sweet-usbnet.sh [LOGFILE]
#   tools/sweet-usbnet.sh reset
# Waits for the phone's CDC-ECM interface (host MAC 02:00:5e:77:ee:01),
# gives it 192.168.7.1/24 (the phone is 192.168.7.2), then prints the live
# kernel console the phone streams to UDP port 5140 (and appends it to
# LOGFILE if given). Needs sudo for the address unless it is already set
# (e.g. by a systemd-networkd .network file matching that MAC).
# `reset` sends "reset" to udp/5141: the phone flushes its log ring and
# reboots to the bootloader (0105). With SWEET_IDLE=SECS and a LOGFILE, the
# reset is sent by itself when the log has not grown for SECS seconds.
set -eu
mac=02:00:5e:77:ee:01
if [ "${1:-}" = reset ]; then
	printf reset | nc -u -w1 192.168.7.2 5141
	echo "reset sent to 192.168.7.2:5141" >&2
	exit 0
fi
echo "waiting for the phone's USB Ethernet ($mac)..." >&2
until ip -o link | grep -qi "$mac"; do sleep 1; done
ifname=$(ip -o link | grep -i "$mac" | awk -F': ' '{print $2}' | cut -d@ -f1)
if ! ip -o addr show dev "$ifname" | grep -q '192\.168\.7\.1/'; then
	nmcli dev set "$ifname" managed no 2>/dev/null || true
	sudo ip addr replace 192.168.7.1/24 dev "$ifname"
	sudo ip link set "$ifname" up
fi
echo "$ifname up: 192.168.7.1 <-> phone 192.168.7.2; live log on udp/5140" >&2
if [ $# -ge 1 ] && [ -n "${SWEET_IDLE:-}" ]; then
	(
		last=-1
		while sleep "$SWEET_IDLE"; do
			size=$(stat -c %s "$1" 2>/dev/null || echo 0)
			if [ "$size" = "$last" ]; then
				echo "log idle for ${SWEET_IDLE}s: sending reset" >&2
				printf reset | nc -u -w1 192.168.7.2 5141 || true
			fi
			last=$size
		done
	) &
fi
if [ $# -ge 1 ]; then
	nc -ukl 5140 | tee -a "$1"
else
	nc -ukl 5140
fi
