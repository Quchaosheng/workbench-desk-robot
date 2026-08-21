/* Entry point for the QEMU build. Task FW1/FW2 acceptance.
 *
 * This lives in hal/qemu/, not core/, for two reasons:
 *   - it reads __stack_bottom/__stack_top, which are QEMU link.ld symbols
 *   - the host build has its own main() in tests/, and two main()s in one
 *     link is an error
 *
 * core/ stays free of entry points. That is what makes it compile unchanged
 * for all three targets.
 *
 * This is a smoke test, not the fault suite. It proves the four things FW1 and
 * FW2 are actually about:
 *   - the toolchain produces a bootable rv32imac image
 *   - crt0 set up sp and gp, and zeroed .bss
 *   - the UART works, so later tests have a way to report
 *   - mtime advances, so FW5's watchdog has a clock to trust
 */
#include "hal.h"
#include "frame_codec_tests.h"
#include "state_machine_tests.h"

/* Deliberately uninitialised: if crt0 skipped the .bss loop this is garbage
 * and the check below fails. QEMU happens to hand out zeroed RAM, so this
 * test can pass for the wrong reason on this target — it earns its keep on
 * the board (FW17), where it does not.
 */
static uint32_t bss_probe[4];

static int check_bss_zeroed(void)
{
    for (unsigned i = 0; i < 4; i++) {
        if (bss_probe[i] != 0) {
            hal_puts("[mcu] .bss not zeroed at index ");
            hal_put_u32(i);
            hal_putc('\n');
            return 1;
        }
    }
    hal_puts("[mcu] ok   .bss zeroed\n");
    return 0;
}

static int check_clock_advances(void)
{
    uint64_t t0 = hal_now_us();

    /* Spin, don't sleep: there is no scheduler here. volatile keeps -Os from
     * deleting the loop. */
    for (volatile uint32_t i = 0; i < 200000; i++) { }

    uint64_t t1 = hal_now_us();
    if (t1 <= t0) {
        hal_puts("[mcu] clock did not advance\n");
        return 2;
    }
    hal_puts("[mcu] ok   clock advanced ");
    hal_put_u32((uint32_t)(t1 - t0));
    hal_puts(" us\n");
    return 0;
}

static int check_stack_sane(void)
{
    /* sp should sit inside the region the linker reserved. Off-by-one here
     * shows up as memory corruption much later, so check it while we can
     * still print. */
    extern char __stack_bottom[], __stack_top[];
    uintptr_t sp;
    __asm__ volatile("mv %0, sp" : "=r"(sp));

    if (sp <= (uintptr_t)__stack_bottom || sp > (uintptr_t)__stack_top) {
        hal_puts("[mcu] sp outside the linked stack region\n");
        return 3;
    }
    hal_puts("[mcu] ok   sp inside .stack, headroom ");
    hal_put_u32((uint32_t)(sp - (uintptr_t)__stack_bottom));
    hal_puts(" bytes\n");
    return 0;
}

static int run_state_machine_tests(void)
{
    mcu_test_report_t report;

    mcu_state_machine_run_tests(&report);
    hal_puts("[mcu] state-machine assertions=");
    hal_put_u32(report.assertions);
    hal_puts(" failures=");
    hal_put_u32(report.failures);
    hal_puts(" first_failure=");
    hal_put_u32(report.first_failure);
    hal_putc('\n');
    return report.failures == 0u ? 0 : 4;
}

static int run_frame_codec_tests(void)
{
    mcu_test_report_t report;

    mcu_frame_codec_run_tests(&report);
    hal_puts("[mcu] frame-codec assertions=");
    hal_put_u32(report.assertions);
    hal_puts(" failures=");
    hal_put_u32(report.failures);
    hal_puts(" first_failure=");
    hal_put_u32(report.first_failure);
    hal_putc('\n');
    return report.failures == 0u ? 0 : 5;
}

int main(void)
{
    hal_puts("\n[mcu] FW1/FW2 smoke test\n");

    int rc = 0;
    rc |= check_bss_zeroed();
    rc |= check_clock_advances();
    rc |= check_stack_sane();
    rc |= run_state_machine_tests();
    rc |= run_frame_codec_tests();

    /* CAN is deliberately not checked: hal_can_init returns false until FW10,
     * and a smoke test that skipped over that would be misleading. */
    hal_puts("[mcu] skip CAN - hal_can_init is a stub until FW10\n");

    return rc;
}
