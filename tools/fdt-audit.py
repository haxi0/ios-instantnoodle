#!/usr/bin/env python3
"""Audit a device's live FDT against the board profile the port was built with.

    tools/fdt-audit.py LIVE.dtb [--device guacamole|instantnoodle] [--profile-only]

LIVE.dtb is usually /sys/firmware/fdt pulled from the phone (root):
    adb exec-out "su -c cat /sys/firmware/fdt" > dtb/<board>-live.dtb

It prints the same facts the shim's bring-up report shows (memory banks,
reserved-memory carve-outs, GIC/timer/UFS/USB/SPMI/RPMh/TLMM/GCC nodes, CPU
MPIDRs) and then a MATCH / MISMATCH table against tools/devices.py and the
per-board kernel constants (kept in MIRROR below, mirroring
pexpert/pexpert/arm64/sweet_dev.h and shim/boards/<board>.h). Exit status is
1 when anything mismatches, so a bring-up check can gate on it.
"""
import argparse
import struct
import sys

sys.path.insert(0, __file__.rsplit('/', 1)[0])
import devices  # noqa: E402

# Per-board driver constants that only live in the kernel/shim headers; keep
# in sync with pexpert/pexpert/arm64/sweet_dev.h and shim/boards/<board>.h.
MIRROR = {
    'guacamole': {
        'SPMI core': 0x0c440000,
        'SPMI observer': 0x0e600000,
        'SPMI config': 0x0c40a000,
        'USB GCC': 0x00100000,
        'USB DWC3': 0x0a600000,
        'USB HS PHY': 0x088e2000,
        'USB QMP PHY': 0x088e8000,
        'RCG/SE17': 0x00c80000,
        'Touch bus': 'i2c@c80000',
        'TLMM': 0x03000000,
        'PSHOLD': 0x0c264000,
        'IMEM': 0x146bf000,
        'RPMh RSC': 0x18220000,
        'RPMh TCS': 0x18220d00,
        'RPMh cmd DB': 0x0c3f000c,
    },
    'instantnoodle': {
        'SPMI core': 0x0c440000,
        'SPMI observer': 0x0e600000,
        'SPMI config': 0x0c40a000,
        'USB GCC': 0x00100000,
        'USB DWC3': 0x0a600000,
        'USB HS PHY': 0x088e3000,
        'USB QMP PHY': 0x088e8000,
        'Touch bus': 'i2c@a94000',
        'TLMM': 0x0f000000,
        'PSHOLD': 0x0c264000,
        'IMEM': 0x146bf000,
        'RPMh RSC': 0x18220000,
        'RPMh TCS': 0x18220d00,
        'RPMh cmd DB': 0x0c3f000c,
    },
    'sweet': {
        'SPMI core': 0x0c440000,
        'SPMI observer': 0x0e600000,
        'SPMI config': 0x0c40a000,
        'USB GCC': 0x00100000,
        'USB DWC3': 0x0a600000,
        'USB HS PHY': 0x088e2000,
        'GENI SE7': 0x00a84000,
        'TLMM': 0x03900000,
        'PSHOLD': 0x0c264000,
        'IMEM': 0x146aa000,
        'RPMh RSC': 0x18220000,
        'RPMh TCS': 0x18220d00,
        'RPMh cmd DB': 0x0c3f000c,
    },
}

BEGIN_NODE, END_NODE, PROP, NOP, END = 1, 2, 3, 4, 9


class FDT:
    def __init__(self, blob):
        magic, total, self.off_struct, self.off_strings, _, self.version, \
            _, _, _, _ = struct.unpack_from('>10I', blob, 0)
        assert magic == 0xd00dfeed, 'not a device tree'
        self.blob = blob
        self.total = total

    def u32(self, off):
        return struct.unpack_from('>I', self.blob, off)[0]

    def u64(self, off):
        return struct.unpack_from('>Q', self.blob, off)[0]

    def str(self, off):
        end = self.blob.index(b'\0', off)
        return self.blob[off:end].decode('latin-1')

    def walk(self):
        """Yield (depth, kind, name/propname, value_bytes_or_None)."""
        p = self.off_struct
        depth = 0
        while True:
            tok = self.u32(p)
            p += 4
            if tok == BEGIN_NODE:
                depth += 1
                end = self.blob.index(b'\0', p)
                name = self.blob[p:end].decode('latin-1')
                p = (end + 4) & ~3
                yield depth, 'node', name, None
            elif tok == END_NODE:
                depth -= 1
            elif tok == PROP:
                ln, nameoff = self.u32(p), self.u32(p + 4)
                val = self.blob[p + 8:p + 8 + ln]
                yield depth, 'prop', self.str(self.off_strings + nameoff), val
                p = (p + 8 + ln + 3) & ~3
            elif tok == NOP:
                continue
            else:
                break

    def cells(self, val, root_ac, root_sc):
        """Decode a reg-style property into (base, size) pairs."""
        out, i = [], 0
        while i + (root_ac + root_sc) * 4 <= len(val):
            base = int.from_bytes(val[i:i + root_ac * 4], 'big')
            size = int.from_bytes(val[i + root_ac * 4:i + (root_ac + root_sc) * 4], 'big')
            out.append((base, size))
            i += (root_ac + root_sc) * 4
        return out


def collect(fdt):
    nodes = []                  # (path, name, dict(prop -> bytes))
    stack = []
    cells = [(2, 2)]            # (ac, sc) per depth, inherited by children
    cur = None
    out = {'mem': [], 'rsvd': [], 'cpus': [], 'chosen': {}, 'interest': [], 'nodes': nodes}
    for depth, kind, name, val in fdt.walk():
        if kind == 'node':
            if depth == 1:
                stack = [name]
                cells = [(2, 2), (2, 2)]            # index 0 unused; 1 = root
            else:
                del stack[depth - 1:]
                stack.append(name)
                cells = cells[:depth]
                cells.append(cells[depth - 1])      # inherit the parent's
            cur = {'path': '/' + '/'.join([s for s in stack[1:] if s]), 'name': name, 'props': {}}
            nodes.append(cur)
            continue
        cur['props'][name] = val
        if name == '#address-cells' and len(val) == 4:
            cells[depth] = (int.from_bytes(val, 'big'), cells[depth][1])
        elif name == '#size-cells' and len(val) == 4:
            cells[depth] = (cells[depth][0], int.from_bytes(val, 'big'))
        leaf = cur['name'].split('@')[0]
        if leaf.startswith('qcom,'):
            leaf = leaf[5:]
        ac, sc = cells[depth - 1] if depth > 1 else cells[depth]   # reg describes the parent
        if depth == 2 and leaf == 'memory' and name == 'reg':
            out['mem'] = fdt.cells(val, ac, sc)
        elif depth == 3 and stack[1] == 'reserved-memory' and name == 'reg':
            out['rsvd'].append((cur['name'], *fdt.cells(val, ac, sc)[0]))
        elif depth == 3 and stack[1] == 'cpus' and leaf == 'cpu' and name == 'reg':
            out['cpus'].append(int.from_bytes(val[-4:], 'big'))
        elif depth == 2 and cur['name'] == 'chosen':
            out['chosen'][name] = val
        elif name == 'reg' and leaf in ('interrupt-controller', 'timer', 'spmi', 'ufshc',
                                        'ufsphy', 'ufsphy_mem', 'ssusb', 'dwc3', 'hsphy',
                                        'qusb2phy', 'ssphy', 'eud', 'msm-eud', 'pinctrl',
                                        'clock-controller', 'gcc', 'mailbox', 'msm-imem',
                                        'restart', 'rsc'):
            for base, size in fdt.cells(val, ac, sc):
                out['interest'].append((leaf, cur['name'], base, size))
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('fdt')
    ap.add_argument('--device', default='guacamole', choices=sorted(devices.DEVICES))
    args = ap.parse_args()

    blob = open(args.fdt, 'rb').read()
    fdt = FDT(blob)
    got = collect(fdt)
    dev = devices.get(args.device)
    mirror = MIRROR[args.device]
    model = next((n['props'].get('model', b'').rstrip(b'\0').decode('latin-1')
                  for n in got['nodes'] if n['path'] == ''), '?')
    compat = next((n['props'].get('compatible', b'') for n in got['nodes'] if n['path'] == ''), b'')

    print(f'FDT {args.fdt}: {fdt.total} bytes, version {fdt.version}')
    print(f'model      {model}')
    print(f'compatible {" ".join(s.decode() for s in compat.split(b"\0") if s)}')
    print()
    print('memory banks:')
    for base, size in got['mem']:
        print(f'  {base:#014x} + {size:#014x}   ({(base + size) / 2**30:.1f} GiB end)')
    print('reserved-memory:')
    for name, base, size in got['rsvd']:
        mark = '  <-- framebuffer' if 'splash' in name else ''
        print(f'  {name:<24} {base:#014x} + {size:#014x}{mark}')
    print(f'cpus: {len(got["cpus"])} regs ' + ' '.join(f'{r:03x}' for r in got['cpus']))
    print('MMIO:')
    for leaf, name, base, size in got['interest']:
        print(f'  {name:<28} {base:#014x} + {size:#010x}')
    if got['chosen']:
        print('chosen:', {k: v.hex() if len(v) <= 8 else f'<{len(v)} bytes>'
                          for k, v in got['chosen'].items()})

    # --- checks ---------------------------------------------------------
    def fmt(v):
        return f'{v:#x}' if isinstance(v, int) else str(v)

    checks = []

    def check(label, found, want):
        checks.append((label, fmt(found), fmt(want), found == want))

    # framebuffer region
    fb = next(((b, s) for n, b, s in got['rsvd'] if 'splash' in n), None)
    check('framebuffer base', fb[0] if fb else None, dev['fb'])
    check('framebuffer size', fb[1] if fb else None, dev['fb_size'])
    # memory banks
    low = next(((b, s) for b, s in got['mem'] if b < (1 << 32)), None)
    high = next(((b, s) for b, s in got['mem'] if b >= (1 << 32)), None)
    check('low bank base', low[0] if low else None, 0x80000000)
    if high:
        check('high bank base', high[0], dev['high_phys_base'])
        check('high bank size', high[1], dev['high_mem_size'])
    # cpus
    check('cpu regs', ','.join(f'{r:03x}' for r in got['cpus']),
          ','.join(f'{r:03x}' for r in dev['cpu_regs']))
    # GIC + timer + ufs + spmi + usb from the interest list
    by = {}
    for leaf, name, base, size in got['interest']:
        by.setdefault(leaf, []).append((base, size))

    def first_in(leaf, lo, hi):
        for base, size in by.get(leaf, []):
            if lo <= base < hi:
                return base
        return None

    check('gicd base', by['interrupt-controller'][0][0] if 'interrupt-controller' in by else None, dev['gicd'])
    check('gicr base', by['interrupt-controller'][1][0] if len(by.get('interrupt-controller', [])) > 1 else None, dev['gicr'])
    check('ufs base', by['ufshc'][0][0] if 'ufshc' in by else None, dev['ufs'])
    # arm,armv8-timer interrupts: sec phys, phys, virt, hyp; CNTV = PPI 16 + n
    timer = next((n for n in got['nodes'] if n['props'].get('compatible', b'').startswith(b'arm,armv8-timer')), None)
    vt = None
    if timer and len(timer['props'].get('interrupts', b'')) >= 36:
        vt = 16 + int.from_bytes(timer['props']['interrupts'][28:32], 'big')
    check('vtimer intid', vt, dev['vtimer_intid'])
    check('spmi core', first_in('spmi', 0x0c000000, 0x0d000000), mirror['SPMI core'])
    check('dwc3 base', first_in('dwc3', 0x0a000000, 0x0b000000), mirror['USB DWC3'])
    check('hs phy base', first_in('hsphy', 0x08000000, 0x0a000000), mirror['USB HS PHY'])
    check('qmp phy base', first_in('ssphy', 0x08000000, 0x0a000000), mirror['USB QMP PHY'])
    check('tlmm base', first_in('pinctrl', 0x02000000, 0x10000000), mirror['TLMM'])
    check('gcc base', first_in('gcc', 0x00100000, 0x00200000) or
          first_in('clock-controller', 0x00100000, 0x00200000), mirror['USB GCC'])
    check('ufs phy base', first_in('ufsphy_mem', 0x01000000, 0x02000000) or
          first_in('ufsphy', 0x01000000, 0x02000000), mirror.get('UFS PHY', 0x01d87000))
    check('imem base', first_in('msm-imem', 0, 0xffffffff), mirror['IMEM'])
    check('pshold base', first_in('restart', 0x0c000000, 0x0d000000), mirror['PSHOLD'])
    # SM8150 lists the apps RSC as mailbox regs; SM8250 as rsc@18200000 with
    # one reg per DRV, qcom,drv-id and qcom,tcs-offset.
    rsc = next((n for n in got['nodes'] if n['name'].startswith('rsc@182')
                and 'qcom,drv-id' in n['props']), None)
    if rsc:
        drvs = [b for leaf, name, b, s in got['interest'] if name == rsc['name']]
        drv = int.from_bytes(rsc['props']['qcom,drv-id'], 'big')
        tcs_off = int.from_bytes(rsc['props'].get('qcom,tcs-offset', b''), 'big')
        rsc_base = drvs[drv] if drv < len(drvs) else None
        check('rpmh rsc', rsc_base, mirror['RPMh RSC'])
        check('rpmh tcs', rsc_base + tcs_off if rsc_base is not None else None, mirror['RPMh TCS'])
    else:
        check('rpmh rsc', first_in('mailbox', 0x18200000, 0x18300000), mirror['RPMh RSC'])
        check('rpmh tcs', next((b for b, s in by.get('mailbox', []) if 0x18200000 <= b < 0x18300000 and b != mirror['RPMh RSC']), None),
              mirror['RPMh TCS'])

    print()
    bad = 0
    for label, found, want, ok in checks:
        print(f'{"ok " if ok else "BAD"} {label:<20} found {found:<28} want {want}')
        bad += 0 if ok else 1
    # touch bus (only report presence)
    bus = mirror.get('Touch bus')
    touch = [n for n in got['nodes'] if bus and n['name'].startswith(bus)]
    if touch:
        print(f'ok  touch bus            found {touch[0]["path"]}')
    print(f'\n{len(checks) - bad}/{len(checks)} match')
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
