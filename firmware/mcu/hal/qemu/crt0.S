/* Startup for the QEMU virt machine. Task FW2.
 *
 * Order matters and each step has a reason:
 *   1. sp before anything else — a C call with a garbage sp corrupts memory
 *      silently rather than trapping.
 *   2. .bss zeroed before main — C guarantees statics start at zero. QEMU
 *      happens to hand us zeroed RAM; the real board does not.
 *   3. mtvec set before enabling anything that can trap, so a fault lands in
 *      our handler instead of looping at the reset vector.
 */

    .section .text.entry, "ax"
    .global _start
    .type _start, @function

_start:
    /* Disable interrupts until the vector table and stack are valid. */
    csrw    mie, zero
    csrw    mip, zero

    /* 1. Stack pointer. */
    la      sp, __stack_top

    /* Frame pointer and global pointer: gp is used for .sdata addressing.
       .option norelax stops the assembler rewriting these into gp-relative
       loads before gp itself is set up. */
.option push
.option norelax
    la      gp, __global_pointer$
.option pop
    mv      fp, sp

    /* 2. Zero .bss. */
    la      a0, __bss_start
    la      a1, __bss_end
    beq     a0, a1, bss_done
bss_loop:
    sw      zero, 0(a0)
    addi    a0, a0, 4
    bltu    a0, a1, bss_loop
bss_done:

    /* .data is already in place: on this machine the ELF loads straight into
       RAM, so there is no flash-to-RAM copy. The CH32V307 crt0 (FW17) will
       need one, which is another reason crt0 is per-HAL. */

    /* 3. Trap vector, direct mode (low two bits 0). */
    la      t0, trap_entry
    csrw    mtvec, t0

    /* Paint the stack so FW9 can measure high-water mark by looking for the
       last untouched word. Cheap, and turns "probably fine" into a number. */
    la      t0, __stack_bottom
    la      t1, __stack_top
    li      t2, 0xC0FFEE00
paint_loop:
    sw      t2, 0(t0)
    addi    t0, t0, 4
    bltu    t0, t1, paint_loop

    call    main

    /* main returned: a0 holds the exit code. Report it, then halt. */
    call    hal_report_exit

halt:
    wfi
    j       halt

    .size _start, . - _start


/* Trap handler. Anything arriving here in a safety MCU is a bug, so it reports
 * and halts rather than trying to continue. FW2's acceptance test is that an
 * illegal instruction actually lands here.
 */
    .align 4
    .global trap_entry
    .type trap_entry, @function
trap_entry:
    /* Preserve the caller-saved registers before inspecting mcause. In
     * particular, t0/t1 are used for dispatch and must still be restored to
     * their pre-interrupt values on the timer-return path. */
    addi    sp, sp, -64
    sw      ra, 0(sp)
    sw      t0, 4(sp)
    sw      t1, 8(sp)
    sw      t2, 12(sp)
    sw      t3, 16(sp)
    sw      t4, 20(sp)
    sw      t5, 24(sp)
    sw      t6, 28(sp)
    sw      a0, 32(sp)
    sw      a1, 36(sp)
    sw      a2, 40(sp)
    sw      a3, 44(sp)
    sw      a4, 48(sp)
    sw      a5, 52(sp)
    sw      a6, 56(sp)
    sw      a7, 60(sp)

    csrr    t0, mcause
    li      t1, 0x80000007
    bne     t0, t1, unexpected_trap
    call    mcu_qemu_timer_interrupt
    lw      ra, 0(sp)
    lw      t0, 4(sp)
    lw      t1, 8(sp)
    lw      t2, 12(sp)
    lw      t3, 16(sp)
    lw      t4, 20(sp)
    lw      t5, 24(sp)
    lw      t6, 28(sp)
    lw      a0, 32(sp)
    lw      a1, 36(sp)
    lw      a2, 40(sp)
    lw      a3, 44(sp)
    lw      a4, 48(sp)
    lw      a5, 52(sp)
    lw      a6, 56(sp)
    lw      a7, 60(sp)
    addi    sp, sp, 64
    mret

unexpected_trap:
    csrr    a0, mcause
    csrr    a1, mepc
    call    hal_report_trap

    /* No return. A trap means an invariant already broke. */
trap_halt:
    wfi
    j       trap_halt

    .size trap_entry, . - trap_entry
