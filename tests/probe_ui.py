"""AMP+ UI: frames while FUNC + A steps through the curves, and the cost of amp_draw / amp_tick / the stock frame."""
import sys, os, struct
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from harness import Plan, run, HERE, png
import test_env_load as TL
from unicorn import UC_HOOK_CODE
from unicorn.m68k_const import UC_M68K_REG_A7
MAP = TL.MAP
P = Plan()
P.tap('AMP'); P.at(100, 'wait')
P.at(1, 'press', 'FUNC'); P.at(60, 'wait')
for i in range(4):
    P.at(1, 'turn', 'A', 1)
    for k in range(6): P.at(3, 'frame', 'f%d_%d' % (i, k))
    P.at(40, 'wait')
P.at(1, 'release', 'FUNC')
for k in range(8): P.at(3, 'frame', 'rel_%d' % k)
P.at(100, 'wait')
FR = {}
def frame(uc, st, tag):
    E = st['E']; FR[tag] = (bytes(E.fb), list(uc.mem_read(MAP['amp_curve'], 1)))
C = {'on': None, 'n': {}, 'calls': {}, 'ret': None}
def on_start(uc, st):
    TL.on_start(uc, st)
    for name in ('amp_draw', 'amp_tick'):
        def enter(u, a, s, d, name=name):
            C['on'] = name; C['ret'] = struct.unpack('>I', u.mem_read(u.reg_read(UC_M68K_REG_A7), 4))[0]
            C['calls'][name] = C['calls'].get(name, 0) + 1
        uc.hook_add(UC_HOOK_CODE, enter, begin=MAP[name], end=MAP[name])
    uc.ctl_flush_tb()
st = run(P, on_start, {'frame': frame})
for k in C['n']: print(k, 'calls', C['calls'][k], 'instructions/call', C['n'][k] // max(1, C['calls'][k]))
prev = None
for tag in sorted(FR, key=lambda t: list(FR).index(t)):
    fb, cur = FR[tag]
    ch = 'same' if prev == fb else 'CHANGED'
    print(tag, 'curve', cur, ch); prev = fb
    png(os.path.join(HERE, 'pu_' + tag + '.png'), fb)
