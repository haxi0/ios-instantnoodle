#pragma once
/* OnePlus 8 (instantnoodle, SM8250 "kona"). Values from the IN2010's own
 * live FDT (audited 2026-10-21, see INSTANTNOODLE.md). Mirrors
 * tools/devices.py. */

#define BOARD_NAME "instantnoodle"

/* ABL continuous-splash framebuffer: reserved-memory cont_splash_region
 * <0x9c000000 0x02300000> (35 MiB). Panel: Samsung ana6705, 1080x2400 DSC
 * cmd mode, a8r8g8b8. */
#define FB_BASE		0x9c000000UL
#define FB_W		1080
#define FB_H		2400
#define FB_STRIDE	(FB_W * 4)

/* GICv3 (interrupt-controller@17a00000, redistributors 0x17a60000). */
#define GICD_BASE	0x17a00000UL
#define GICR_BASE	0x17a60000UL
#define GICR_SIZE	0x100000UL
#define GICR_PE_SIZE	0x20000UL
/* Standard PPI numbering on SM8250 (live FDT arm,armv8-timer <1 13>,
 * <1 14>, <1 11>, <1 12>): virt = PPI 11, non-secure phys = PPI 14. */
#define VTIMER_INTID	27
#define PTIMER_INTID	30

/* SoC-level reset registers: qcom,msm-imem@146bf000 (restart_reason@65c)
 * and restart@c264000, both the same as SM8150. */
#define IMEM_RESTART_REASON	0x146bf65cUL
#define PSHOLD			0x0c264000UL

/* Internal UFS host (ufshc@1d84000, UFS 3.0). */
#define UFS_BASE		0x01d84000UL

/* Reading the UFS host registers while ABL has it gated hung guacamole
 * (same SoC family, same host); keep the probe off until it is known to be
 * safe here. */
#define PROBE_UFS		0

/* Reset-surviving scratch word: 0x18000000 into the kernel's high bank
 * (0x180000000, same layout as guacamole). */
#define MARK_PA			0x198000000UL

/* BOARD_TLMM_PA is deliberately not defined: the shim's TLMM test uses the
 * SM8150 tile map and writes gpio104, which is wrong for SM8250's TLMM at
 * 0x0f000000 (qcom,kona-pinctrl). probe.c skips the test without it. */
