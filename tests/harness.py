"""Headless digiemu harness for amp-dt probes. usage: from harness import run; run(plan_fn, syx=None)"""
import os, sys, struct, types, time, zlib
HERE = os.path.dirname(os.path.abspath(__file__))
D = os.path.expanduser('~/mnt/digiemu/claude-work')
FW = D + '/firmware/dt1-1.54-f78ba80f'
def setup(syx=None, main=None):
    syx = syx or FW + '/Digitakt_OS1.54.syx'
    os.environ.update({"DT2_SYX": syx, "DT2_SECTIONS": FW + "/sections", "DT2_SNAPSHOTS": FW + "/snapshots",
        "DT2_PLUSDRIVE": FW + "/plusdrive.img", "DT2_MAIN_IMG": main or FW + "/sections/section_3_MAIN_OS.bin",
        "DT2_DEVICES": FW + "/devices"})
    os.chdir(FW)
    _tk = types.ModuleType("tkinter"); _tk.Frame = type("Frame", (), {}); _tk.Tk = type("Tk", (), {})
    sys.modules["tkinter"] = _tk
    for n in ("ttk", "messagebox", "filedialog", "font"): sys.modules["tkinter." + n] = types.ModuleType("tkinter." + n)
    sys.modules['rtmidi'] = types.ModuleType('rtmidi')
    return syx
def png(path, fb):
    def ch(t_, d): return struct.pack(">I", len(d)) + t_ + d + struct.pack(">I", zlib.crc32(t_ + d) & 0xffffffff)
    big = []
    for y in range(64):
        line = b"".join(bytes([0 if fb[y * 128 + x] else 255] * 3) * 4 for x in range(128)); big += [b"\0" + line] * 4
    open(path, "wb").write(b"\x89PNG\r\n\x1a\n" + ch(b"IHDR", struct.pack(">IIBBBBB", 512, 256, 8, 2, 0, 0, 0)) + ch(b"IDAT", zlib.compress(b"".join(big))) + ch(b"IEND", b""))
class Plan:
    def __init__(s): s.items = []; s.t = 60
    def at(s, dt, *a): s.t += dt; s.items.append((s.t, a))
    def tap(s, k): s.at(1, 'press', k); s.at(25, 'release', k); s.at(300, 'wait')
def run(plan, on_start=None, actions=None, syx=None, main=None, every=None):
    syx = setup(syx, main)
    import emu.gui as G
    SNAP = FW + '/snapshots/Digitakt_OS1.54/gui.snap'
    st = {'n': 0}
    END = plan.t + 20
    _spin = G.spin
    def spin(m, pc, *a, **kw):
        uc = m.uc; n = st['n']
        if n == 0 and on_start: on_start(uc, st)
        if n == 40:
            names = {v: c for c, v in (E.button_names or {}).items()}
            names.update({v: c for c, v in (getattr(E.device, 'labels', None) or {}).items()})
            st['names'] = names; st['enc'] = {v: c for c, v in (E.encoder_names or {}).items()}; print('ENC', E.encoder_names, flush=True)
        for when, act in plan.items:
            if when != n: continue
            k = act[0]
            if k in ('press', 'release'): E.inbox.append((k, st['names'][act[1]], 0))
            elif k == 'turn': E.inbox.append(('encoder', st['enc'][act[1]], act[2]))
            elif k == 'snap': png(os.path.join(HERE, act[1]), E.fb)
            elif actions and k in actions: actions[k](uc, st, *act[1:])
        if every: every(uc, st)
        st['n'] += 1
        r = _spin(m, pc, *a, **kw)
        if st['n'] >= END or st.get('stop'): E.stop_flag.set()
        return r
    G.spin = spin
    E = G.Emulator(SNAP, syx=syx, realtime=False, audio=True)
    st['E'] = E
    t0 = time.time(); E.run()
    print('error:', E.error, 'steps', st['n'], '%.0fs' % (time.time() - t0), flush=True)
    return st
