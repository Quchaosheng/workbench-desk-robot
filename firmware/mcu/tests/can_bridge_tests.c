#include "can_bridge_tests.h"

#include <stdbool.h>

#include "can_bridge.h"

typedef struct {
    mcu_wire_frame_t frame;
    uint16_t arbitration_id;
} bridge_vector_t;

static const bridge_vector_t bridge_vectors[] = {
    {
        .frame = {
            .kind = MCU_WIRE_FRAME_COMMAND,
            .command_id = 42u,
            .opcode = MCU_WIRE_OPCODE_MOVE,
            .retry_count = 2u,
        },
        .arbitration_id = MCU_CAN_ID_COMMAND,
    },
    {
        .frame = {
            .kind = MCU_WIRE_FRAME_ACK,
            .command_id = 42u,
            .opcode = MCU_WIRE_OPCODE_MOVE,
            .retry_count = 2u,
            .result_code = MCU_WIRE_RESULT_ACCEPTED,
            .fault_code = MCU_WIRE_FAULT_NONE,
            .device_mode = MCU_WIRE_MODE_MOVING,
        },
        .arbitration_id = MCU_CAN_ID_ACK,
    },
    {
        .frame = {
            .kind = MCU_WIRE_FRAME_TELEMETRY,
            .sequence_no = 9u,
            .fault_code = MCU_WIRE_FAULT_NONE,
            .device_mode = MCU_WIRE_MODE_IDLE,
        },
        .arbitration_id = MCU_CAN_ID_TELEMETRY,
    },
    {
        .frame = {
            .kind = MCU_WIRE_FRAME_STOP,
            .command_id = MCU_STOP_ID_MIN,
            .opcode = MCU_WIRE_OPCODE_STOP,
            .retry_count = 1u,
        },
        .arbitration_id = MCU_CAN_ID_STOP,
    },
    {
        .frame = {
            .kind = MCU_WIRE_FRAME_STOP_ACK,
            .command_id = MCU_STOP_ID_MIN,
            .opcode = MCU_WIRE_OPCODE_STOP,
            .retry_count = 1u,
            .result_code = MCU_WIRE_RESULT_ACCEPTED,
            .fault_code = MCU_WIRE_FAULT_NONE,
            .device_mode = MCU_WIRE_MODE_STOPPED,
        },
        .arbitration_id = MCU_CAN_ID_STOP_ACK,
    },
};

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

static void copy_wire_frame(mcu_wire_frame_t *destination,
                            const mcu_wire_frame_t *source)
{
    destination->kind = source->kind;
    destination->command_id = source->command_id;
    destination->sequence_no = source->sequence_no;
    destination->opcode = source->opcode;
    destination->retry_count = source->retry_count;
    destination->result_code = source->result_code;
    destination->fault_code = source->fault_code;
    destination->device_mode = source->device_mode;
}

static bool wire_frames_equal(const mcu_wire_frame_t *left,
                              const mcu_wire_frame_t *right)
{
    return left->kind == right->kind && left->command_id == right->command_id &&
           left->sequence_no == right->sequence_no && left->opcode == right->opcode &&
           left->retry_count == right->retry_count && left->result_code == right->result_code &&
           left->fault_code == right->fault_code && left->device_mode == right->device_mode;
}

static void copy_hal_frame(hal_can_frame *destination,
                           const hal_can_frame *source)
{
    unsigned i;

    destination->arbitration_id = source->arbitration_id;
    destination->dlc = source->dlc;
    destination->flags = source->flags;
    for (i = 0u; i < HAL_CAN_CLASSIC_DLC_MAX; i++) {
        destination->data[i] = source->data[i];
    }
}

static bool hal_frames_equal(const hal_can_frame *left,
                             const hal_can_frame *right)
{
    unsigned i;

    if (left->arbitration_id != right->arbitration_id || left->dlc != right->dlc ||
        left->flags != right->flags) {
        return false;
    }
    for (i = 0u; i < HAL_CAN_CLASSIC_DLC_MAX; i++) {
        if (left->data[i] != right->data[i]) {
            return false;
        }
    }
    return true;
}

static void set_wire_sentinel(mcu_wire_frame_t *frame)
{
    frame->kind = MCU_WIRE_FRAME_KIND_COUNT;
    frame->command_id = 0xa55au;
    frame->sequence_no = 0x5aa55aa5u;
    frame->opcode = MCU_WIRE_OPCODE_COUNT;
    frame->retry_count = 0xa5u;
    frame->result_code = MCU_WIRE_RESULT_COUNT;
    frame->fault_code = MCU_WIRE_FAULT_COUNT;
    frame->device_mode = MCU_WIRE_MODE_COUNT;
}

static void set_hal_sentinel(hal_can_frame *frame)
{
    unsigned i;

    frame->arbitration_id = 0x0555u;
    frame->dlc = 0xa5u;
    frame->flags = 0x5au;
    for (i = 0u; i < HAL_CAN_CLASSIC_DLC_MAX; i++) {
        frame->data[i] = (uint8_t)(0xa0u + i);
    }
}

static void initialize_core(mcu_command_dedup_t *dedup,
                            mcu_state_machine_t *machine,
                            mcu_watchdog_t *watchdog,
                            bool open_session,
                            mcu_test_report_t *report)
{
    mcu_command_dedup_init(dedup);
    mcu_sm_init(machine);
    mcu_watchdog_init(watchdog, 1u);
    if (open_session) {
        check(report, mcu_command_dedup_open_session(dedup, true));
    }
}

static void expect_decode_failure(mcu_test_report_t *report,
                                  const hal_can_frame *encoded,
                                  mcu_can_bridge_status_t expected)
{
    mcu_wire_frame_t decoded;
    mcu_wire_frame_t before;

    set_wire_sentinel(&decoded);
    copy_wire_frame(&before, &decoded);
    check(report, mcu_can_bridge_decode(encoded, &decoded) == expected);
    check(report, wire_frames_equal(&decoded, &before));
}

static void test_all_wire_kinds_round_trip(mcu_test_report_t *report)
{
    unsigned index;

    check(report, HAL_CAN_STANDARD_ID_MAX == 0x07ffu);
    check(report, HAL_CAN_CLASSIC_DLC_MAX == MCU_WIRE_DLC);
    check(report, MCU_CAN_ID_STOP < MCU_CAN_ID_STOP_ACK);
    check(report, MCU_CAN_ID_STOP_ACK < MCU_CAN_ID_COMMAND);
    check(report, MCU_CAN_ID_COMMAND < MCU_CAN_ID_ACK);
    check(report, MCU_CAN_ID_ACK < MCU_CAN_ID_TELEMETRY);

    for (index = 0u; index < sizeof(bridge_vectors) / sizeof(bridge_vectors[0]); index++) {
        hal_can_frame encoded;
        mcu_wire_frame_t decoded;

        set_hal_sentinel(&encoded);
        set_wire_sentinel(&decoded);
        check(report, mcu_can_bridge_encode(&bridge_vectors[index].frame, &encoded) ==
                        MCU_CAN_BRIDGE_OK);
        check(report, encoded.arbitration_id == bridge_vectors[index].arbitration_id);
        check(report, encoded.dlc == MCU_WIRE_DLC);
        check(report, encoded.flags == (uint8_t)HAL_CAN_FRAME_FLAG_NONE);
        check(report, encoded.data[0] == MCU_WIRE_VERSION_V1);
        check(report, mcu_can_bridge_decode(&encoded, &decoded) == MCU_CAN_BRIDGE_OK);
        check(report, wire_frames_equal(&decoded, &bridge_vectors[index].frame));
    }

    {
        hal_can_frame encoded;
        hal_can_frame before;
        mcu_wire_frame_t invalid;

        set_hal_sentinel(&encoded);
        copy_hal_frame(&before, &encoded);
        copy_wire_frame(&invalid, &bridge_vectors[0].frame);
        invalid.command_id = MCU_STOP_ID_MIN;
        check(report, mcu_can_bridge_encode(&invalid, &encoded) ==
                        MCU_CAN_BRIDGE_INVALID_WIRE_FIELD);
        check(report, hal_frames_equal(&encoded, &before));
    }

    check(report, mcu_can_bridge_encode(0, 0) == MCU_CAN_BRIDGE_INVALID_ARGUMENT);
    check(report, mcu_can_bridge_decode(0, 0) == MCU_CAN_BRIDGE_INVALID_ARGUMENT);
}

static void test_raw_envelope_and_wire_rejections(mcu_test_report_t *report)
{
    hal_can_frame valid;
    hal_can_frame invalid;
    unsigned dlc;
    unsigned flags;

    check(report, mcu_can_bridge_encode(&bridge_vectors[0].frame, &valid) == MCU_CAN_BRIDGE_OK);

    for (flags = 1u; flags <= UINT8_MAX; flags++) {
        copy_hal_frame(&invalid, &valid);
        invalid.flags = (uint8_t)flags;
        expect_decode_failure(report, &invalid, MCU_CAN_BRIDGE_INVALID_FLAGS);
    }

    copy_hal_frame(&invalid, &valid);
    invalid.arbitration_id = HAL_CAN_STANDARD_ID_MAX + 1u;
    expect_decode_failure(report, &invalid, MCU_CAN_BRIDGE_INVALID_ARBITRATION_ID);

    for (dlc = 0u; dlc <= UINT8_MAX; dlc++) {
        if (dlc == MCU_WIRE_DLC) {
            continue;
        }
        copy_hal_frame(&invalid, &valid);
        invalid.dlc = (uint8_t)dlc;
        expect_decode_failure(report, &invalid, MCU_CAN_BRIDGE_INVALID_DLC);
    }

    copy_hal_frame(&invalid, &valid);
    invalid.arbitration_id = HAL_CAN_STANDARD_ID_MAX;
    expect_decode_failure(report, &invalid, MCU_CAN_BRIDGE_UNSUPPORTED_ID);

    copy_hal_frame(&invalid, &valid);
    invalid.data[0] = 0x11u;
    expect_decode_failure(report, &invalid, MCU_CAN_BRIDGE_INVALID_VERSION);

    copy_hal_frame(&invalid, &valid);
    invalid.data[5] = 1u;
    expect_decode_failure(report, &invalid, MCU_CAN_BRIDGE_NONZERO_RESERVED);

    copy_hal_frame(&invalid, &valid);
    invalid.data[1] = 0x80u;
    invalid.data[2] = 0x00u;
    expect_decode_failure(report, &invalid, MCU_CAN_BRIDGE_INVALID_WIRE_FIELD);

    copy_hal_frame(&invalid, &valid);
    invalid.data[3] = (uint8_t)MCU_WIRE_OPCODE_STOP;
    expect_decode_failure(report, &invalid, MCU_CAN_BRIDGE_INVALID_WIRE_FIELD);
}

static void check_core_unchanged(mcu_test_report_t *report,
                                 const mcu_command_dedup_t *dedup,
                                 const mcu_state_machine_t *machine,
                                 const mcu_watchdog_t *watchdog)
{
    check(report, mcu_command_dedup_is_valid(dedup));
    check(report, !dedup->has_last_accepted);
    check(report, machine->state == MCU_STATE_IDLE);
    check(report, machine->device_mode == MCU_DEVICE_MODE_IDLE);
    check(report, machine->fault_code == MCU_FAULT_NONE);
    check(report, !watchdog->link_watchdog_armed);
    check(report, !watchdog->stop_ack_pending);
}

static void test_rejected_ingress_has_no_safety_side_effect(mcu_test_report_t *report)
{
    static const unsigned wrong_direction_vectors[] = {1u, 2u, 4u};
    mcu_command_dedup_t dedup;
    mcu_state_machine_t machine;
    mcu_watchdog_t watchdog;
    mcu_can_bridge_record_t record;
    hal_can_frame encoded;
    unsigned index;

    initialize_core(&dedup, &machine, &watchdog, true, report);
    check(report, mcu_can_bridge_encode(&bridge_vectors[0].frame, &encoded) == MCU_CAN_BRIDGE_OK);
    encoded.flags = (uint8_t)HAL_CAN_FRAME_FLAG_EXTENDED_ID;
    check(report, mcu_can_bridge_process_frame(&dedup,
                                               &machine,
                                               &watchdog,
                                               &encoded,
                                               100u,
                                               &record));
    check(report, record.outcome == MCU_CAN_BRIDGE_OUTCOME_REJECTED);
    check(report, record.status == MCU_CAN_BRIDGE_INVALID_FLAGS);
    check(report, !record.request_decoded);
    check(report, !record.response_available);
    check_core_unchanged(report, &dedup, &machine, &watchdog);

    initialize_core(&dedup, &machine, &watchdog, true, report);
    check(report, mcu_can_bridge_encode(&bridge_vectors[0].frame, &encoded) == MCU_CAN_BRIDGE_OK);
    encoded.data[0] = 0x11u;
    check(report, mcu_can_bridge_process_frame(&dedup,
                                               &machine,
                                               &watchdog,
                                               &encoded,
                                               101u,
                                               &record));
    check(report, record.status == MCU_CAN_BRIDGE_INVALID_VERSION);
    check_core_unchanged(report, &dedup, &machine, &watchdog);

    for (index = 0u;
         index < sizeof(wrong_direction_vectors) / sizeof(wrong_direction_vectors[0]);
         index++) {
        initialize_core(&dedup, &machine, &watchdog, true, report);
        check(report,
              mcu_can_bridge_encode(&bridge_vectors[wrong_direction_vectors[index]].frame,
                                    &encoded) == MCU_CAN_BRIDGE_OK);
        check(report, mcu_can_bridge_process_frame(&dedup,
                                                   &machine,
                                                   &watchdog,
                                                   &encoded,
                                                   102u + index,
                                                   &record));
        check(report, record.request_decoded);
        check(report, record.status == MCU_CAN_BRIDGE_UNEXPECTED_DIRECTION);
        check(report, !record.response_available);
        check_core_unchanged(report, &dedup, &machine, &watchdog);
    }

    initialize_core(&dedup, &machine, &watchdog, false, report);
    dedup.initialized = 0u;
    check(report, mcu_can_bridge_encode(&bridge_vectors[0].frame, &encoded) == MCU_CAN_BRIDGE_OK);
    check(report, mcu_can_bridge_process_frame(&dedup,
                                               &machine,
                                               &watchdog,
                                               &encoded,
                                               106u,
                                               &record));
    check(report, record.outcome == MCU_CAN_BRIDGE_OUTCOME_REJECTED);
    check(report, record.status == MCU_CAN_BRIDGE_CORE_REJECTED);
    check(report, !record.ordinary_event_dispatched);
    check(report, !record.response_available);
    check(report, machine.state == MCU_STATE_IDLE);
}

static void test_session_gate_and_valid_command(mcu_test_report_t *report)
{
    mcu_command_dedup_t dedup;
    mcu_state_machine_t machine;
    mcu_watchdog_t watchdog;
    mcu_can_bridge_record_t record;
    hal_can_frame encoded;

    initialize_core(&dedup, &machine, &watchdog, false, report);
    check(report, mcu_can_bridge_encode(&bridge_vectors[0].frame, &encoded) == MCU_CAN_BRIDGE_OK);
    check(report, mcu_can_bridge_process_frame(&dedup,
                                               &machine,
                                               &watchdog,
                                               &encoded,
                                               200u,
                                               &record));
    check(report, record.outcome == MCU_CAN_BRIDGE_OUTCOME_SESSION_CLOSED);
    check(report, record.request_decoded);
    check(report, !record.ordinary_event_dispatched);
    check(report, !record.response_available);
    check(report, machine.state == MCU_STATE_IDLE);

    initialize_core(&dedup, &machine, &watchdog, true, report);
    check(report, mcu_can_bridge_process_frame(&dedup,
                                               &machine,
                                               &watchdog,
                                               &encoded,
                                               201u,
                                               &record));
    check(report, record.outcome == MCU_CAN_BRIDGE_OUTCOME_COMMAND_HANDLED);
    check(report, record.status == MCU_CAN_BRIDGE_OK);
    check(report, record.ordinary_event_dispatched);
    check(report, record.response_available);
    check(report, !record.response_handed_off);
    check(report, record.response.kind == MCU_WIRE_FRAME_ACK);
    check(report, record.response.command_id == bridge_vectors[0].frame.command_id);
    check(report, record.response.result_code == MCU_WIRE_RESULT_ACCEPTED);
    check(report, machine.state == MCU_STATE_EXECUTING);
    check(report, watchdog.link_watchdog_armed);

    check(report, mcu_can_bridge_process_frame(&dedup,
                                               &machine,
                                               &watchdog,
                                               &encoded,
                                               202u,
                                               &record));
    check(report, record.outcome == MCU_CAN_BRIDGE_OUTCOME_COMMAND_HANDLED);
    check(report, !record.ordinary_event_dispatched);
    check(report, record.response.result_code == MCU_WIRE_RESULT_ACCEPTED);
    check(report, machine.state == MCU_STATE_EXECUTING);
    check(report, watchdog.link_deadline_us == 201u + MCU_SOFTWARE_WATCHDOG_TIMEOUT_US);
}

static void test_stop_bypasses_ordinary_session(mcu_test_report_t *report)
{
    mcu_command_dedup_t dedup;
    mcu_state_machine_t machine;
    mcu_watchdog_t watchdog;
    mcu_can_bridge_record_t record;
    hal_can_frame encoded;
    hal_can_frame response;

    initialize_core(&dedup, &machine, &watchdog, false, report);
    check(report, mcu_can_bridge_encode(&bridge_vectors[3].frame, &encoded) == MCU_CAN_BRIDGE_OK);
    check(report, encoded.arbitration_id == MCU_CAN_ID_STOP);
    check(report, encoded.data[1] == 0x80u && encoded.data[2] == 0x00u);
    check(report, mcu_can_bridge_process_frame(&dedup,
                                               &machine,
                                               &watchdog,
                                               &encoded,
                                               300u,
                                               &record));
    check(report, record.outcome == MCU_CAN_BRIDGE_OUTCOME_STOP_HANDLED);
    check(report, record.stop_path_entered);
    check(report, !record.ordinary_event_dispatched);
    check(report, record.response_available);
    check(report, record.response.kind == MCU_WIRE_FRAME_STOP_ACK);
    check(report, record.response.command_id >= MCU_STOP_ID_MIN);
    check(report, machine.state == MCU_STATE_SAFE_STOP);
    check(report, watchdog.stop_ack_pending);
    check(report, mcu_can_bridge_encode(&record.response, &response) == MCU_CAN_BRIDGE_OK);
    check(report, response.arbitration_id == MCU_CAN_ID_STOP_ACK);

    /* Ordinary replay state is not a STOP dependency. A missing dedup object
     * cannot suppress a newly initialized watchdog/state-machine STOP path. */
    mcu_sm_init(&machine);
    mcu_watchdog_init(&watchdog, 2u);
    check(report, mcu_can_bridge_process_frame(0,
                                               &machine,
                                               &watchdog,
                                               &encoded,
                                               301u,
                                               &record));
    check(report, record.outcome == MCU_CAN_BRIDGE_OUTCOME_STOP_HANDLED);
    check(report, record.stop_path_entered);
    check(report, machine.state == MCU_STATE_SAFE_STOP);
}

void mcu_can_bridge_run_tests(mcu_test_report_t *report)
{
    if (report == 0) {
        return;
    }

    report->assertions = 0u;
    report->failures = 0u;
    report->first_failure = 0u;

    test_all_wire_kinds_round_trip(report);
    test_raw_envelope_and_wire_rejections(report);
    test_rejected_ingress_has_no_safety_side_effect(report);
    test_session_gate_and_valid_command(report);
    test_stop_bypasses_ordinary_session(report);
}
