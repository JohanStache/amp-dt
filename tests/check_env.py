"""Checks test_env.py's three runs: base (each track's curve against the model), stock (the stock firmware:
track 1, STK, must equal the mod's sample for sample), switch (curves changed mid-attack and mid-decay:
the largest step at a change against the largest step anywhere else in the envelope)."""
import pickle, sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from model import gains
D = sys.argv[1]
L = {m: pickle.load(open(os.path.join(D, 'env_ampdn_%s.pkl' % m), 'rb')) for m in ('base', 'stock', 'switch')}
names = ['STK', 'LIN', 'EXP', 'LOG', 'PNCH']
fails = []
def need(c, w): print(('  ok   ' if c else '  FAIL ') + w); c or fails.append(w)
R = L['base']; G, CASES, TRIG, OFF = R['G'], R['CASES'], R['TRIG'], R['OFF']
start = (TRIG + 1) * 32
for t, (c, sy, a, h, d) in enumerate(CASES):
    got = G[t][start:]
    exp, stg = gains(c, sy, a, h, d, len(got), off_at=(OFF + 1) * 32 - start if h == 127 else None)
    err = max(abs(x - y) for x, y in zip(got, exp))
    need(err < 5e-3 and max(G[t][:start]) == 0, 'track %d, %s %s (A %d, H %s, D %d): the gain follows the model within 0.5%% (worst %.1e: 0.67 ms straight pieces), silent before the trig'
         % (t + 1, names[c], 'SYNC' if sy else 'FREE', a, 'NOTE' if h == 127 else h, d, err))
S = L['stock']['G']
need(S[0] == G[0], 'track 1 on STK + FREE equals the stock firmware sample for sample (%d samples)' % len(S[0]))
need(all(S[t] == S[0] for t in range(5)), 'stock firmware: tracks 1-5 (the same knobs) alike, as the harness meant')
W = L['switch']['G']
for t in (1, 2, 3, 4, 7):
    g = W[t]
    jumps = {b: abs(g[b * 32 + 32] - g[b * 32 + 31]) for b in (25, 300)}   # the change lands on the block after
    rest = max(abs(g[i] - g[i - 1]) for i in range(start + 1, len(g)) if i // 32 - 1 not in (25, 300))
    need(max(jumps.values()) <= max(rest, 1e-3) * 1.05,
         'track %d: changing the curve mid-attack (%.4f) and mid-decay (%.4f) steps no more than the envelope ever does (%.4f)'
         % (t + 1, jumps[25], jumps[300], rest))
print('\n' + ('ALL ENVELOPE CHECKS PASSED' if not fails else 'FAILED: %d' % len(fails)))
