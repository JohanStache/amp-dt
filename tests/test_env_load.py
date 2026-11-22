"""amp-dt 0.1: the envelope on the real build in digiemu. Every track's block is fed a constant 0.5 at the
envelope's entry, so out / 0.5 is its gain, sample by sample. Each track gets a curve and hold (amp_curve,
amp_sync written directly), the same ATK/HOLD/DEC (in the record and the render's 8.8 words), a trig at
block 10 and, for the NOTE track, the trig's end at block 150. The gains are checked against a model of
each curve (and the stock's arithmetic for STK)."""
import sys, os, json, struct, math
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from harness import Plan, run, HERE
from unicorn import UC_HOOK_CODE
from unicorn.m68k_const import UC_M68K_REG_A7, UC_M68K_REG_A2
TAG = 'ampdn'
MAP = {k: int(v, 16) for k, v in json.load(open(os.path.join(HERE, TAG + '.map.json'))).items() if isinstance(v, str) and v.startswith('0x')}
RET = 0x4007807e
NBLK = 0
MODE = 'ui'
SWITCH = {25: [0, 4, 3, 1, 2, 0, 1, 4], 300: [0, 3, 4, 2, 1, 0, 1, 4]}   # block: the curves from then on
TRIG, OFF = 10, 150
#            curve sync  atk hold dec
CASES = [  (0, 0, 24, 10, 24),      # STK free: the stock code
           (1, 0, 24, 10, 24),      # LIN
           (2, 0, 24, 10, 24),      # EXP
           (3, 0, 24, 10, 24),      # LOG
           (4, 0, 24, 10, 24),      # PNCH
           (0, 1, 24, 4, 24),       # STK + SYNC 1/64
           (1, 1, 24, 20, 24),      # LIN + SYNC 1/32
           (4, 0, 24, 127, 24) ]    # PNCH, NOTE: hold until the trig ends
DC = 0x40000000
G = {t: [] for t in range(8)}
ST = {'blk': 0, 'cur': None}
def load_mod(uc):
    """the mod build over the resumed stock snapshot: the bytes that differ from stock (the sites and the
    appended mod payload), then core's boot copy of .run and a cleared .bss"""
    stock = open(os.path.join(os.path.dirname(HERE), 'firmware/dt1-1.54-f78ba80f/sections/section_3_MAIN_OS.bin'), 'rb').read()
    mod = open(os.path.join(HERE, 'main_%s.bin' % TAG), 'rb').read()
    n = 0; i = 0
    while i < len(mod):
        if i >= len(stock) or mod[i] != stock[i]:
            j = i
            while j < len(mod) and (j >= len(stock) or mod[j] != stock[j]): j += 1
            uc.mem_write(0x40000400 + i, mod[i:j]); n += j - i; i = j
        else: i += 1
    words = MAP['__run_words']
    run = mod[MAP['__run_load'] - 0x40000400: MAP['__run_load'] - 0x40000400 + 4 * words]
    lo = MAP['__run_start'] & ~0xfffff
    try: uc.mem_map(lo, 0x100000)
    except Exception as e: print('map', e)
    uc.mem_write(MAP['__run_start'], run)
    uc.mem_write(MAP['__bss_start'], bytes(4 * MAP['__bss_words']))
    uc.ctl_flush_tb()
    print('mod loaded:', n, 'bytes changed, .run', len(run), flush=True)
def every(uc, st):
    if ST['blk'] >= NBLK: st['stop'] = 1

def on_start(uc, st):
    load_mod(uc)
