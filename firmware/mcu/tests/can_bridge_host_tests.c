#include "can_bridge_host_tests.h"

#include <stdbool.h>

#include "can_bridge.h"
#include "hal_host_test.h"

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

static void clear_wire_frame(mcu_wire_frame_t *frame)
{
    frame->kind = MCU_WIRE_FRAME_COMMAND;
    frame->command_id = 0u;
    frame->sequence_no = 0u;
    frame->opcode = MCU_WIRE_OPCODE_RESERVED;
    frame->retry_count = 0u;
    frame->result_code = MCU_WIRE_RESULT_ACCEPTED;
    frame->fault_code = MCU_WIRE_FAULT_NONE;
    frame->device_mode = MCU_WIRE_MODE_IDLE;
}

static void make_frame(mcu_wire_frame_kind_t kind, mcu_wire_frame_t *frame)
{
    clear_wire_frame(frame);
    frame->kind = kind;
    switch (kind) {
    case MCU_WIRE_FRAME_COMMAND:
        frame->command_id = 7u;
        frame->opcode = MCU_WIRE_OPCODE_MOVE;
        break;
    case MCU_WIRE_FRAME_ACK:
        frame->command_id = 7u;
        frame->opcode = MCU_WIRE_OPCODE_MOVE;
        frame->device_mode = MCU_WIRE_MODE_MOVING;
        break;
    case MCU_WIRE_FRAME_TELEMETRY:
        frame->sequence_no = 11u;
        break;
    case MCU_WIRE_FRAME_STOP:
        frame->command_id = MCU_STOP_ID_MIN;
        frame->opcode = MCU_WIRE_OPCODE_STOP;
        break;
    case MCU_WIRE_FRAME_STOP_ACK:
        frame->command_id = MCU_STOP_ID_MIN;
        frame->opcode = MCU_WIRE_OPCODE_STOP;
        frame->device_mode = MCU_WIRE_MODE_STOPPED;
        break;
    case MCU_WIRE_FRAME_KIND_COUNT:
    default:
        break;
    }
}

static bool wire_frames_equal(const mcu_wire_frame_t *left,
                              const mcu_wire_frame_t *right)
{
    return left->kind == right->kind && left->command_id == right->command_id &&
           left->sequence_no == right->sequence_no && left->opcode == right->opcode &&
           left->retry_count == right->retry_count && left->result_code == right->result_code &&
           left->fault_code == right->fault_code && left->device_mode == right->device_mode;
}

static void initialize_core(mcu_command_dedup_t *dedup,
                            mcu_state_machine_t *machine,
                            mcu_watchdog_t *watchdog)
{
    mcu_command_dedup_init(dedup);
    mcu_sm_init(machine);
    mcu_watchdog_init(watchdog, 1u);
}

static void test_fake_hal_sends_all_wire_kinds(mcu_test_report_t *report)
{
    unsigned kind;

    hal_host_can_reset();
    check(report, hal_can_init());
    for (kind = 0u; kind < MCU_WIRE_FRAME_KIND_COUNT; kind++) {
        mcu_wire_frame_t original;
        mcu_wire_frame_t decoded;
        hal_can_frame encoded;

        make_frame((mcu_wire_frame_kind_t)kind, &original);
        check(report, mcu_can_bridge_send(&original) == MCU_CAN_BRIDGE_OK);
        check(report, hal_host_can_tx_count() == 1u);
        check(report, hal_host_can_take_tx(&encoded));
        check(report, mcu_can_bridge_decode(&encoded, &decoded) == MCU_CAN_BRIDGE_OK);
        check(report, wire_frames_equal(&original, &decoded));
        check(report, hal_host_can_tx_count() == 0u);
    }
}

static void test_poll_no_frame_and_malformed_input(mcu_test_report_t *report)
{
    mcu_command_dedup_t dedup;
    mcu_state_machine_t machine;
    mcu_watchdog_t watchdog;
    mcu_can_bridge_record_t record;
    mcu_wire_frame_t command;
    hal_can_frame encoded;

    hal_host_can_reset();
    check(report, hal_can_init());
    initialize_core(&dedup, &machine, &watchdog);
    check(report, mcu_command_dedup_open_session(&dedup, true));
    check(report, mcu_can_bridge_poll(&dedup, &machine, &watchdog, 10u, &record));
    check(report, record.outcome == MCU_CAN_BRIDGE_OUTCOME_NO_FRAME);
    check(report, record.status == MCU_CAN_BRIDGE_NO_FRAME);

    make_frame(MCU_WIRE_FRAME_COMMAND, &command);
    check(report, mcu_can_bridge_encode(&command, &encoded) == MCU_CAN_BRIDGE_OK);
    encoded.flags = (uint8_t)HAL_CAN_FRAME_FLAG_REMOTE;
    check(report, hal_host_can_inject_rx(&encoded));
    check(report, mcu_can_bridge_poll(&dedup, &machine, &watchdog, 11u, &record));
    check(report, record.outcome == MCU_CAN_BRIDGE_OUTCOME_REJECTED);
    check(report, record.status == MCU_CAN_BRIDGE_INVALID_FLAGS);
    check(report, !record.request_decoded);
    check(report, !record.response_handed_off);
    check(report, hal_host_can_tx_count() == 0u);
    check(report, machine.state == MCU_STATE_IDLE);
    check(report, !dedup.has_last_accepted);
}

static void test_fake_arbitration_routes_stop_first(mcu_test_report_t *report)
{
    mcu_command_dedup_t dedup;
    mcu_state_machine_t machine;
    mcu_watchdog_t watchdog;
    mcu_can_bridge_record_t record;
    mcu_wire_frame_t command;
    mcu_wire_frame_t stop;
    mcu_wire_frame_t decoded_response;
    hal_can_frame command_encoded;
    hal_can_frame stop_encoded;
    hal_can_frame response_encoded;

    hal_host_can_reset();
    check(report, hal_can_init());
    initialize_core(&dedup, &machine, &watchdog);
    make_frame(MCU_WIRE_FRAME_COMMAND, &command);
    make_frame(MCU_WIRE_FRAME_STOP, &stop);
    check(report, mcu_can_bridge_encode(&command, &command_encoded) == MCU_CAN_BRIDGE_OK);
    check(report, mcu_can_bridge_encode(&stop, &stop_encoded) == MCU_CAN_BRIDGE_OK);
    check(report, command_encoded.arbitration_id > stop_encoded.arbitration_id);

    /* Inject ordinary traffic first. Both are pending before poll, so the
     * fake's deterministic arbitration must still expose STOP first. */
    check(report, hal_host_can_inject_rx(&command_encoded));
    check(report, hal_host_can_inject_rx(&stop_encoded));
    check(report, hal_host_can_rx_count() == 2u);
    check(report, mcu_can_bridge_poll(&dedup, &machine, &watchdog, 20u, &record));
    check(report, record.outcome == MCU_CAN_BRIDGE_OUTCOME_STOP_HANDLED);
    check(report, record.stop_path_entered);
    check(report, record.response_handed_off);
    check(report, machine.state == MCU_STATE_SAFE_STOP);
    check(report, !watchdog.stop_ack_pending);
    check(report, hal_host_can_rx_count() == 1u);
    check(report, hal_host_can_take_tx(&response_encoded));
    check(report, response_encoded.arbitration_id == MCU_CAN_ID_STOP_ACK);
    check(report, mcu_can_bridge_decode(&response_encoded, &decoded_response) == MCU_CAN_BRIDGE_OK);
    check(report, decoded_response.kind == MCU_WIRE_FRAME_STOP_ACK);
    check(report, decoded_response.command_id == stop.command_id);

    /* Ordinary dispatch is still closed, so the queued command cannot undo
     * the STOP or create a response after it is polled. */
    check(report, mcu_can_bridge_poll(&dedup, &machine, &watchdog, 21u, &record));
    check(report, record.outcome == MCU_CAN_BRIDGE_OUTCOME_SESSION_CLOSED);
    check(report, !record.ordinary_event_dispatched);
    check(report, !record.response_available);
    check(report, machine.state == MCU_STATE_SAFE_STOP);
    check(report, hal_host_can_tx_count() == 0u);
}

static void test_poll_stop_ignores_corrupt_dedup(mcu_test_report_t *report)
{
    mcu_command_dedup_t dedup;
    mcu_state_machine_t machine;
    mcu_watchdog_t watchdog;
    mcu_can_bridge_record_t record;
    mcu_wire_frame_t stop;
    hal_can_frame stop_encoded;

    hal_host_can_reset();
    check(report, hal_can_init());
    initialize_core(&dedup, &machine, &watchdog);
    dedup.initialized = 0u;
    make_frame(MCU_WIRE_FRAME_STOP, &stop);
    check(report, mcu_can_bridge_encode(&stop, &stop_encoded) == MCU_CAN_BRIDGE_OK);
    check(report, hal_host_can_inject_rx(&stop_encoded));
    check(report, mcu_can_bridge_poll(&dedup, &machine, &watchdog, 25u, &record));
    check(report, record.outcome == MCU_CAN_BRIDGE_OUTCOME_STOP_HANDLED);
    check(report, record.response_handed_off);
    check(report, machine.state == MCU_STATE_SAFE_STOP);
}

static void test_failed_stop_handoff_remains_pending(mcu_test_report_t *report)
{
    mcu_command_dedup_t dedup;
    mcu_state_machine_t machine;
    mcu_watchdog_t watchdog;
    mcu_can_bridge_record_t record;
    mcu_wire_frame_t stop;
    mcu_wire_frame_t telemetry;
    hal_can_frame stop_encoded;
    hal_can_frame filler;
    unsigned index;

    hal_host_can_reset();
    check(report, hal_can_init());
    initialize_core(&dedup, &machine, &watchdog);
    make_frame(MCU_WIRE_FRAME_STOP, &stop);
    make_frame(MCU_WIRE_FRAME_TELEMETRY, &telemetry);
    check(report, mcu_can_bridge_encode(&stop, &stop_encoded) == MCU_CAN_BRIDGE_OK);
    check(report, mcu_can_bridge_encode(&telemetry, &filler) == MCU_CAN_BRIDGE_OK);
    for (index = 0u; index < HAL_HOST_CAN_QUEUE_CAPACITY; index++) {
        check(report, hal_can_send(&filler));
    }
    check(report, hal_host_can_inject_rx(&stop_encoded));
    check(report, mcu_can_bridge_poll(&dedup, &machine, &watchdog, 30u, &record));
    check(report, record.outcome == MCU_CAN_BRIDGE_OUTCOME_STOP_HANDLED);
    check(report, record.status == MCU_CAN_BRIDGE_HAL_SEND_FAILED);
    check(report, record.response_available);
    check(report, !record.response_handed_off);
    check(report, machine.state == MCU_STATE_SAFE_STOP);
    check(report, watchdog.stop_ack_pending);
    check(report, watchdog.stop_command_id == stop.command_id);
}

void mcu_can_bridge_host_run_tests(mcu_test_report_t *report)
{
    if (report == 0) {
        return;
    }

    report->assertions = 0u;
    report->failures = 0u;
    report->first_failure = 0u;

    test_fake_hal_sends_all_wire_kinds(report);
    test_poll_no_frame_and_malformed_input(report);
    test_fake_arbitration_routes_stop_first(report);
    test_poll_stop_ignores_corrupt_dedup(report);
    test_failed_stop_handoff_remains_pending(report);
}
