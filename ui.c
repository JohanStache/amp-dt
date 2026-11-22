/* SPDX-License-Identifier: GPL-2.0-or-later */
/* amp-dt 0.2, the UI, on the AMP page:
 *   FUNC + A picks the active track's envelope curve: STK (stock), LIN, EXP, LOG, PNCH;
 *   FUNC + B sets its hold FREE (the stock's) or SYNC (HOLD picks a note value at the tempo).
 * A detent a step, drawn at once; A and B keep their values while FUNC is held.
 * While FUNC is held, the envelope's picture (knobs A-C) shows the curve's real shape with its name inverted
 * and the hold's mode under it (FREE, the note value or NOTE), and the title bar the times: the attack, the
 * hold and the decay in ms or s. A track on a curve or a synced hold keeps that picture (name not inverted);
 * a track on STK with a free hold keeps the stock picture.
 * The settings live in RAM (amp_curve, amp_sync), not yet saved with the sound: every track starts on STK and
 * FREE at power-on. */
#include <stdint.h>
#include "digitakt-mk1/core3.h"

typedef void (*rect_fn)(void *bmp, int x0, int y0, int x1, int y1, int colour);
typedef void (*text_fn)(void *bmp, const void *font, int x, int y, int maxlen, const char *fmt, ...);
#define FILLRECT  ((rect_fn)fw_fillrect)
#define TEXTF     ((text_fn)fw_textf)
#define FONT5     ((const void *)fw_font5)

#define UI_PAGE   (*(volatile uint8_t *)0x4197c6bb)   /* OS 1.54: 0 TRIG 1 SRC 2 FLTR 3 AMP 4 LFO */
#define TEMPO     (*(volatile int32_t *)0x4020df10)   /* BPM x 120 */
#define PAGE_AMP  3
#define KEY_FUNC  1
#define ENC_A     1
#define ENC_B     2
#define DETENT    4
#define COUNTS    (2 * DETENT)
#define IDLE      12
#define NCURVES   5
#define EV_ID(ev)    (*(int32_t *)((char *)(ev) + 12))
#define EV_FLAGS(ev) (*(uint32_t *)((char *)(ev) + 16))
#define EV_DELTA(ev) (*(int32_t *)((char *)(ev) + 16))

/* the envelope picture's place: x 19-97 (dnod-dt draws from 98), y 32-52 (y 0 the bottom row) */
#define GX0 19
#define GX1 97
#define GY0 32
#define GY1 52
#define BASE 34
#define TOP  50

extern volatile uint8_t amp_curve[8], amp_sync[8], amp_custom[8];
extern volatile uint32_t amp_sptr;
extern const uint8_t amp_sync_k[16];

static const char *const cnames[NCURVES] = { "STK", "LIN", "EXP", "LOG", "PNCH" };
static const char *const snames[16] = { "1/64", "1/32T", "1/32", "1/16T", "1/32.", "1/16", "1/8T", "1/16.",
                                        "1/8", "1/4T", "1/8.", "1/4", "1/2T", "1/4.", "1/2", "1BAR" };
/* the stock lengths again (env.c has them as tables): for the times shown */
#include "tabs.h"

static uint8_t func, fresh, drawn_valid;
static int32_t acc;
static uint32_t now, last_turn, drawn_key;
static void *ui_ctrl;                   /* the page's controller, from the tick: to ask for a draw */

static uint32_t track(void) { return fw_active_track & 7; }

static int knob(int off)                /* the active track's ATK (94), HOLD (96) or DEC (98), 0-127 */
{
    uint32_t p = amp_sptr;
    int32_t w;
    if (!p)
        return 0;
    w = *(volatile int16_t *)(p + 106 * track() + off) >> 8;
    return w < 0 ? 0 : w > 127 ? 127 : w;
}

static void set_custom(uint32_t t) { amp_custom[t] = (uint8_t)(amp_curve[t] != 0 || amp_sync[t] != 0); }

int amp_key(void *brain, void *ev)
{
    (void)brain;
    if (EV_ID(ev) == KEY_FUNC) {
        func = EV_FLAGS(ev) & 1;
        acc = 0;
        fresh = 1;
    }
    return 0;
}

/* FUNC + a knob: a step a detent, every detent counted (a quick turn arrives as one event of several) */
static int steps(int32_t d)
{
    int s;
    if (fresh || now - last_turn > IDLE || (d > 0 && acc < 0) || (d < 0 && acc > 0))
        acc = 0;
    fresh = 0;
    last_turn = now;
    acc += d;
    s = acc / DETENT;
    acc -= s * DETENT;
    return s;
}

int amp_enc(void *brain, void *ev)
{
    uint32_t t = track();
    int32_t id = EV_ID(ev), n;
    int s;
    (void)brain;
    if (!func || UI_PAGE != PAGE_AMP || (id != ENC_A && id != ENC_B))
        return 0;
    s = steps(EV_DELTA(ev));
    if (id == ENC_A) {
        n = amp_curve[t] + s;
        if (n < 0) n = 0;
        if (n > NCURVES - 1) n = NCURVES - 1;
        amp_curve[t] = (uint8_t)n;
    } else if (s) {
        amp_sync[t] = s > 0;
    }
    set_custom(t);
    if (s && ui_ctrl)
        *((volatile unsigned char *)ui_ctrl + 0x20) = 1;      /* drawn again now, not at the next tick */
    return 1;                                   /* A and B keep their values */
}

void amp_tick(void *ctrl)
{
    uint32_t t = track(), key;
    now++;
    ui_ctrl = ctrl;
    if (UI_PAGE != PAGE_AMP) {
        drawn_valid = 0;
        return;
    }
    key = (uint32_t)amp_curve[t] | (uint32_t)amp_sync[t] << 3 | (uint32_t)func << 4 | t << 5
          | (uint32_t)knob(94) << 8 | (uint32_t)knob(96) << 15 | (uint32_t)knob(98) << 22
          | (uint32_t)(amp_sync[t] && func ? (TEMPO & 0x1f) : 0) << 27;
    if (!drawn_valid || key != drawn_key) {
        *((unsigned char *)ctrl + 0x20) = 1;
        drawn_key = key;
        drawn_valid = 1;
    }
}

/* ---- text ----------------------------------------------------------------------------------------- */
static char *put(char *p, const char *s) { while (*s) *p++ = *s++; *p = 0; return p; }
static char *num(char *p, uint32_t v)
{
    char b[11];
    int i = 0;
    do { b[i++] = (char)('0' + v % 10); v /= 10; } while (v);
    while (i) *p++ = b[--i];
    *p = 0;
    return p;
}
static char *ms(char *p, uint32_t samples)     /* 12MS, 340MS, 1.2S, 14S */
{
    uint32_t m = (samples + 24) / 48;
    if (m < 1000) return put(num(p, m), "MS");
    if (m < 10000) { p = num(p, m / 1000); *p++ = '.'; p = num(p, (m % 1000) / 100); return put(p, "S"); }
    return put(num(p, m / 1000), "S");
}
static int len(const char *s) { int n = 0; while (s[n]) n++; return n; }

static void hold_text(char *p, uint32_t t, int h)
{
    if (h >= 127) put(p, "NOTE");
    else if (amp_sync[t]) put(p, snames[(h * 16) / 127 & 15]);
    else ms(p, hold_len[h]);
}

/* ---- the picture ---------------------------------------------------------------------------------- */
static int32_t sq(int32_t x) { return (x * x) >> 15; }
static int32_t att(int c, int32_t p)
{
    int32_t q = 32768 - p;
    return c == 2 ? sq(p) : c == 3 ? 32768 - sq(q) : c == 4 ? 32768 - sq(sq(q)) : p;
}
static int32_t dec(int c, int32_t p)
{
    int32_t q = 32768 - p;
    return c == 0 ? sq(sq(sq(q))) + (sq(q) >> 4)         /* the stock's: steep, then a tail */
         : c == 2 ? sq(sq(sq(q))) : c == 3 ? 32768 - sq(p) : c == 4 ? 32768 - sq(sq(p)) : q;
}
static void plot(void *bmp, int x, int y0, int y1)      /* a column from the last point to this one */
{
    if (y0 > y1) { int s = y0; y0 = y1; y1 = s; }
    FILLRECT(bmp, x, y0, x, y1, 1);
}
static int yof(int32_t g15) { return BASE + (g15 * (TOP - BASE) + 16384) / 32768; }

static void picture(void *bmp, uint32_t t, int picking)
{
    int c = amp_curve[t] % NCURVES, a = knob(94), h = knob(96), d = knob(98);
    int x = GX0 + 1, i, w, y, py = BASE;
    const char *s;
    FILLRECT(bmp, GX0, GY0, GX1, GY1, 0);
    /* attack */
    w = 1 + (a * 22) / 127;
    for (i = 0; i <= w; i++) {
        y = yof(att(c, (i * 32768) / w));
        plot(bmp, x + i, py, y);
        py = y;
    }
    x += w + 1;
    /* hold */
    if (h >= 127)
        w = 14;
    else if (amp_sync[t])
        w = 2 + ((h * 16) / 127) + 1;
    else
        w = (h * 16) / 127;
    if (w > 0) FILLRECT(bmp, x, TOP, x + w - 1, TOP, 1);
    x += w;
    if (h >= 127)                               /* NOTE: a dotted line where the trig ends */
        for (y = BASE; y <= TOP; y += 2) FILLRECT(bmp, x, y, x, y, 1);
    /* decay */
    py = TOP;
    if (d >= 127) {
        if (x < GX1 - 1) FILLRECT(bmp, x, TOP, GX1 - 1, TOP, 1);
    } else {
        int room = GX1 - 1 - x;
        w = 3 + ((room - 3) * d) / 126;
        if (w > room) w = room;
        for (i = 1; i <= w; i++) {
            y = yof(dec(c, (i * 32768) / w));
            plot(bmp, x + i, py, y);
            py = y;
        }
        if (x + w < GX1 - 1) FILLRECT(bmp, x + w, BASE, GX1 - 1, BASE, 1);
    }
    /* the curve's name, and the note value, top right */
    s = cnames[c];
    FILLRECT(bmp, GX1 - 4 * len(s) - 1, 45, GX1, 51, 0);
    TEXTF(bmp, FONT5, GX1 - 4 * len(s) + 1, 46, -1, "%s", s);
    if (picking)                                /* FUNC held: the name inverted, as dnod-dt's type */
        FILLRECT(bmp, GX1 - 4 * len(s) - 1, 45, GX1, 51, -1);
    if (picking || amp_sync[t]) {               /* the hold's mode under it */
        const char *m = h >= 127 ? "NOTE" : amp_sync[t] ? snames[(h * 16) / 127 & 15] : "FREE";
        FILLRECT(bmp, GX1 - 4 * len(m) - 1, 38, GX1, 44, 0);
        TEXTF(bmp, FONT5, GX1 - 4 * len(m) + 1, 39, -1, "%s", m);
    }
}

/* FUNC held: the times in the title bar (x 17-127, y 53-63, white on black as the stock's title):
 * the attack, the hold (ms, its note value or NOTE) and the decay; in SYNC the hold's ms at this tempo */
static void times(void *bmp, uint32_t t)
{
    int a = knob(94), h = knob(96), d = knob(98);
    char l[40], *p;
    p = put(l, "ATK "); p = ms(p, a ? att_len[a] : 0);
    p = put(p, " HLD ");
    if (amp_sync[t] && h < 127) {
        int32_t tm = TEMPO;
        uint32_t k = amp_sync_k[(h * 16) / 127 & 15];
        p = ms(p, (7200000u * k) / (uint32_t)(tm < 120 ? 120 : tm));
    } else {
        hold_text(p, t, h);
        while (*p) p++;
    }
    p = put(p, " DEC ");
    if (d >= 127) put(p, "INF"); else ms(p, dec_len[d]);
    FILLRECT(bmp, 17, 53, 127, 63, 0);
    TEXTF(bmp, FONT5, 19, 56, -1, "%s", l);
    FILLRECT(bmp, 17, 53, 127, 63, -1);
}

void amp_draw(void *bmp, void *ctrl)
{
    uint32_t t = track();
    (void)ctrl;
    if (UI_PAGE != PAGE_AMP)
        return;
    if (func) {
        picture(bmp, t, 1);
        times(bmp, t);
    } else if (amp_custom[t]) {
        picture(bmp, t, 0);
    }
}
