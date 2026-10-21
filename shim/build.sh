#!/bin/bash
# Build the shim and wrap it in a boot.img v2 that mirrors the stock PixelOS header.
#   BOARD=sweet      (default), guacamole or instantnoodle -> shim/boards/<board>.h
#   DTB=<file>       stock DTB fed to ABL (default dtb/boot_unpacked/dtb)
set -euo pipefail
cd "$(dirname "$0")"
BOARD=${BOARD:-sweet}
DTB=${DTB:-../dtb/boot_unpacked/dtb}
[ -f "boards/$BOARD.h" ] || { echo "unknown BOARD=$BOARD (shim/boards/)" >&2; exit 1; }
[ -f "$DTB" ] || { echo "stock DTB not found: $DTB" >&2; exit 1; }
echo "building shim for board $BOARD"
CC=aarch64-linux-gnu-gcc
OBJCOPY=aarch64-linux-gnu-objcopy
CFLAGS="-O2 -ffreestanding -nostdlib -fno-pic -mgeneral-regs-only -mstrict-align -fno-stack-protector -Wall -Wextra -DBOARD_HEADER=\"boards/$BOARD.h\""
mkdir -p out
for f in start.S shim.c console.c mmu.c fdt.c loader.c probe.c ufs.c; do
	$CC $CFLAGS -c $f -o out/${f%.*}.o
done
# The image runs wherever ABL puts it with no relocation pass: only the
# header's image_size (start.o, linked at 0) may be an absolute address.
abs=$(aarch64-linux-gnu-readelf -r out/shim.o out/console.o out/mmu.o out/fdt.o out/loader.o out/probe.o out/ufs.o | grep -c ABS64 || true)
[ "$abs" = 0 ] || { echo "error: $abs absolute relocations in C objects" >&2; exit 1; }
$CC $CFLAGS -static -T shim.ld -Wl,--build-id=none -Wl,--no-warn-rwx-segments -Wl,-N \
	out/start.o out/shim.o out/console.o out/mmu.o out/fdt.o out/loader.o out/probe.o out/ufs.o -o out/shim.elf
$OBJCOPY -O binary out/shim.elf out/Image
# ABL copies the file; pad to image_size so .bss/stacks exist as zeroed bytes.
size=$(aarch64-linux-gnu-nm out/shim.elf | awk '$3=="_end"{print strtonum("0x"$1)}')
truncate -s "$size" out/Image
# Ramdisk: an xnu payload (tools/mkpayload.py) if given as $1, else an empty
# newc cpio (ABL dislikes a zero-size ramdisk on some builds) -> diagnostics.
if [ -n "${1:-}" ]; then
	cp "$1" out/ramdisk.bin
else
	echo "no payload: building the live-FDT probe image (shim/probe.c)"
	(cd out && rm -rf rd && mkdir rd && cd rd && find . | cpio -o -H newc --quiet | gzip -9 > ../ramdisk.bin)
fi
mkbootimg --header_version 2 --kernel out/Image --ramdisk out/ramdisk.bin \
	--dtb "$DTB" --base 0 --kernel_offset 0x8000 --ramdisk_offset 0x1000000 \
	--tags_offset 0x100 --dtb_offset 0x1f00000 --pagesize 4096 \
	--os_version 17.0.0 --os_patch_level 2035-06 \
	--cmdline "console=null" -o out/shim-boot.img
# Host render of the console layout; with a DTB argument it renders the
# live-FDT bring-up report instead (out/probe.ppm).
gcc -O1 -Wall -DHOST_TEST=1 -DBOARD_HEADER=\"boards/$BOARD.h\" -o out/host_test console.c probe.c host_test.c && ./out/host_test
ls -l out/Image out/shim-boot.img
