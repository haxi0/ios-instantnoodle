#!/bin/bash
# One unattended OnePlus 8 test boot: build an image from the current kernel,
# boot it from RAM, let the kernel reboot itself to the bootloader after SECS
# (xnu 0104, boot-arg sweetreset), boot TWRP from RAM, pull the console log
# ring from the end of userdata, and leave the phone in fastboot again.
#
#   tools/noodle-run.sh NAME SECS ["extra boot-args"]
#
# Needs: the phone in fastboot, xnu/out/kernel.development.instantnoodle,
# recovery/twrp.img, dtb/boot_unpacked/dtb. Writes logs/NAME.txt. Nothing is
# flashed. If the PC stops seeing the phone in fastboot, replug the cable.
set -euo pipefail
cd "$(dirname "$0")/.."
name=${1:?usage: noodle-run.sh NAME SECS [extra boot-args]}
secs=${2:?usage: noodle-run.sh NAME SECS [extra boot-args]}
extra=${3:-}
kernel=${KERNEL:-xnu/out/kernel.development.instantnoodle}
base="debug=0xc serial=3 cpus=8 keepsyms=1 -noprogress rd=ufsroot0 unentitled_ios_sim_launch=1 ignition_level=1 wdt_test=no_user_checkin ufsrw=1 rootrw=1 launchd_unsecure_cache=1 wdt=-1 sweetfb_noconsole=1 sweetfb_hz=30"
mkdir -p logs

stamp() { date +%H:%M:%S; }
bootloader_ready() { [ "$(timeout 5 fastboot getvar product 2>&1 | awk '/^product:/{print $2}')" = kona ]; }
wait_bootloader() {    # $1 = seconds
	local end=$((SECONDS + $1))
	until bootloader_ready; do
		[ $SECONDS -lt $end ] || { echo "$(stamp) no answering bootloader (replug the cable?)" >&2; return 1; }
		sleep 3
	done
}

python3 tools/mkadt.py shim/out/instantnoodle.adt --device instantnoodle --highmem >/dev/null
python3 tools/mkpayload.py "$kernel" shim/out/instantnoodle.adt "shim/out/payload-$name.bin" \
	--cmdline "$base sweetreset=$secs $extra" >/dev/null
BOARD=instantnoodle DTB=../dtb/boot_unpacked/dtb shim/build.sh "../shim/out/payload-$name.bin" >/dev/null 2>&1
cp shim/out/shim-boot.img "shim/out/$name.img"
echo "$(stamp) image shim/out/$name.img ($(sha256sum "shim/out/$name.img" | cut -c1-16))"

wait_bootloader 300
timeout 90 fastboot boot "shim/out/$name.img" >/dev/null 2>&1
echo "$(stamp) booted iOS, kernel resets in ${secs}s"
# Wait for the phone to leave fastboot, then for the kernel's reset to bring it back.
sleep 20
wait_bootloader $((secs + 300))
echo "$(stamp) back in the bootloader"

timeout 90 fastboot boot recovery/twrp.img >/dev/null 2>&1
end=$((SECONDS + 180))
until adb devices | grep -q 'recovery$'; do
	[ $SECONDS -lt $end ] || { echo "$(stamp) TWRP did not show up on adb" >&2; exit 1; }
	sleep 3
done
tools/sweet-log-pull.sh "logs/$name.txt"
adb reboot bootloader
echo "$(stamp) log logs/$name.txt ($(wc -l < "logs/$name.txt") lines); phone returning to fastboot"
grep -E 'SWEET RESET|^CRASH .* sig|panic|SpringBoard|swap [0-9]+ ' "logs/$name.txt" | tail -15 || true
