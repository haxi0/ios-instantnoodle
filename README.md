# ios-guacamole

**Apple's iOS 16 running on the OnePlus 7 Pro.**

This is a port of [ios-sweet](https://github.com/dipa-studio/ios-sweet) (XNU on the
Xiaomi Redmi Note 10 Pro) to the OnePlus 7 Pro (`guacamole`, Qualcomm SM8150 /
Snapdragon 855, Adreno 640). Apple's open-source XNU kernel (xnu-8796, the iOS 16
generation) boots from the stock bootloader and runs the **unmodified iOS 16.7.16
(20H392) userland of the iPhone X**: launchd, the system daemons, backboardd,
SpringBoard and the stock apps.

As of **2026-10-20** the phone boots to the **iOS home screen**: SpringBoard
renders, apps open, and the touchscreen works. Rendering runs entirely on the CPU;
there is no GPU driver.

![iOS 16 Settings > General > About on the OnePlus 7 Pro](docs/guacamole-about.jpg)

*iOS 16.7.16 on a OnePlus 7 Pro: Settings > General > About reports "iPhone X",
17 GB capacity and 4.15 GB available. The panel is letterboxed (1125x2436 canvas
centred in the 1440x3120 panel).*

[中文说明](README.zh-CN.md)

> Experimental bring-up, not a usable phone OS. Many things are missing or stubbed
> (see below), and Apple's security model is mostly switched off. It installs into
> the `userdata` partition and so **erases Android's user data**.

## What works

| Area | State |
| --- | --- |
| Boot | Stock OnePlus ABL → `fastboot boot` of our shim → XNU. Nothing is flashed to the boot partitions |
| CPU | All 8 cores via PSCI (`cpus=8`), 16K pages, GICv3 interrupts, 19.2 MHz timer |
| Memory | 3 GiB at `0xc0000000` (the profile also offers the 4 GiB upper bank at `0x180000000`) |
| Storage | Own UFS host driver (`ufshc@1d84000`); the iOS root is a journaled HFS+ volume in `userdata`, read/write |
| iOS userland | Real iPhone X 16.7.16 root filesystem and shared cache; launchd and the system daemons run |
| Display | Kernel IOSurface + IOMobileFramebuffer (`AppleCLCD`) services; CoreAnimation renders in software; frames are copied into the ABL splash framebuffer at 30 Hz. Presenting the iPhone X panel (1125x2436) letterboxed into the 1440x3120 panel |
| GUI | backboardd, SpringBoard, home screen, apps |
| Touch | Samsung S6SY761 at I²C `0x48` on GENI SE17, driven by **GPIO bit-bang I²C** (the SE's FIFO interface is fused off on this unit); TLMM four-tile GPIO addressing; 1.8 V rail and `ldoa17` (3008 mV) through RPMh |
| Device identity | iPhone X (`iPhone10,3` / `D22AP`): no Home button, gesture UI |
| Activation | Native "Hactivation" path of mobileactivationd, chosen through device-tree security status. No Apple servers involved |

## What does not work (yet)

- **No GPU.** The Adreno 640 sits idle; CoreAnimation uses its software renderer
  (roughly 20-30 fps). A plan exists; see [Roadmap](#roadmap).
- **No Wi-Fi, Bluetooth, cellular, audio, camera, sensors, GPS or SEP / Face ID.**
  Daemons for them start and fail or keep relaunching.
- **The setup wizard hangs** after "Don't Transfer App & Data". The root image used
  here skips Setup, which is why the home screen comes up directly.
- **Few apps.** The image has only what is on the system volume. There is no App
  Store and no Apple ID.
- **Slow boot:** about 4-5 minutes on the Apple logo.
- **Security is off:** permissive code signing (AMFI) and sandbox policies, a stub
  AppleKeyStore, no data protection. Do not put anything personal on it.

## One non-obvious requirement: `/product`

The ADT must contain the `/product` node copied from the real iPhone X device
tree. Without it, MobileGestalt has no artwork attributes (`artwork-device-idiom`,
`artwork-device-subtype`, `device-perf-memory-class`, `graphics-featureset-class`,
...) and UIKit's bounding-path asset lookup fails:

```
NSInternalInconsistencyException: Failed to load bounding path bitmap data from
the asset manager for asset name: BoundingPathBitmap-1125x2436-375x812-3.00x
```

SpringBoard aborts on its first icon render, the icon store never initializes and
the system ends up on the loginwindow fallback. The file is not in git; extract it
once from the iPhone X IPSW:

```sh
python3 tools/remotezip.py IPSW_URL DeviceTree.d22ap.im4p research/ipsw-x/dt
ipsw img4 im4p extract research/ipsw-x/dt/Firmware/all_flash/DeviceTree.d22ap.im4p \
    -o research/ipsw-x/d22ap.adt
```

`tools/mkadt.py` picks it up automatically. If it is missing it prints
`warning: ... missing, no /product node` and the resulting image will crash
SpringBoard.

## How it boots

```
ABL (stock OnePlus bootloader, unlocked)
  -> fastboot boot shim-boot.img              (temporary; nothing is flashed to boot)
     -> shim: own MMU setup, reads the live FDT, loads the payload from the ramdisk
        -> XNU Mach-O + generated Apple Device Tree (ADT) + boot-args
           -> XNU -> UFS driver -> HFS+ root in the userdata partition
              -> dyld + shared cache -> launchd -> daemons -> backboardd + SpringBoard
```

There is no usable serial port. The kernel draws its console into the framebuffer
that the ABL leaves at `0x9c000000`, and the display driver mutes it
(`sweetfb_noconsole=1`) once the GUI presents. A persistent 4 MiB log ring lives at
the end of `userdata`; the next boot with `sweetlogdump=1` prints the interesting
lines of the previous boot before the GUI starts.

## How to do it yourself

You need a OnePlus 7 Pro (GM1910/GM1911/GM1913, SM8150) with an **unlocked
bootloader**, a Linux PC, and a GitHub account for the kernel build. **Everything
on `userdata` is lost.** Bootloaders, recovery, modem, persist and the other
partitions are never touched.

### 0. Back up the phone

Boot a recovery (or use `dd` in a root shell) and pull at least `persist`,
`modemst1`, `modemst2`, `fsg`, `fsc`, `boot`, `dtbo` and `vbmeta`. They contain
per-device calibration data. Keep them off git; `.gitignore` already excludes
`backup/`, `dtb/` and `recovery/`.

The shim needs the stock DTB. Unpack your phone's stock `boot.img`:

```sh
python3 tools/unpack_bootv2.py backup/boot.img dtb/boot_unpacked   # -> dtb/boot_unpacked/dtb
```

### 1. Build the kernel

The kernel builds on GitHub's macOS runners with
[blacktop/darwin-xnu-build](https://github.com/blacktop/darwin-xnu-build). The
workflow fetches xnu-8796, applies `xnu/patches/` in order, and also stages the
pinned open-source libpthread, HFS and BearSSL sources it needs. Fork this repo
(public repos get free macOS minutes) and run:

```sh
gh workflow run xnu.yml -R YOU/ios-guacamole -f machine_config=GUACAMOLE
gh run download RUN_ID -R YOU/ios-guacamole -n xnu-kernel -D xnu/out
```

To check a patch locally before spending a CI run, `tools/xnu-cc.py` replays the
compile commands of a previous CI log for single files.

### 2. Build the iOS root image

Download the iPhone X (iPhone10,3) iOS 16.7.16 (20H392) IPSW from Apple. Then, on
Linux, with `apfs-fuse`, `hfsprogs` and sudo:

```sh
# OS, SystemOS and AppOS disk images from the IPSW (see BuildManifest.plist for their names)
tools/mkiosroot.sh OS.dmg SystemOS.dmg AppOS.dmg ios16-root.img 16G
sudo fsck.hfsplus -fy ios16-root.img
sudo mount -t hfsplus -o loop,force ios16-root.img /mnt/iosroot
sudo python3 tools/sweet-root-tweaks.py /mnt/iosroot
sudo umount /mnt/iosroot
img2simg ios16-root.img ios16-root.simg
```

`mkiosroot.sh` copies the OS volume and both cryptexes into one case-sensitive
journaled HFS+ volume. It adds the dyld cache links, the plain system keybag and
the log directories the daemons expect. `sweet-root-tweaks.py` applies the
bring-up changes: it skips Setup, seeds the activation state, removes the baseband
daemon, disables the watchdogs that kill slow apps and the crash-looping media
paths, and so on. The script's header explains each change.

`--keep-setup` leaves the purplebuddy prefs alone so the wizard runs once (it is
what creates the `mobile` session), but on guacamole the wizard currently hangs
after the "App & Data" step, so the working images use the skip mode.

### 3. Build the boot image

Needs `aarch64-linux-gnu-gcc` and `mkbootimg`.

```sh
python3 tools/mkadt.py shim/out/guacamole.adt --device guacamole
python3 tools/mkpayload.py xnu/out/kernel.development.guacamole shim/out/guacamole.adt \
    shim/out/payload.bin \
    --cmdline 'debug=0xc serial=3 cpus=8 keepsyms=1 -enable_kprintf_spam -noprogress rd=ufsroot0 unentitled_ios_sim_launch=1 ignition_level=1 wdt_test=no_user_checkin ufsrw=1 rootrw=1 launchd_unsecure_cache=1 wdt=-1 sweetusb=0 sweettouchdelay=20 sweetfb_noconsole=1 sweetfb_hz=30'
shim/build.sh ../shim/out/payload.bin      # -> shim/out/shim-boot.img
```

For a different board: `BOARD=guacamole DTB=../dtb/boot_unpacked/dtb
./build.sh ../shim/out/payload.bin` from `shim/`.

Note that `tools/mkadt.py FILE --dump` only parses an existing file. It used to
rebuild and overwrite it with the default (sweet) profile first, which silently
replaced guacamole's framebuffer geometry with sweet's.

What the less obvious boot-args do:

| Boot-arg | Effect |
| --- | --- |
| `rd=ufsroot0 ufsrw=1 rootrw=1` | Root on the `userdata` partition, writable |
| `cpus=8` | Start all eight cores; `cpus=1` is the safe fallback |
| `launchd_unsecure_cache=1` | launchd accepts its job cache without AMFI |
| `wdt=-1 wdt_test=no_user_checkin` | No hardware watchdog |
| `sweetfb_noconsole=1` | Stop drawing kernel text over the GUI. It still goes to the persistent log; panics are drawn |
| `sweetfb_hz=30` | Panel refresh rate of the CPU copy |
| `sweetusb=0` | Keep the USB gadget off (no driver for the SM8150 DWC3 yet) |
| `sweettouchdelay=20` | Wait 20 s after boot before probing the touch panel |
| `sweetlogdump=1` | At the next boot, print the previous boot's log ring before the GUI starts |

### 4. Flash the root and boot

```sh
fastboot flash userdata ios16-root.simg     # ~7 minutes; do not unplug
# OnePlus fastboot sometimes drops the connection after a large flash:
# re-enter fastboot with Power + Volume down, then
fastboot boot shim/out/shim-boot.img
```

The first boot takes about 4-5 minutes on the Apple logo, then the home screen
appears. To get back to fastboot, hold Power + Volume down.

### 5. Read the kernel log

```sh
fastboot boot /tmp/opencode/img-t26.img     # same payload + sweetlogdump=1
```

The log dump prints the crash reports (`CRASH name ...`), the daemons' `SWEET ...`
lines and the boot tasks. It appears early in the boot and scrolls away quickly;
film it or use the console build and read the letterbox bars below the GUI.

## QEMU

`tools/qemu-sweet.py` boots the same kernel on QEMU `virt` with a test RAM-disk
root. It is useful for kernel-only changes; see `NOTES.md`.

## Repository layout

| Path | What |
| --- | --- |
| `shim/` | Bare-metal boot shim (C + asm) packed as an Android boot.img v2; with no payload it prints the live-FDT bring-up report (`shim/probe.c`) |
| `xnu/patches/` | The XNU patch series (applied in order by CI), plus staging scripts for libpthread, HFS and BearSSL. **0082** is the guacamole board |
| `.github/workflows/xnu.yml` | Kernel CI build (`machine_config=GUACAMOLE`) |
| `tools/mkadt.py` | Generates the Apple Device Tree from the board's MMIO layout and the iPhone X identity (`--device sweet\|guacamole`) |
| `tools/devices.py` | Per-board hardware profiles (memory, GIC, CPUs, framebuffer, UFS) for the ADT/shim |
| `tools/mkfdt-test.py` | Test device tree for the shim's live-FDT probe and the host renderer |
| `tools/mkpayload.py` | Packs kernel + ADT + boot-args into the shim payload |
| `tools/mkiosroot.sh` | Builds the HFS+ iOS root from the IPSW images |
| `tools/sweet-root-tweaks.py` | Bring-up changes to the root (Setup skip/keep, activation, daemons) |
| `tools/sweet-log-pull.sh`, `sweet-log.py` | Read the persistent kernel log from recovery |
| `tools/sweet-crash.py` | Symbolicate console crash reports |
| `tools/xnu-cc.py` | Local single-file compile check from a CI log |
| `tools/qemu-sweet.py` | QEMU test boots with framebuffer text decoding |
| `tools/adt.py`, `remotezip.py`, `unpack_bootv2.py`, `sparsediff.py` | Helpers |
| `GUACAMOLE.md` | Hardware map, live-FDT audit and bring-up notes for this board |
| `NOTES.md` | Detailed engineering log: every boot, crash and decision, plus hardware facts |

Not in git: partition backups, live device trees, recovery images, Apple firmware
and root images, and downloaded or generated build trees. They contain device
serials and calibration data, or Apple's copyrighted files.

## Kernel patches

| # | What |
| --- | --- |
| 0001–0009 | Toolchain compatibility, SWEET machine config, non-PAC arm64, stubs for Apple-internal pieces |
| 0010–0018 | Early framebuffer console, physmap fix, PRNG without corecrypto, device-tree platform expert, timer PPI, boot CPU driver |
| 0019–0020 | Apple open-source libpthread kernel provider; BearSSL AES |
| 0021–0027 | RAM-disk root, mockfs, SHA-256, minimal AMFI, Apple open-source HFS+, MD5 |
| 0028–0034 | UFS host driver and root device, read/write root, DMA above 4 GiB |
| 0035–0045 | Entitlements, bindfs, AppleKeyStore stub, IOWatchdog, console crash reports |
| 0046 | IOSurface (IOCoreSurfaceRoot) and IOMobileFramebuffer (AppleCLCD) services |
| 0047–0057 | Diagnostics: persistent log, /dev/null tee, IOKit trace, heap strings and user stack sampler on crash; permissive Sandbox policy; HFS rename-swap; AppleKeyStore selectors |
| 0058–0061 | HID event services, iPhone X identity, display presented as 1125x2436 |
| 0062–0078 | RPMh rails, battery, GENI/Goodix (sweet) touch, SMP, console mute |
| 0079–0081 | Display power, network trace, USB link state |
| **0082** | **guacamole board**: SM8150 constants, MACHINE_CONFIG=GUACAMOLE, S6SY761 touch over bit-bang I2C, SM8150 TLMM tiles, RPMh cmd-db, letterboxed presentation, `config_personas` |

## Key hardware facts (guacamole)

- SoC: SM8150 (Snapdragon 855), 8 cores (4x Cortex-A76 + 4x Cortex-A55), no PAC,
  ARMv8.2. PSCI through `smc`, GICv3 at `0x17a00000` / `0x17a60000`, 19.2 MHz timer.
- RAM: the profile places the kernel at `0xc0000000` + 3 GiB; `--highmem` uses the
  4 GiB upper bank at `0x180000000` instead. The 8/12 GB SKUs are both covered.
- Panel: Samsung S6E3HC2, 1440x3120. The ABL's continuous splash lives at
  `0x9c000000` (36 MiB) and stays scanned out across `fastboot boot`; there is no
  DSI/DSC driver in the kernel.
- UFS: `ufshc@1d84000`, HS-G4, 2 lanes. The ABL leaves the link up; the driver
  only owns the register block.
- Touch: S6SY761 at `0x48` on GENI SE17 (`i2c@0xc80000`); on this unit
  `GENI_IF_DISABLE_RO` bit 0 is set, so the FIFO interface is fused off and the
  transport is a GPIO bit-bang I2C (~100 kHz). Pins: panel reset 6, touch 54/55/56/
  119/122 (SOUTH TLMM tile), IRQ 122.
- TLMM: four tile arrays inside `0x03000000`: west `+0x100000`, east `+0x500000`,
  north `+0x900000`, south `+0xD00000`; pins live at `tile + 0x1000*gpio`.
- RPMh: RSC/DRV-2 at `0x18220000`, TCS at `0x18220d00`, command-DB locator at
  `0x0c3f000c`. The touch rail is `ldoa17` at `0x41300` (3008 mV).
- GPU (not driven yet): Adreno 640 at `/soc/qcom,kgsl-3d0@2C00000`, GPUCC
  `qcom,gpucc-sm8150` at `0x2c90000`, apps SMMU at `0x15000000`, zap shader
  `a640_zap` through `/soc/qcom,kgsl-hyp` (PAS id 0xd).

More in [`NOTES.md`](NOTES.md) and [`GUACAMOLE.md`](GUACAMOLE.md).

## Roadmap

1. **Stability and usability** of the current image: auto-lock/wake, frame rate,
   crash-free long runs.
2. **GPU (Adreno 640).** No existing driver drops into this kernel: Turnip,
   Freedreno and KGSL assume Linux `/dev/kgsl-3d0` or DRM, and the macOS
   `IOAcceleratorFamily2`/AGX kexts are not present in the iOS 16 userland.
   [UniXNU NativeAdreno](https://github.com/UniXNU/NativeAdreno) supplies a
   reusable XNU skeleton (GMU, CP ring, BOs, SMMUv2, fences), but the a640
   power-up tables, GMU HFI version, GPUCC clocks, SMMU SIDs and zap path must be
   written against Mesa's `a6xx` reference. Order: (1) kernel power-up + GMU +
   SQE + one CP queue; acceptance is the CP writing a known value into a mapped
   buffer and the CPU reading it back; (2) userspace buffers/queues/fences and a
   Mesa/Turnip port; (3) an iOS `_MTLDevice` plugin using the `MetalPluginName`
   loading path, with AIR to SPIR-V via metal2vulkan and Turnip's
   SPIR-V→NIR→IR3. Patches 0085-0088 are the first kernel steps: `sweetgpu=2`
   powers the CX GDSC, and `sweetgpu=4` votes `gfx.lvl` corner 1 before
   powering the GX GDSC (`PWR_UP` verified on hardware). RBBM still reads zero
   because the GPU/GMU clocks are off; GMU, SMMU and the CP ring are still
   missing. GLES is not an independent shortcut:
   `AppleMetalGLRenderer` is a Metal client.
3. **Radios and audio** (Wi-Fi, Bluetooth, UART, speakers) are separate bring-up
   projects of similar size.

## Second board: Redmi Note 10 Pro (sweet)

The upstream project. The same tree still builds for the Redmi Note 10 Pro
(`sweet`, SM7150) with `--device sweet`, `BOARD=sweet` and `machine_config=SWEET`;
that port has its own touch (Goodix GT9896), buttons and battery drivers and is
what the display/IOSurface/KeyStore work was developed on. See the
[upstream README](https://github.com/dipa-studio/ios-sweet) and the sweet sections
of `NOTES.md`.

## Credits

Built on Apple's open-source releases (xnu, IOHIDFamily, libpthread, hfs),
[BearSSL](https://bearssl.org),
[blacktop/darwin-xnu-build](https://github.com/blacktop/darwin-xnu-build),
[ipsw](https://github.com/blacktop/ipsw), Qualcomm/OnePlus' published Linux
kernel sources for the hardware details, and the
[ios-sweet](https://github.com/dipa-studio/ios-sweet) project, which made the
userland side possible. The GPU roadmap references
[UniXNU](https://github.com/UniXNU) (NativeAdreno, NativeMetal, AirNir,
AdrenoPM4, AdrenoFirmware, ArmSmmu4K) and Mesa's
[freedreno/Turnip](https://gitlab.freedesktop.org/mesa/mesa) drivers.
iOS itself is Apple's and is not distributed here.

The OnePlus 8 (instantnoodle) port takes code from **HackiOS** by
[OOSEX GANG](https://t.me/oosexgangdevs)
([hackios-xnu-kernel](https://github.com/oosexgang/hackios-xnu-kernel), APSL 2.0;
[hackios-xnu-userland](https://github.com/oosexgang/hackios-xnu-userland), MIT),
XNU on the POCO X5 Pro 5G (SM7325). Each ported file names its HackiOS source
in its header:

| Here | From HackiOS |
|---|---|
| `bsd/dev/sweet_cpufreq.c` (xnu 0107) | `xnu/files/bsd/dev/redwood_cpufreq.c`: EPSS clock raise, loop-speed check, `membench=1` |
| `bsd/dev/sweet_adreno.c` (xnu 0108) | `xnu/files/bsd/dev/redwood_adreno.c`: the staged Adreno bring-up (`adreno=N`), steps 1-10 so far, with SM8250/Adreno 650 values |
