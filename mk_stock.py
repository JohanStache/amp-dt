"""usage: mk_stock.py env.dis  (objdump -D -b binary -m m68k:cfv4e --adjust-vma=0x40000400 of the stock main
section, cut to 0x400716c0-0x40071c20). Reassemble the OS 1.54 AMP envelope (0x400716c0-0x40071870) as gas source, with labels for its branches,
and the amp-dt dispatch at the per-track loop head (0x400716da)."""
import re, sys
lines = [l for l in open(sys.argv[1] if len(sys.argv) > 1 else 'env.dis') if re.match(r'^4007[0-9a-f]{4}:', l)]
body = []
for l in lines:
    a = int(l[:8], 16)
    if a > 0x40071870: break
    parts = l.rstrip('\n').split('\t')
    hexb, ins = parts[1].strip(), parts[2].strip()
    body.append((a, hexb, ins))
targets = set()
for a, h, ins in body:
    m = re.match(r'^(b\w+|bra\w*)\s+0x([0-9a-f]+)$', ins)
    if m: targets.add(int(m.group(2), 16))
out = []
for a, h, ins in body:
    if a in targets or a == 0x400716da:
        out.append('L_%08x:' % a)
    if a == 0x400716da:
        out.append('        AMP_DISPATCH')
    m = re.match(r'^(b\w+|bra\w*)\s+0x([0-9a-f]+)$', ins)
    if m:
        op = m.group(1); t = int(m.group(2), 16)
        assert 0x400716c0 <= t <= 0x40071870, hex(t)
        size = {4: 's', 6: 'w'}[len(h.replace(' ', '')) // 2 + 2] if False else None
        nb = len(h.replace(' ', '')) // 2
        base = op[:-1] if op[-1] in 'sw' and op not in ('bls',) else op
        # objdump writes bnes/beqs/bras (short), bnew/braw (word); bls/bcs etc keep their form
        if op.endswith('s') and nb == 2: base, sz = op[:-1], 's'
        elif op.endswith('w') and nb == 4: base, sz = op[:-1], 'w'
        else: base, sz = op, ('s' if nb == 2 else 'w')
        ins = '%s.%s L_%08x' % (base, sz, t)
    out.append('        %-40s | %08x %s' % (ins, a, h))
open('stock_env.inc', 'w').write('\n'.join(out) + '\n')
print(len(body), 'instructions,', len(targets), 'labels')
