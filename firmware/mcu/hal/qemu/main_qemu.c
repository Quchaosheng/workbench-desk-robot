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
#include "can_bridge_tests.h"
#include "command_dedup_tests.h"
#include "frame_codec_tests.h"
#include "state_machine_tests.h"
#include "watchdog.h"
#include "watchdog_tests.h"

/* Deliberately uninitialised: if crt0 skipped the .bss loop this is garbage
 * and the check below fails. QEMU happens to hand out zeroed RAM, so this
 * test can pass for the wrong reason on this target — it earns its keep on
 * the board (FW17), where it does not.
 */
static uint32_t bss_probe[4];

static mcu_state_machine_t timer_machine;
static mcu_watchdog_t timer_watchdog;
static volatile uint32_t timer_interrupts;
static volatile uint32_t timer_fault_records;
static volatile bool timer_record_available;
static mcu_watchdog_record_t timer_record;

static void copy_timer_record(const mcu_watchdog_record_t *source)
{
    timer_record.kind = source->kind;
    timer_record.fault = source->fault;
    timer_record.observed_at_us = source->observed_at_us;
    timer_record.deadline_us = source->deadline_us;
    timer_record.command_id = source->command_id;
    timer_record.retry_count = source->retry_count;
    timer_record.frame.kind = source->frame.kind;
    timer_record.frame.command_id = source->frame.command_id;
    timer_record.frame.sequence_no = source->frame.sequence_no;
    timer_record.frame.opcode = source->frame.opcode;
    timer_record.frame.retry_count = source->frame.retry_count;
    timer_record.frame.result_code = source->frame.result_code;
    timer_record.frame.fault_code = source->frame.fault_code;
    timer_record.frame.device_mode = source->frame.device_mode;
}

/* Called by the machine-timer path in crt0.S. It is intentionally tiny: the
 * same allocation-free poll used by Host runs here, followed by the HAL-owned
 * hardware watchdog feed and the next one-shot timer arm. */
void mcu_qemu_timer_interrupt(void)
{
    mcu_watchdog_record_t record;
    uint64_t now_us = hal_now_us();

    timer_interrupts++;
    if (mcu_watchdog_poll(&timer_watchdog, &timer_machine, now_us, &record)) {
        copy_timer_record(&record);
        timer_record_available = true;
        timer_fault_records++;
    }
    if (mcu_watchdog_should_feed_hardware(&timer_watchdog, &timer_machine)) {
        hal_wdt_feed();
    }
    hal_timer_arm_us(now_us + MCU_HEARTBEAT_PERIOD_US);
}

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

static int run_watchdog_tests(void)
{
    mcu_test_report_t report;

    mcu_watchdog_run_tests(&report);
    hal_puts("[mcu] watchdog assertions=");
    hal_put_u32(report.assertions);
    hal_puts(" failures=");
    hal_put_u32(report.failures);
    hal_puts(" first_failure=");
    hal_put_u32(report.first_failure);
    hal_putc('\n');
    return report.failures == 0u ? 0 : 6;
}

static int run_command_dedup_tests(void)
{
    mcu_test_report_t report;

    mcu_command_dedup_run_tests(&report);
    hal_puts("[mcu] command-dedup assertions=");
    hal_put_u32(report.assertions);
    hal_puts(" failures=");
    hal_put_u32(report.failures);
    hal_puts(" first_failure=");
    hal_put_u32(report.first_failure);
    hal_putc('\n');
    return report.failures == 0u ? 0 : 10;
}

static int run_can_bridge_tests(void)
{
    mcu_test_report_t report;

    mcu_can_bridge_run_tests(&report);
    hal_puts("[mcu] can-bridge assertions=");
    hal_put_u32(report.assertions);
    hal_puts(" failures=");
    hal_put_u32(report.failures);
    hal_puts(" first_failure=");
    hal_put_u32(report.first_failure);
    hal_putc('\n');
    return report.failures == 0u ? 0 : 11;
}

static int run_qemu_timing_evidence(void)
{
    mcu_event_t begin_move;
    mcu_transition_result_t transition;
    uint64_t start_us;

    mcu_sm_init(&timer_machine);
    mcu_watchdog_init(&timer_watchdog, 100u);
    begin_move.kind = MCU_EVENT_BEGIN_MOVE;
    begin_move.fault_code = MCU_FAULT_NONE;
    begin_move.reset_authorized = false;
    begin_move.cause_cleared = false;
    mcu_sm_dispatch(&timer_machine, &begin_move, &transition);
    if (transition.result_code != MCU_RESULT_ACCEPTED) {
        hal_puts("[mcu] watchdog demo could not enter executing\n");
        return 7;
    }

    start_us = hal_now_us();
    if (!mcu_watchdog_note_activity(&timer_watchdog,
                                    &timer_machine,
                                    MCU_WATCHDOG_ACTIVITY_VALID_NEW,
                                    start_us)) {
        hal_puts("[mcu] watchdog demo could not arm link timeout\n");
        return 8;
    }
    hal_wdt_start(MCU_HARDWARE_WATCHDOG_PERIOD_MS);
    timer_interrupts = 0u;
    timer_fault_records = 0u;
    timer_record_available = false;
    hal_timer_arm_us(start_us + MCU_HEARTBEAT_PERIOD_US);
    hal_timer_enable();

    /* Three timer periods reach the software deadline. The fourth proves that
     * the timer keeps running after the fault while the core stops feeding the
     * modeled hardware watchdog. */
    while (timer_interrupts < 4u && !hal_wdt_is_expired()) {
        __asm__ volatile("wfi");
    }
    if (timer_interrupts < 3u || timer_fault_records != 1u || !timer_record_available ||
        timer_record.kind != MCU_WATCHDOG_RECORD_FAULT_TELEMETRY ||
        timer_machine.state != MCU_STATE_FAULT || hal_wdt_feed_count() == 0u) {
        hal_timer_disarm();
        hal_puts("[mcu] QEMU timer/watchdog evidence failed\n");
        return 9;
    }

    while (!hal_wdt_is_expired()) {
        __asm__ volatile("wfi");
    }
    hal_timer_disarm();
    hal_puts("[mcu] QEMU timer interrupts=");
    hal_put_u32(timer_interrupts);
    hal_puts(" fault_records=");
    hal_put_u32(timer_fault_records);
    hal_puts(" wdt_feeds=");
    hal_put_u32(hal_wdt_feed_count());
    hal_puts(" wdt_expired=1\n");
    return 0;
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
    rc |= run_watchdog_tests();
    rc |= run_command_dedup_tests();
    rc |= run_can_bridge_tests();
    rc |= run_qemu_timing_evidence();

    /* The platform-independent HAL/Wire boundary is covered above. QEMU CAN
     * transport remains explicit NOT_EXECUTED because these HAL functions are
     * still false-returning stubs. */
    hal_puts("[mcu] CAN transport NOT_EXECUTED - QEMU HAL is a stub\n");

    return rc;
}
