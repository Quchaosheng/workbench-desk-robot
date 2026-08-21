#include "watchdog_tests.h"

#include <stdbool.h>
#include <stdint.h>


#include "watchdog.h"

typedef struct {
    uint64_t now_us;
} fake_clock_t;

static void check(mcu_test_report_t *report, bool condition)
{
    report->assertions++;
    if (!condition) {
        report->failures++;
        if (report->first_failure == 0u) {
            report->first_failure = report->assertions;
        }
    }
}

static void dispatch(mcu_state_machine_t *machine,
                     mcu_event_kind_t kind,
                     mcu_transition_result_t *result)
{
    mcu_event_t event;

    event.kind = kind;
    event.fault_code = MCU_FAULT_NONE;
    event.reset_authorized = false;
    event.cause_cleared = false;
    mcu_sm_dispatch(machine, &event, result);
}

static void start_move(mcu_state_machine_t *machine)
{
    mcu_transition_result_t result;

    mcu_sm_init(machine);
    dispatch(machine, MCU_EVENT_BEGIN_MOVE, &result);
}

static void make_stop(mcu_wire_frame_t *stop, uint16_t command_id, uint8_t retry_count)
{
    stop->kind = MCU_WIRE_FRAME_STOP;
    stop->command_id = command_id;
    stop->sequence_no = 0u;
    stop->opcode = MCU_WIRE_OPCODE_STOP;
    stop->retry_count = retry_count;
    stop->result_code = MCU_WIRE_RESULT_ACCEPTED;
    stop->fault_code = MCU_WIRE_FAULT_NONE;
    stop->device_mode = MCU_WIRE_MODE_IDLE;
}

static bool record_frame_encodes(const mcu_watchdog_record_t *record)
{
    uint16_t arbitration_id;
    uint8_t data[MCU_WIRE_DLC];
    uint8_t length;

    return mcu_frame_encode(&record->frame, &arbitration_id, data, sizeof(data), &length) ==
             MCU_CODEC_OK &&
           length == MCU_WIRE_DLC;
}

static void test_controlled_constants(mcu_test_report_t *report)
{
    check(report, MCU_HEARTBEAT_PERIOD_US > 0u);
    check(report, MCU_SOFTWARE_WATCHDOG_TIMEOUT_US >= 2u * MCU_HEARTBEAT_PERIOD_US);
    check(report, MCU_STOP_ACK_DEADLINE_US > 0u);
    check(report, MCU_STOP_ACK_DEADLINE_US < MCU_SOFTWARE_WATCHDOG_TIMEOUT_US);
    check(report, MCU_HARDWARE_WATCHDOG_PERIOD_MS > 0u);
}

static void test_only_valid_new_activity_feeds(mcu_test_report_t *report)
{
    static const mcu_watchdog_activity_t rejected_activity[] = {
        MCU_WATCHDOG_ACTIVITY_RETRY,
        MCU_WATCHDOG_ACTIVITY_DUPLICATE,
        MCU_WATCHDOG_ACTIVITY_STALE,
        MCU_WATCHDOG_ACTIVITY_MALFORMED,
        MCU_WATCHDOG_ACTIVITY_STOP,
    };
    mcu_watchdog_t watchdog;
    mcu_state_machine_t machine;
    mcu_transition_result_t transition;
    fake_clock_t clock = {.now_us = 1000u};
    uint64_t deadline;
    unsigned i;

    mcu_watchdog_init(&watchdog, 7u);
    mcu_sm_init(&machine);
    check(report,
          !mcu_watchdog_note_activity(
            &watchdog, &machine, MCU_WATCHDOG_ACTIVITY_VALID_NEW, clock.now_us));
    check(report, !watchdog.link_watchdog_armed);

    dispatch(&machine, MCU_EVENT_BEGIN_MOVE, &transition);
    check(report,
          mcu_watchdog_note_activity(
            &watchdog, &machine, MCU_WATCHDOG_ACTIVITY_VALID_NEW, clock.now_us));
    deadline = clock.now_us + MCU_SOFTWARE_WATCHDOG_TIMEOUT_US;
    check(report, watchdog.link_watchdog_armed);
    check(report, watchdog.link_deadline_us == deadline);

    for (i = 0u; i < sizeof(rejected_activity) / sizeof(rejected_activity[0]); i++) {
        clock.now_us += MCU_HEARTBEAT_PERIOD_US;
        check(report,
              !mcu_watchdog_note_activity(
                &watchdog, &machine, rejected_activity[i], clock.now_us));
        check(report, watchdog.link_deadline_us == deadline);
    }

    check(report,
          !mcu_watchdog_note_activity(
            &watchdog, &machine, MCU_WATCHDOG_ACTIVITY_COUNT, clock.now_us));
    check(report, watchdog.link_deadline_us == deadline);
}

static void test_watchdog_deadline_and_single_record(mcu_test_report_t *report)
{
    mcu_watchdog_t watchdog;
    mcu_state_machine_t machine;
    mcu_watchdog_record_t record;
    fake_clock_t clock = {.now_us = 9000u};
    uint64_t deadline;

    mcu_watchdog_init(&watchdog, 41u);
    start_move(&machine);
    check(report,
          mcu_watchdog_note_activity(
            &watchdog, &machine, MCU_WATCHDOG_ACTIVITY_VALID_NEW, clock.now_us));
    deadline = watchdog.link_deadline_us;

    record.kind = MCU_WATCHDOG_RECORD_STOP_ACK;
    check(report, !mcu_watchdog_poll(&watchdog, &machine, deadline - 1u, &record));
    check(report, record.kind == MCU_WATCHDOG_RECORD_STOP_ACK);
    check(report, machine.state == MCU_STATE_EXECUTING);

    check(report, mcu_watchdog_poll(&watchdog, &machine, deadline, &record));
    check(report, record.kind == MCU_WATCHDOG_RECORD_FAULT_TELEMETRY);
    check(report, record.fault == MCU_WATCHDOG_FAULT_WATCHDOG_EXPIRED);
    check(report, record.observed_at_us == deadline);
    check(report, record.deadline_us == deadline);
    check(report, record.frame.kind == MCU_WIRE_FRAME_TELEMETRY);
    check(report, record.frame.sequence_no == 41u);
    check(report, record.frame.fault_code == MCU_WIRE_FAULT_WATCHDOG_EXPIRED);
    check(report, record.frame.device_mode == MCU_WIRE_MODE_FAULTED);
    check(report, record_frame_encodes(&record));
    check(report, machine.state == MCU_STATE_FAULT);
    check(report, machine.device_mode == MCU_DEVICE_MODE_FAULTED);
    check(report, machine.fault_code == MCU_FAULT_WATCHDOG_EXPIRED);
    check(report, !watchdog.link_watchdog_armed);

    record.kind = MCU_WATCHDOG_RECORD_STOP_ACK;
    check(report, !mcu_watchdog_poll(&watchdog, &machine, deadline + 1u, &record));
    check(report, record.kind == MCU_WATCHDOG_RECORD_STOP_ACK);
}

static void test_uint64_wraparound(mcu_test_report_t *report)
{
    mcu_watchdog_t watchdog;
    mcu_state_machine_t machine;
    mcu_watchdog_record_t record;
    fake_clock_t clock = {.now_us = UINT64_MAX - 100000u};
    uint64_t deadline = clock.now_us + MCU_SOFTWARE_WATCHDOG_TIMEOUT_US;

    mcu_watchdog_init(&watchdog, UINT32_MAX);
    start_move(&machine);
    check(report,
          mcu_watchdog_note_activity(
            &watchdog, &machine, MCU_WATCHDOG_ACTIVITY_VALID_NEW, clock.now_us));
    check(report, watchdog.link_deadline_us == deadline);
    check(report, !mcu_watchdog_poll(&watchdog, &machine, deadline - 1u, &record));
    check(report, machine.state == MCU_STATE_EXECUTING);
    check(report, mcu_watchdog_poll(&watchdog, &machine, deadline, &record));
    check(report, record.frame.sequence_no == UINT32_MAX);
    check(report, watchdog.next_telemetry_sequence == 0u);
    check(report, machine.state == MCU_STATE_FAULT);
}

static void test_stop_ack_within_bound(mcu_test_report_t *report)
{
    mcu_watchdog_t watchdog;
    mcu_state_machine_t machine;
    mcu_wire_frame_t stop;
    mcu_watchdog_record_t record;
    fake_clock_t clock = {.now_us = 50000u};
    uint64_t deadline;

    mcu_watchdog_init(&watchdog, 0u);
    start_move(&machine);
    check(report,
          mcu_watchdog_note_activity(
            &watchdog, &machine, MCU_WATCHDOG_ACTIVITY_VALID_NEW, clock.now_us));
    make_stop(&stop, MCU_STOP_ID_MIN + 9u, 2u);
    check(report, mcu_watchdog_receive_stop(&watchdog, &machine, &stop, clock.now_us, &record));
    deadline = clock.now_us + MCU_STOP_ACK_DEADLINE_US;

    check(report, machine.state == MCU_STATE_SAFE_STOP);
    check(report, machine.device_mode == MCU_DEVICE_MODE_STOPPED);
    check(report, !watchdog.link_watchdog_armed);
    check(report, watchdog.stop_ack_pending);
    check(report, watchdog.stop_deadline_us == deadline);
    check(report, record.kind == MCU_WATCHDOG_RECORD_STOP_ACK);
    check(report, record.command_id == stop.command_id);
    check(report, record.retry_count == stop.retry_count);
    check(report, record.deadline_us == deadline);
    check(report, record.observed_at_us == clock.now_us);
    check(report, record.frame.kind == MCU_WIRE_FRAME_STOP_ACK);
    check(report, record.frame.command_id == stop.command_id);
    check(report, record.frame.retry_count == stop.retry_count);
    check(report, record.frame.result_code == MCU_WIRE_RESULT_ACCEPTED);
    check(report, record.frame.fault_code == MCU_WIRE_FAULT_NONE);
    check(report, record.frame.device_mode == MCU_WIRE_MODE_STOPPED);
    check(report, record_frame_encodes(&record));

    check(report,
          !mcu_watchdog_confirm_stop_ack(
            &watchdog, (uint16_t)(stop.command_id + 1u), stop.retry_count, deadline));
    check(report, watchdog.stop_ack_pending);
    check(report,
          mcu_watchdog_confirm_stop_ack(
            &watchdog, stop.command_id, stop.retry_count, deadline));
    check(report, !watchdog.stop_ack_pending);
    check(report, !mcu_watchdog_poll(&watchdog, &machine, deadline + 1u, &record));
    check(report, machine.state == MCU_STATE_SAFE_STOP);
}

static void test_stop_timeout_is_distinct_and_latched(mcu_test_report_t *report)
{
    mcu_watchdog_t watchdog;
    mcu_state_machine_t machine;
    mcu_wire_frame_t stop;
    mcu_watchdog_record_t record;
    mcu_transition_result_t reset;
    fake_clock_t clock = {.now_us = UINT64_MAX - 4000u};
    uint64_t deadline = clock.now_us + MCU_STOP_ACK_DEADLINE_US;

    mcu_watchdog_init(&watchdog, 0u);
    start_move(&machine);
    make_stop(&stop, MCU_STOP_ID_MIN, 255u);
    check(report, mcu_watchdog_receive_stop(&watchdog, &machine, &stop, clock.now_us, &record));
    check(report, !mcu_watchdog_poll(&watchdog, &machine, deadline, &record));
    check(report, watchdog.stop_ack_pending);
    check(report, mcu_watchdog_poll(&watchdog, &machine, deadline + 1u, &record));
    check(report, record.kind == MCU_WATCHDOG_RECORD_STOP_TIMEOUT);
    check(report, record.fault == MCU_WATCHDOG_FAULT_STOP_TIMEOUT);
    check(report, record.command_id == stop.command_id);
    check(report, record.retry_count == stop.retry_count);
    check(report, record.deadline_us == deadline);
    check(report, machine.state == MCU_STATE_SAFE_STOP);
    check(report, machine.device_mode == MCU_DEVICE_MODE_STOPPED);
    check(report, !watchdog.stop_ack_pending);
    check(report, watchdog.stop_timeout_cause_active);
    check(report,
          !mcu_watchdog_receive_stop(&watchdog, &machine, &stop, deadline + 2u, &record));
    check(report,
          !mcu_watchdog_confirm_stop_ack(
            &watchdog, stop.command_id, stop.retry_count, deadline + 1u));

    record.kind = MCU_WATCHDOG_RECORD_STOP_ACK;
    check(report, !mcu_watchdog_poll(&watchdog, &machine, deadline + 2u, &record));
    check(report, record.kind == MCU_WATCHDOG_RECORD_STOP_ACK);
    check(report,
          !mcu_watchdog_request_reset(&watchdog, &machine, true, true, &reset));
    check(report, reset.reason == MCU_REASON_RESET_CAUSE_ACTIVE);
    check(report, machine.state == MCU_STATE_SAFE_STOP);
    mcu_watchdog_mark_causes_cleared(&watchdog);
    check(report,
          !mcu_watchdog_request_reset(&watchdog, &machine, false, true, &reset));
    check(report, reset.reason == MCU_REASON_RESET_NOT_AUTHORIZED);
    check(report, mcu_watchdog_request_reset(&watchdog, &machine, true, true, &reset));
    check(report, machine.state == MCU_STATE_IDLE);
}

static void test_watchdog_reset_requires_live_cause_clear(mcu_test_report_t *report)
{
    mcu_watchdog_t watchdog;
    mcu_state_machine_t machine;
    mcu_watchdog_record_t record;
    mcu_transition_result_t reset;
    fake_clock_t clock = {.now_us = 8u};

    mcu_watchdog_init(&watchdog, 0u);
    start_move(&machine);
    check(report,
          mcu_watchdog_note_activity(
            &watchdog, &machine, MCU_WATCHDOG_ACTIVITY_VALID_NEW, clock.now_us));
    check(report,
          mcu_watchdog_poll(
            &watchdog, &machine, clock.now_us + MCU_SOFTWARE_WATCHDOG_TIMEOUT_US, &record));
    check(report, watchdog.watchdog_cause_active);
    check(report,
          !mcu_watchdog_request_reset(&watchdog, &machine, true, true, &reset));
    check(report, reset.reason == MCU_REASON_RESET_CAUSE_ACTIVE);
    check(report, machine.state == MCU_STATE_FAULT);
    mcu_watchdog_mark_causes_cleared(&watchdog);
    check(report, mcu_watchdog_request_reset(&watchdog, &machine, true, true, &reset));
    check(report, machine.state == MCU_STATE_IDLE);
    check(report, !watchdog.watchdog_record_emitted);
}

static void test_hardware_feed_policy_in_latched_fault(mcu_test_report_t *report)
{
    mcu_watchdog_t watchdog;
    mcu_state_machine_t machine;
    mcu_watchdog_record_t record;
    fake_clock_t clock = {.now_us = 21u};

    mcu_watchdog_init(&watchdog, 0u);
    start_move(&machine);
    check(report,
          mcu_watchdog_note_activity(
            &watchdog, &machine, MCU_WATCHDOG_ACTIVITY_VALID_NEW, clock.now_us));
    check(report,
          mcu_watchdog_poll(
            &watchdog, &machine, clock.now_us + MCU_SOFTWARE_WATCHDOG_TIMEOUT_US, &record));
    check(report, machine.state == MCU_STATE_FAULT);
    check(report, watchdog.watchdog_cause_active);
    check(report, !mcu_watchdog_should_feed_hardware(&watchdog, &machine));

    mcu_watchdog_mark_causes_cleared(&watchdog);
    check(report, machine.state == MCU_STATE_FAULT);
    check(report, !watchdog.watchdog_cause_active);
    check(report, mcu_watchdog_should_feed_hardware(&watchdog, &machine));
}

static void test_invalid_inputs_and_hardware_feed_gate(mcu_test_report_t *report)
{
    mcu_watchdog_t watchdog;
    mcu_state_machine_t machine;
    mcu_watchdog_record_t record;
    mcu_wire_frame_t stop;

    mcu_watchdog_init(&watchdog, 0u);
    mcu_sm_init(&machine);
    check(report, mcu_watchdog_is_valid(&watchdog));
    check(report, mcu_watchdog_should_feed_hardware(&watchdog, &machine));
    check(report, !mcu_watchdog_should_feed_hardware(0, &machine));
    check(report, !mcu_watchdog_should_feed_hardware(&watchdog, 0));

    machine.device_mode = MCU_DEVICE_MODE_MOVING;
    check(report, !mcu_watchdog_should_feed_hardware(&watchdog, &machine));
    check(report,
          !mcu_watchdog_note_activity(
            &watchdog, &machine, MCU_WATCHDOG_ACTIVITY_VALID_NEW, 0u));
    check(report, !mcu_watchdog_poll(&watchdog, &machine, 0u, &record));

    mcu_sm_init(&machine);
    make_stop(&stop, MCU_STOP_ID_MIN, 0u);
    stop.opcode = MCU_WIRE_OPCODE_HEARTBEAT;
    check(report, !mcu_watchdog_receive_stop(&watchdog, &machine, &stop, 0u, &record));
    check(report, machine.state == MCU_STATE_IDLE);
    check(report, !watchdog.stop_ack_pending);

    watchdog.initialized = 0u;
    check(report, !mcu_watchdog_is_valid(&watchdog));
    check(report, !mcu_watchdog_poll(&watchdog, &machine, 0u, &record));
}

void mcu_watchdog_run_tests(mcu_test_report_t *report)
{
    if (report == 0) {
        return;
    }

    report->assertions = 0u;
    report->failures = 0u;
    report->first_failure = 0u;

    test_controlled_constants(report);
    test_only_valid_new_activity_feeds(report);
    test_watchdog_deadline_and_single_record(report);
    test_uint64_wraparound(report);
    test_stop_ack_within_bound(report);
    test_stop_timeout_is_distinct_and_latched(report);
    test_watchdog_reset_requires_live_cause_clear(report);
    test_hardware_feed_policy_in_latched_fault(report);
    test_invalid_inputs_and_hardware_feed_gate(report);
}
