"""amp-dt 0.1's envelope as float: the gain a sample, for one trig at sample 0 (the block after the trig's)."""
import re, math, os
T = {}
src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'tabs.h')).read()
for name in ('att_len', 'hold_len', 'dec_len', 'dec_coef'):
    m = re.search(name + r'\[128\] = \{([^}]*)\}', src)
    T[name] = [int(x.strip().rstrip('u')) for x in m.group(1).split(',') if x.strip()]
SYNC_K = [3, 4, 6, 8, 9, 12, 16, 18, 24, 32, 36, 48, 64, 72, 96, 192]
def att(c, p):
    q = 1 - p
    return p * p if c == 2 else 1 - q * q if c == 3 else 1 - q ** 4 if c == 4 else p
def dec(c, p):
    q = 1 - p
    return q ** 8 if c == 2 else 1 - p * p if c == 3 else 1 - p ** 4 if c == 4 else q
def gains(c, sync, a, h, d, n, tempo=11760, off_at=None):
    """-> n gains from the trig, and the stage at each sample"""
    out, stage = [], []
    L = T['att_len'][a]
    if a == 0: L = 0
    i = 0
    if c == 0 and not sync:     # the stock: starts at inc/2, + inc a sample, until it saturates
        inc = 1 / L if L else 1
        g = inc / 2
        while L and g < 1 and i < n:
            out.append(g); stage.append(2); g += inc; i += 1
    else:
        for k in range(1, L + 1):        # ramps reach the curve's point at the end of each piece
            if i >= n: break
            out.append(att(c, k / L)); stage.append(2); i += 1
    H = None if h >= 127 else (7200000 * SYNC_K[(h * 16) // 127] // tempo if sync else T['hold_len'][h])
    k = 0
    while i < n and (H is None or k < H):
        if off_at is not None and H is None and i >= off_at: break
        out.append(1.0); stage.append(1); i += 1; k += 1
    D = T['dec_len'][d]; cc = T['dec_coef'][d] / 2**31
    g = 1.0; k = 0
    while i < n:
        if c == 0:
            out.append(g); g *= cc
        else:
            k += 1
            out.append(dec(c, min(1.0, k / D)) if k <= D else 0.0)
        stage.append(0); i += 1
    return out, stage
