/* SPDX-License-Identifier: GPL-2.0-or-later */
/* amp-dt 0.2, the render side: one track's AMP envelope for a block, for a track with a curve other than
 * the stock one or with a synced hold (amp.s calls it from the stock envelope's per-track loop).
 *
 * The state is the stock's, so what reads it (core's fw_amp_level, byte-dt) still works:
 *   st[0] the phase: 2 attack, 1 hold, 0 decay;
 *   st[1] the value: in attack and decay the level, negated Q31 (0x80000000 full, 0 silent); in hold the
 *         samples held so far.
 * A shaped stage also keeps how far through it the track is, amp_ph[t] (Q31, 0 to END), and follows the
 * knobs' full 8.8 values from the render's records (amp_sptr), so an LFO or a slide on ATK, HOLD or DEC moves
 * the time smoothly. Each stage is drawn as straight pieces between its curve's points at most a block
 * (32 samples, 0.67 ms) apart, so a curve costs two evaluations a block, and a multiply a sample.
 *
 * Every curve takes the stock's times: the attack is the stock attack's length, the decay ends (at silence)
 * where the stock decay is 40 dB down. Curves (amp_curve):
 *   0 STK   the stock shapes (only here with a synced hold): linear attack, exponential decay
 *   1 LIN   linear attack, linear decay
 *   2 EXP   attack p^2 (swells in), decay (1-p)^8 (falls at once, much faster than the stock): snappy
 *   3 LOG   attack 1-(1-p)^2 (quick, rounded), decay 1-p^2 (stays up, then falls): round, full
 *   4 PNCH  attack 1-(1-p)^4 (fastest), decay 1-p^4 (full body, then a quick fall): punchy, gated
 * Hold (amp_sync): 0 FREE the stock hold; 1 SYNC the knob picks a note value at the project tempo
 * (0x4020df10, BPM x 120). HOLD 127 is the stock's NOTE (until the trig ends) either way. */
#include <stdint.h>
#include "tabs.h"

#define NCURVES 5
#define END     0x7fffffff
#define FULL    0x80000000u
#define TEMPO   (*(volatile int32_t *)0x4020df10)    /* OS 1.54: BPM x 120 */
#define REC     106                                   /* the render's track record */
#define OFF_ATK 94
#define OFF_HLD 96
#define OFF_DEC 98

extern volatile uint32_t amp_sptr, amp_blk;
extern int32_t amp_ramp(int32_t *x, int32_t n, int32_t g, int32_t step);
extern int32_t amp_expdec(int32_t *x, int32_t n, int32_t g, int32_t c);

volatile uint8_t amp_curve[8];          /* the UI's: 0-4 */
volatile uint8_t amp_sync[8];           /* the UI's: 0 FREE, 1 SYNC */
static uint32_t amp_ph[8];
static uint8_t last_curve[8];
static uint32_t last_blk[8];

/* the sixteen note values, in twelfths of a sixteenth: 1/64 1/32T 1/32 1/16T 1/32. 1/16 1/8T 1/16. 1/8
 * 1/4T 1/8. 1/4 1/2T 1/4. 1/2 1 bar */
const uint8_t amp_sync_k[16] = { 3, 4, 6, 8, 9, 12, 16, 18, 24, 32, 36, 48, 64, 72, 96, 192 };

static int32_t sq(int32_t x) { return (x * x) >> 15; }

/* Q15 gains, p in Q15 (0-32768) */
static int32_t att_shape(int c, int32_t p)
{
    int32_t q = 32768 - p;
    switch (c) {
    case 2: return sq(p);
    case 3: return 32768 - sq(q);
    case 4: return 32768 - sq(sq(q));
    default: return p;
    }
}

static int32_t dec_shape(int c, int32_t p)
{
    int32_t q = 32768 - p;
    switch (c) {
    case 2: return sq(sq(sq(q)));
    case 3: return 32768 - sq(p);
    case 4: return 32768 - sq(sq(p));
    default: return q;
    }
}

static int32_t q31(int32_t g15)         /* Q15 0-32768 -> Q31, 32768 -> 0x7fffffff */
{
    if (g15 >= 32768) return END;
    if (g15 <= 0) return 0;
    return g15 << 16;
}

static int32_t p15(uint32_t ph) { return ph >= END ? 32768 : (int32_t)(ph >> 16); }

static int32_t gain_of(int32_t v)       /* the stock value (negated level) -> the gain, Q31 */
{
    if ((uint32_t)v == FULL) return END;
    return v > 0 ? 0 : -v;
}

/* a knob's length from its 8.8 value, between the table's neighbours */
static uint32_t interp(const uint32_t *t, int32_t w)
{
    int32_t i, f;
    uint32_t a, b;
    if (w <= 0) return t[0];
    if (w >= 127 << 8) return t[127];
    i = w >> 8; f = w & 255;
    a = t[i]; b = t[i + 1];
    if (b == 0xffffffffu) b = a * 4 > a ? a * 4 : a;     /* toward DEC 127 (no decay): up to 4 x */
    if (b >= a) return a + (((b - a) * (uint32_t)f) >> 8);    /* neighbours differ by < 2^24 */
    return a - (((a - b) * (uint32_t)f) >> 8);
}

/* the phase where curve c's stage gives gain g (Q31): from the stock (or another curve) to this one,
 * mid-stage, without a jump */
static uint32_t find_phase(int c, int attack, int32_t g)
{
    int32_t g15 = g >> 16, lo = 0, hi = 32768, k;
    for (k = 0; k < 15; k++) {
        int32_t mid = (lo + hi) >> 1;
        int32_t s = attack ? att_shape(c, mid) : dec_shape(c, mid);
        if (attack ? s < g15 : s > g15) lo = mid; else hi = mid;
    }
    return lo >= 32768 ? END : (uint32_t)lo << 16;
}

static uint32_t sync_len(int32_t hold)
{
    int32_t t = TEMPO;
    uint32_t k = amp_sync_k[(hold * 16) / 127 & 15];
    if (t < 120) t = 120;
    return (uint32_t)(7200000u * k) / (uint32_t)t;      /* 48 kHz x 60 x 120 / 4 per sixteenth / 12 */
}

/* n samples of a shaped stage from phase *ph at inc a sample (to END); returns the samples used.
 * A full block (n 32) needs no division: shifts. */
static int32_t shaped(int32_t *x, int32_t n, int c, int attack, uint32_t *ph, uint32_t inc, int32_t *gout)
{
    uint32_t p0 = *ph, p1, left = END - p0;
    int32_t k, g0, g1, d, step;
    if (inc == 0) inc = 1;
    if ((n == 32 ? left >> 5 : left / (uint32_t)n) < inc) {    /* left < inc n: the stage ends here */
        k = (int32_t)((left + inc - 1) / inc);
        if (k < 1) k = 1;
        if (k > n) k = n;
        p1 = END;
    } else {
        k = n;
        p1 = p0 + inc * (uint32_t)n;
    }
    g0 = q31(attack ? att_shape(c, p15(p0)) : dec_shape(c, p15(p0)));
    g1 = q31(attack ? att_shape(c, p15(p1)) : dec_shape(c, p15(p1)));
    d = g1 - g0;                        /* the step, toward zero, so the first sample stays within g0 */
    if (k == 32) step = d >= 0 ? d >> 5 : -((-d) >> 5);
    else step = d / k;
    amp_ramp(x, k, g1 - step * (k - 1), step);     /* the piece's last sample lands on g1 */
    *ph = p1;
    *gout = g1;
    return k;
}

/* END / len, kept per track and stage while len stays */
static uint32_t inc_len[8][2], inc_val[8][2];
static uint32_t inc_of(int32_t t, int s, uint32_t len)
{
    if (inc_len[t][s] != len) {
        inc_len[t][s] = len;
        inc_val[t][s] = END / (len ? len : 1);
    }
    return inc_val[t][s];
}

void amp_track(int32_t t, int32_t *blocks, const uint8_t *rec, volatile int32_t *st)
{
    int32_t *x = blocks + 32 * t;
    int32_t n = 32, k, g;
    int c = amp_curve[t] % NCURVES;
    int32_t atk_i = (int8_t)rec[t], hold_i = (int8_t)rec[8 + t], dec_i = (int8_t)rec[16 + t];
    int32_t w_atk = atk_i << 8, w_hld = hold_i << 8, w_dec = dec_i << 8;
    int trig = (rec[24] >> t) & 1, off = (rec[25] >> t) & 1;
    uint32_t sp = amp_sptr;

    if (sp) {                           /* the knobs' full values, a lock or an LFO's fraction included */
        w_atk = *(volatile int16_t *)(sp + REC * t + OFF_ATK);
        w_hld = *(volatile int16_t *)(sp + REC * t + OFF_HLD);
        w_dec = *(volatile int16_t *)(sp + REC * t + OFF_DEC);
    }
    /* a curve changed, or the stock ran this track last block: find where this curve is */
    if (c != last_curve[t] || last_blk[t] + 1 != amp_blk) {
        if (st[0] == 2 && (uint32_t)st[1] != FULL)
            amp_ph[t] = find_phase(c, 1, gain_of(st[1]));
        else if (st[0] == 0 && c)
            amp_ph[t] = find_phase(c, 0, gain_of(st[1]));
        last_curve[t] = (uint8_t)c;
    }
    last_blk[t] = amp_blk;

    while (n > 0) {
        if (st[0] == 2) {                                       /* attack */
            uint32_t len;
            if ((uint32_t)st[1] == FULL) { st[0] = 1; st[1] = 0; continue; }
            len = interp(att_len, w_atk);
            if (len == 0 || atk_i == 0) { st[1] = (int32_t)FULL; continue; }
            k = shaped(x, n, c, 1, &amp_ph[t], inc_of(t, 0, len), &g);
            st[1] = amp_ph[t] >= END ? (int32_t)FULL : -g;
            x += k; n -= k;
        } else if (st[0] == 1) {                                /* hold: the sound passes as it is */
            uint32_t thr, cnt = (uint32_t)st[1];
            if (hold_i == 127) {                                /* NOTE: until the trig ends */
                st[1] = (int32_t)(cnt + (uint32_t)n < cnt ? cnt : cnt + (uint32_t)n);
                break;
            }
            thr = amp_sync[t] ? sync_len(hold_i) : interp(hold_len, w_hld);
            if (cnt >= thr) { st[0] = 0; st[1] = (int32_t)FULL; amp_ph[t] = 0; continue; }
            k = thr - cnt < (uint32_t)n ? (int32_t)(thr - cnt) : n;
            st[1] = (int32_t)(cnt + (uint32_t)k);
            x += k; n -= k;
        } else {                                                /* decay */
            uint32_t len = interp(dec_len, w_dec);
            g = gain_of(st[1]);
            if (dec_i >= 127 || len == 0xffffffffu) {           /* DEC 127: no decay */
                amp_ramp(x, n, g, 0);
                break;
            }
            if (c == 0) {                                       /* the stock's shape */
                g = amp_expdec(x, n, g, (int32_t)dec_coef[dec_i & 127]);
                st[1] = -g;
                break;
            }
            if (g == 0 || amp_ph[t] >= END) {                   /* over: silence */
                for (k = 0; k < n; k++)
                    x[k] = 0;
                st[1] = 0;
                amp_ph[t] = END;
                break;
            }
            k = shaped(x, n, c, 0, &amp_ph[t], inc_of(t, 1, len), &g);
            st[1] = -g;
            x += k; n -= k;
        }
    }
    /* after the block, as the stock: a trig starts the attack, the trig's end ends a NOTE hold */
    if (trig) {
        amp_ph[t] = 0;
        st[1] = atk_i == 0 ? (int32_t)FULL : 0;
        st[0] = 2;
    } else if (off && hold_i == 127 && st[0] == 1) {
        st[1] = (int32_t)FULL;
        st[0] = 0;
        amp_ph[t] = 0;
    }
}
