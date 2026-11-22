"""amp-dt 0.1's UI in digiemu on the core + digihealth + DN OVERDRIVE + AMP+ build (the mod laid over the
resumed stock snapshot, as test_env.py). Screens to ui_*.png; the settings read from amp_curve/amp_sync."""
import sys, os, json, struct
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from harness import Plan, run, HERE
import test_env_load as TL
TAG = 'ampdn'
MAP = TL.MAP
P = Plan()
def rd(tag): P.at(0, 'read', tag)
P.tap('AMP'); P.at(100, 'snap', 'ui_1_amp_stock.png'); rd('amp')
P.at(1, 'press', 'FUNC'); P.at(200, 'snap', 'ui_2_func_held.png'); rd('func')
P.at(1, 'turn', 'A', 1); P.at(150, 'snap', 'ui_3_func_a1.png'); rd('A x1')
P.at(1, 'turn', 'A', 1); P.at(3, 'wait'); P.at(1, 'turn', 'A', 1); P.at(150, 'wait'); rd('A x3')
P.at(1, 'turn', 'B', 1); P.at(150, 'snap', 'ui_4_func_sync.png'); rd('B right')
P.at(1, 'release', 'FUNC'); P.at(300, 'snap', 'ui_5_picture.png'); rd('released')
for i in range(8): P.at(1, 'turn', 'B', -4); P.at(40, 'wait')
P.at(300, 'snap', 'ui_6_hold_down.png'); rd('B alone')
P.at(1, 'press', 'FUNC'); P.at(100, 'wait'); P.at(1, 'turn', 'D', 4); P.at(150, 'wait'); P.at(1, 'turn', 'D', 4); P.at(150, 'wait')
P.at(1, 'release', 'FUNC'); P.at(300, 'snap', 'ui_7_dnod_too.png'); rd('dnod')
P.at(1, 'press', 'FUNC'); P.at(100, 'wait'); P.at(1, 'turn', 'A', -1); P.at(150, 'wait'); P.at(1, 'turn', 'A', -1); P.at(150, 'wait')
P.at(1, 'turn', 'A', -1); P.at(150, 'wait'); P.at(1, 'turn', 'A', -1); P.at(150, 'wait'); P.at(1, 'turn', 'B', -4); P.at(150, 'wait')
P.at(1, 'release', 'FUNC'); P.at(300, 'snap', 'ui_8_back_to_stock.png'); rd('back')
P.tap('FLTR'); P.at(1, 'press', 'FUNC'); P.at(100, 'wait'); P.at(1, 'turn', 'A', 1); P.at(150, 'wait'); P.at(1, 'release', 'FUNC'); P.at(200, 'wait'); rd('fltr')
R = {}
def read(uc, st, tag):
    g = lambda k, n=8: list(uc.mem_read(MAP[k], n))
    R[tag] = dict(curve=g('amp_curve'), sync=g('amp_sync'), custom=g('amp_custom'), dn=g('dn_type'),
                  page=uc.mem_read(0x4197c6bb, 1)[0], atk_hold=struct.unpack('>hh', uc.mem_read(0x80002760 + 94, 4)))
    print('%-10s' % tag, R[tag], flush=True)
st = run(P, TL.on_start, {'read': read})
fails = []
def need(c, w): print(('  ok   ' if c else '  FAIL ') + w); c or fails.append(w)
need(not st['E'].error, 'no fault')
need(R['amp']['curve'][0] == 0 and R['amp']['page'] == 3, 'AMP page, track 1 on STK')
need(R['A x1']['curve'][0] == 1, 'FUNC + A: a detent steps to LIN (%d)' % R['A x1']['curve'][0])
need(R['A x3']['curve'][0] == 3, 'then a detent a step: LOG after three (%d)' % R['A x3']['curve'][0])
need(R['B right']['sync'][0] == 1 and R['B right']['custom'][0] == 1, 'FUNC + B right: SYNC, and the track runs AMP+ (%s)' % R['B right'])
need(R['B right']['atk_hold'] == R['func']['atk_hold'], 'A and B keep their values under FUNC (%s)' % (R['B right']['atk_hold'],))
need(R['B alone']['atk_hold'][1] != R['released']['atk_hold'][1], 'B alone turns HOLD as stock (%s -> %s)' % (R['released']['atk_hold'][1], R['B alone']['atk_hold'][1]))
need(R['dnod']['dn'][0] != R['B alone']['dn'][0] and R['dnod']['curve'][0] == R['B alone']['curve'][0], 'FUNC + D still picks the DN OVERDRIVE type (%d -> %d), the curve stays' % (R['B alone']['dn'][0], R['dnod']['dn'][0]))
need(R['back']['curve'][0] == 0 and R['back']['sync'][0] == 0 and R['back']['custom'][0] == 0, 'back to STK + FREE: the stock code again (%s)' % R['back'])
need(R['fltr']['curve'][0] == 0, 'FUNC + A on the FLTR page leaves the curve alone')
print('\n' + ('ALL UI CHECKS PASSED' if not fails else 'FAILED: %d' % len(fails)))
