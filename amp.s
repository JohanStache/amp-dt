| SPDX-License-Identifier: GPL-2.0-or-later
| amp-dt 0.2: the Digitakt mk1 (OS 1.54) AMP envelope with curves and a tempo-synced hold.
| The stock envelope (0x400716c0, called once a block from the render with the blocks and a
| 26-byte record: ATK[8] HOLD[8] DEC[8] trig bits, note-off bits) is reassembled here byte for
| byte (stock_env.inc, from mk_stock.py). One thing is added: at the head of its per-track loop,
| a track whose amp_custom byte is set skips the stock body and runs amp_track (env.c) instead,
| so a track on the stock curve with a free hold plays exactly as stock.
| The envelope state stays the stock's (0x4199ed64, 8 bytes a track: phase, value), which other
| mods read (core's fw_amp_level, byte-dt's sleep).

        .section .bss
        .globl  amp_sptr, amp_blk, amp_custom
        .align  4
amp_sptr:       .space 4                | the render's track records (a2 at the call): AMP at +94 + 106 t
amp_blk:        .space 4                | blocks rendered, for env.c to see a track it skipped
amp_custom:     .space 8                | per track: nonzero runs amp_track

        .section .run, "ax"

| At the loop head: d6 the track, a2/a0 its state (phase, value), a4 the record + track,
| sp@(64) the blocks, sp@(68) the record. amp_track(t, blocks, record, state) keeps d2-d7/a2-a6.
        .macro  AMP_DISPATCH
        lea     amp_custom,%a1
        tst.b   %a1@(0,%d6:l)
        beq.w   9f
        addql   #1,%a4                  | the stock's mvsb %a4@+ (the record's ATK, track by track)
        move.l  %a0,-(%sp)
        move.l  %a2,-(%sp)
        move.l  %sp@(68+8),-(%sp)       | the record
        move.l  %sp@(64+12),-(%sp)      | the blocks
        move.l  %d6,-(%sp)
        jsr     amp_track
        lea     %sp@(16),%sp
        moveal  (%sp)+,%a0
        bra.w   L_4007185a              | the stock's loop tail: next track
9:
        .endm

        .globl  amp_env
amp_env:
        move.l  %a2,amp_sptr
        addq.l  #1,amp_blk
        .include "stock_env.inc"

| int32_t amp_ramp(int32_t *x, int32_t n, int32_t g, int32_t step): x[i] *= g, g += step
| (g in Q31, 0..0x7fffffff); returns g after the n samples. n > 0. Four samples a pass on four
| accumulators, as the stock decay does, so no MAC waits on the one before it.
        .globl  amp_ramp
amp_ramp:
        lea     %sp@(-24),%sp
        movem.l %d2-%d6/%a2,%sp@
        moveal  %sp@(28),%a0
        move.l  %sp@(32),%d1
        move.l  %sp@(36),%d2
        move.l  %sp@(40),%d3
        move.l  %macsr,%d6
        move.l  #0xa0,%macsr            | fractional, saturating
        moveal  %a0,%a1                 | where the results go
        subq.l  #4,%d1
        blt.s   3f
        move.l  %a0@+,%d0               | x0; each MAC loads the next sample as it multiplies
1:      mac.l   %d0,%d2,%a0@+,%d4,%acc0
        add.l   %d3,%d2
        mac.l   %d4,%d2,%a0@+,%d0,%acc1
        add.l   %d3,%d2
        mac.l   %d0,%d2,%a0@+,%d4,%acc2
        add.l   %d3,%d2
        mac.l   %d4,%d2,%a0@+,%d0,%acc3 | (the last pass reads one sample past: never used)
        add.l   %d3,%d2
        movclr.l %acc0,%d4
        move.l  %d4,%a1@+
        movclr.l %acc1,%d5
        move.l  %d5,%a1@+
        movclr.l %acc2,%d4
        move.l  %d4,%a1@+
        movclr.l %acc3,%d5
        move.l  %d5,%a1@+
        subq.l  #4,%d1
        bge.s   1b
        subq.l  #4,%a0                  | back to the first sample not yet done
3:      addq.l  #4,%d1                  | the 0-3 left, one at a time
        ble.s   5f
4:      move.l  %a0@+,%d0
        mac.l   %d0,%d2,%acc0
        add.l   %d3,%d2
        movclr.l %acc0,%d4
        move.l  %d4,%a1@+
        subq.l  #1,%d1
        bgt.s   4b
5:      move.l  %d6,%macsr
        move.l  %d2,%d0
        movem.l %sp@,%d2-%d6/%a2
        lea     %sp@(24),%sp
        rts

| int32_t amp_expdec(int32_t *x, int32_t n, int32_t g, int32_t c): the stock decay's shape, x[i] *= g,
| g *= c (Q31, c = |the stock coefficient|); returns g. For a stock-curve track with a synced hold.
| Two samples a pass, as the stock: g, g c from g and c^2, on four accumulators.
        .globl  amp_expdec
amp_expdec:
        lea     %sp@(-28),%sp
        movem.l %d2-%d7/%a2,%sp@
        moveal  %sp@(32),%a0
        move.l  %sp@(36),%d1
        move.l  %sp@(40),%d2            | g
        move.l  %sp@(44),%d3            | c
        move.l  %macsr,%d7
        move.l  #0xa0,%macsr
        mac.l   %d3,%d3,%acc0
        movclr.l %acc0,%d6              | c^2
        subq.l  #2,%d1
        blt.s   3f
1:      move.l  %a0@,%d0
        mac.l   %d0,%d2,%acc0           | x0 g
        mac.l   %d2,%d3,%acc1           | g c
        mac.l   %d2,%d6,%acc2           | g c^2: the next pair's g
        move.l  %a0@(4),%d4
        movclr.l %acc1,%d5
        mac.l   %d4,%d5,%acc3           | x1 g c
        movclr.l %acc0,%d0
        move.l  %d0,%a0@+
        movclr.l %acc2,%d2
        movclr.l %acc3,%d4
        move.l  %d4,%a0@+
        subq.l  #2,%d1
        bge.s   1b
3:      addq.l  #2,%d1
        ble.s   5f
        move.l  %a0@,%d0                | an odd one
        mac.l   %d0,%d2,%acc0
        mac.l   %d2,%d3,%acc1
        movclr.l %acc0,%d0
        move.l  %d0,%a0@+
        movclr.l %acc1,%d2
5:      move.l  %d7,%macsr
        move.l  %d2,%d0
        movem.l %sp@,%d2-%d7/%a2
        lea     %sp@(28),%sp
        rts
