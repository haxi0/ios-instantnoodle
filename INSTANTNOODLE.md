# instantnoodle: the sweet port on the OnePlus 8 (SM8250)

The third board of the port, after sweet (SM7150) and guacamole (SM8150).
Same plan: **Apple's XNU boots from the stock bootloader via `fastboot boot`,
reuses ABL's continuous-splash framebuffer, runs the unmodified iPhone X iOS
16.7.16 userland, and keeps its HFS+ root inside `userdata`.** The userland,
the ADT identity (`D22AP` / `iPhone10,3`) and the root image are unchanged.

Status (2026-10-21): **scaffold only, nothing booted yet.** Board profile,
shim board header, kernel machine config `INSTANTNOODLE` (patch 0103) and the
ADT build are in place; the probe shim builds and renders the phone's live-FDT
report on the host. No image has been booted on the phone.

## Where the device lives in the tree

| Layer | instantnoodle |
| --- | --- |
| ADT | `tools/mkadt.py --device instantnoodle --highmem` (`tools/devices.py`) |
| Shim | `BOARD=instantnoodle shim/build.sh` (`shim/boards/instantnoodle.h`) |
| Kernel | `MACHINE_CONFIG=INSTANTNOODLE` (CI input `machine_config`), patch 0103 |
| Kernel constants | `pexpert/pexpert/arm64/sweet_dev.h`, first block |
| Audit | `tools/fdt-audit.py dtb/instantnoodle-live.dtb --device instantnoodle` |

`INSTANTNOODLE` defines `ARM64_BOARD_CONFIG_SWEET` like `GUACAMOLE` does, so
all of the port's platform code builds; it does **not** define
`ARM64_BOARD_CONFIG_GUACAMOLE`, so the guacamole GPU bring-up (0084-0102)
compiles out.

## Audited on the phone (2026-10-21)

Retail **IN2010** (India), OxygenOS 11 (`OnePlus8_IND`, `RP1A.201005.001`,
build 2202142212), slot `_b`, **bootloader unlocked** (`orange`), Magisk
root, 8 GB RAM. Pulled read-only (all gitignored):

| Pulled | Where |
| --- | --- |
| live FDT (`/sys/firmware/fdt`, 889 KB) and its `dtc` decompile | `dtb/instantnoodle-live.dtb`, `research/instantnoodle-live.dts` |
| `/proc` iomem, interrupts, cpuinfo, cmdline, meminfo; dmesg; getprop; by-name; partitions | `research/` |
| every by-name partition except `userdata` (118 images, 21 GB, sha256-verified against the phone) | `backup/partitions/`, log `backup/backup.log` |
| stock `boot_b` unpacked (header v2, base 0, kernel 0x8000, ramdisk 0x1000000, tags 0x100, dtb 0x1f00000 - the offsets `shim/build.sh` already uses) | `dtb/boot_unpacked/` |

`tools/fdt-audit.py dtb/instantnoodle-live.dtb --device instantnoodle` reports
**20/20 match**.

## Board facts

| Area | Value | Source |
| --- | --- | --- |
| SoC | SM8250 `kona`, project 19821 | live FDT, cmdline |
| CPUs | Kryo 585: 4x A55 (MIDR part 0x805) + 4x A77 (0xd0d), MPIDR 0x000..0x700; max 1.8048 / 2.4192 / 2.8416 GHz | live FDT, cpufreq |
| Memory | `0x80000000+0x3bb00000`, `0xc0000000+0xc0000000`, `0x180000000+0x100000000` (same as guacamole) | live FDT |
| Splash | `cont_splash_region` **0x9c000000 + 0x02300000** | live FDT |
| Panel | Samsung **ana6705** (`qcom,mdss_dsi_samsung_ana6705_dsc_cmd`), 1080x2400 DSC cmd, 70 x 151 mm | cmdline, live FDT |
| GIC / timer | 0x17a00000 / 0x17a60000, timer 0x17c20000 | live FDT |
| UFS | `ufshc@1d84000`, PHY `0x1d87000` | live FDT |
| SPMI | `qcom,spmi@c440000` (same regs as SM8150); PM8150 = SID 0 | live FDT |
| Keys | power = PM8150 PON; volume up/down = **PM8150 GPIO6/GPIO7**, active low (guacamole layout) | live FDT `gpio-keys` |
| RPMh | `rsc@18200000` "apps_rsc", drv-id 2 -> DRV-2 **0x18220000**, tcs-offset 0xd00; cmd-db is `reserved-memory@80860000` | live FDT |
| TLMM | **`pinctrl@f000000`** (`qcom,kona-pinctrl`, 16 MiB) | live FDT |
| USB | dwc3 `0xa600000`, HS PHY **`0x88e3000`**, QMP `0x88e8000` | live FDT |
| Touch | **Samsung S6SY761** ("SY771") @0x48 on **`i2c@a94000`**; reset tlmm 38, IRQ tlmm 39; vdd pm8150_l13 (`ldoa13`, 3.008 V), vcc pm8150a_l1 (`ldoc1`); dmesg shows it probing (Synaptics S3908 @0x4b is the alternative part) | live FDT, dmesg |
| IMEM / PS_HOLD | `0x146bf000` (restart_reason 0x146bf65c) / `0x0c264000` | live FDT |

## What is switched on in the first kernel

- Display (ABL splash), UFS root, power key, **volume keys** (same PM8150
  GPIO6/7 layout as guacamole, so patch 0083's path is enabled).
- **Touch off** (`SWEET_DEV_TOUCH_SEC 0`): `sweet_touch_sec.c` hardcodes the
  SM8150 TLMM tiles and pins and a GPIO 1.8 V switch; the OnePlus 8 needs the
  kona tiles at `0x0f000000`, pins 38/39, the SE at `0xa94000` and a second
  RPMh rail (`ldoc1`).
- **USB off** (`SWEET_DEV_USB 0`): the SM8250 GCC USB GDSC/CBCR offsets are
  not filled in yet, and the HS PHY moved to `0x88e3000`.
- The shim skips its TLMM write test (no `BOARD_TLMM_PA`; the test uses the
  SM8150 tile map) and its UFS probe (`PROBE_UFS 0`, as on guacamole).

## Bring-up sequence

1. **Probe boot** (no payload), with the phone in fastboot:
   ```sh
   BOARD=instantnoodle DTB=../dtb/boot_unpacked/dtb shim/build.sh
   fastboot boot shim/out/shim-boot.img
   ```
   Expected: `BOARD instantnoodle`, the live-FDT report (see
   `shim/out/probe.ppm` for the host render), then a ~180 s countdown and a
   reset to the bootloader.
2. **Kernel**: GitHub Actions `xnu` workflow, `machine_config=INSTANTNOODLE`;
   artifact `kernel.development.instantnoodle`.
3. **ADT + payload + image**:
   ```sh
   python3 tools/mkadt.py shim/out/instantnoodle.adt --device instantnoodle --highmem
   python3 tools/mkpayload.py xnu/out/kernel.development.instantnoodle shim/out/instantnoodle.adt \
       shim/out/payload-noodle.bin --cmdline 'debug=0xc serial=3 cpus=1 keepsyms=1 -noprogress rd=ufsroot0 unentitled_ios_sim_launch=1 ignition_level=1 wdt_test=no_user_checkin ufsrw=1 rootrw=1 launchd_unsecure_cache=1 wdt=-1 sweetfb_hz=30'
   BOARD=instantnoodle DTB=../dtb/boot_unpacked/dtb shim/build.sh ../shim/out/payload-noodle.bin
   ```
   Start with `cpus=1`; without an iOS root in `userdata` the kernel waits
   for the root device (expected).
4. **iOS root** in `userdata` (`tools/mkiosroot.sh`, same image as
   guacamole). The user approved wiping `userdata` on 2026-10-21; nothing
   else is flashed.
5. Then: `cpus=8`, touch (SM8250 TLMM tiles + `ldoc1`), USB.
