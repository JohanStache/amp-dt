"""amp-dt 0.1's cost: cycles a block (digiemu's ColdFire V4 model, zero-wait memory) for the stock envelope
(stock image, 0x400716c0) and AMP+ (all eight tracks on one setting), over 300 blocks from a trig on every
track (ATK 10, HOLD 10, DEC 40: an attack, a hold and a decay)."""
import sys, os, json, struct, types
from unicorn import Uc, UC_ARCH_M68K, UC_MODE_BIG_ENDIAN
from unicorn.m68k_const import *
from emu.cftiming import CycleClock
HERE = os.path.dirname(os.path.abspath(__file__))
STOCK = open(os.path.join(HERE, '..', 'firmware/dt1-1.54-f78ba80f/sections/section_3_MAIN_OS.bin'), 'rb').read()
MOD = open(os.path.join(HERE, 'main_amp.bin'), 'rb').read()
MAP = {k: int(v, 16) for k, v in json.load(open(os.path.join(HERE, 'amp.map.json'))).items() if isinstance(v, str) and v.startswith('0x')}
BASE, STRUCT, BLOCKS, REC, RET, STUB = 0x40000400, 0x46000000, 0x80001a18, 0x46001000, 0x47f00000, 0x47f00100
def cycles(img, fn, curve=0, sync=0, nblk=300, hold=10):
    uc = Uc(UC_ARCH_M68K, UC_MODE_BIG_ENDIAN); uc.ctl_set_cpu_model(UC_CPU_M68K_CFV4E)
    uc.mem_map(0x40000000, 0x08000000); uc.mem_map(0x80000000, 0x20000)
    uc.mem_write(BASE, img); uc.mem_write(RET, b'\x4e\x71')
    uc.mem_write(0x4020df10, struct.pack('>i', 11760))
    if img is MOD:
        w = MAP['__run_words']; uc.mem_write(MAP['__run_start'], MOD[MAP['__run_load'] - BASE: MAP['__run_load'] - BASE + 4 * w])
        uc.mem_write(MAP['__bss_start'], bytes(4 * MAP['__bss_words']))
        uc.mem_write(MAP['amp_curve'], bytes([curve] * 8)); uc.mem_write(MAP['amp_sync'], bytes([sync] * 8))
        uc.mem_write(MAP['amp_custom'], bytes([int(curve != 0 or sync != 0)] * 8))
    uc.mem_write(0x4199ed64, bytes(64))
    for t in range(8): uc.mem_write(STRUCT + 106 * t + 94, struct.pack('>hhh', 10 << 8, hold << 8, 40 << 8))
    m = types.SimpleNamespace(uc=uc, raise_vector=lambda *a, **k: None)
    clk = CycleClock(m, exclude=((STUB, STUB + 16),))
    for b in range(nblk):
        uc.mem_write(BLOCKS, struct.pack('>256i', *([0x30000000] * 256)))
        uc.mem_write(REC, bytes([10] * 8 + [hold] * 8 + [40] * 8 + [0xff if b == 0 else 0, 0]))
        uc.mem_write(STRUCT - 16, struct.pack('>III', RET, BLOCKS, REC))
        uc.mem_write(STUB, bytes.fromhex('a93c000000a0') + b'\x4e\xf9' + struct.pack('>I', fn))
        uc.reg_write(UC_M68K_REG_SR, 0x2700); uc.reg_write(UC_M68K_REG_A7, STRUCT - 16); uc.reg_write(UC_M68K_REG_A2, STRUCT)
        uc.emu_start(STUB, RET, count=2_000_000)
    r = clk.report()
    return r['cycles'] / nblk, r['decode_mismatches'], struct.unpack('>256i', uc.mem_read(BLOCKS, 1024))[0]
s = cycles(STOCK, 0x400716c0)
if len(sys.argv) > 1:
    for label, c, sy, h in (('stock, NOTE hold', -1, 0, 127), ('LIN, NOTE hold (no ramp)', 1, 0, 127)):
        r = cycles(STOCK, 0x400716c0, hold=h) if c < 0 else cycles(MOD, MAP['amp_env'], c, sy, hold=h)
        print(label, round(r[0]))
    sys.exit()
print('%-26s %6.0f cycles/block  (mismatches %d)' % ('stock envelope', s[0], s[1]))
for label, c, sy in (('AMP+, all STK + FREE', 0, 0), ('AMP+, all LIN', 1, 0), ('AMP+, all EXP', 2, 0), ('AMP+, all LOG', 3, 0),
                     ('AMP+, all PNCH', 4, 0), ('AMP+, all STK + SYNC', 0, 1), ('AMP+, all PNCH + SYNC', 4, 1)):
    r = cycles(MOD, MAP['amp_env'], c, sy)
    print('%-26s %6.0f cycles/block  %+5.0f vs stock  (mismatches %d)' % (label, r[0], r[0] - s[0], r[1]))
