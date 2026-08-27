#include "command_dedup_tests.h"

#include <stdbool.h>

#include "command_dedup.h"

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

static void make_command(mcu_wire_frame_t *command,
                         uint16_t command_id,
                         mcu_wire_opcode_t opcode,
                         uint8_t retry_count)
{
    command->kind = MCU_WIRE_FRAME_COMMAND;
    command->command_id = command_id;
    command->sequence_no = 0u;
    command->opcode = opcode;
    command->retry_count = retry_count;
    command->result_code = MCU_WIRE_RESULT_ACCEPTED;
    command->fault_code = MCU_WIRE_FAULT_NONE;
    command->device_mode = MCU_WIRE_MODE_IDLE;
}

static void make_stop(mcu_wire_frame_t *stop, uint16_t command_id, uint8_t retry_count)
{
    make_command(stop, command_id, MCU_WIRE_OPCODE_STOP, retry_count);
    stop->kind = MCU_WIRE_FRAME_STOP;
}

static void init_open(mcu_command_dedup_t *dedup,
                      mcu_state_machine_t *machine,
                      mcu_watchdog_t *watchdog)
{
    mcu_command_dedup_init(dedup);
    mcu_sm_init(machine);
    mcu_watchdog_init(watchdog, 0u);
    (void)mcu_command_dedup_open_session(dedup, true);
}

static bool receive(mcu_command_dedup_t *dedup,
                    mcu_state_machine_t *machine,
                    mcu_watchdog_t *watchdog,
                    uint16_t command_id,
                    mcu_wire_opcode_t opcode,
                    uint8_t retry_count,
                    uint64_t now_us,
                    mcu_command_record_t *record)
{
    mcu_wire_frame_t command;

    make_command(&command, command_id, opcode, retry_count);
    return mcu_command_dedup_receive(
      dedup, machine, watchdog, &command, now_us, record);
}

static bool ack_is_encodable(const mcu_wire_frame_t *ack)
{
    uint16_t arbitration_id;
    uint8_t encoded[MCU_WIRE_DLC];
    uint8_t encoded_length;

    return mcu_frame_encode(ack,
                            &arbitration_id,
                            encoded,
                            sizeof(encoded),
                            &encoded_length) == MCU_CODEC_OK &&
           arbitration_id == MCU_CAN_ID_ACK && encoded_length == MCU_WIRE_DLC;
}

static bool semantic_ack_equal(const mcu_wire_frame_t *left,
                               const mcu_wire_frame_t *right)
{
    return left->kind == right->kind && left->command_id == right->command_id &&
           left->opcode == right->opcode && left->result_code == right->result_code &&
           left->fault_code == right->fault_code && left->device_mode == right->device_mode;
}

static unsigned valid_entry_count(const mcu_command_dedup_t *dedup)
{
    unsigned count = 0u;
    unsigned i;

    for (i = 0u; i < MCU_COMMAND_REPLAY_WINDOW_SIZE; i++) {
        if (dedup->entries[i].valid) {
            count++;
        }
    }
    return count;
}

static void test_session_gate_and_restart_policy(mcu_test_report_t *report)
{
    mcu_command_dedup_t dedup;
    mcu_state_machine_t machine;
    mcu_watchdog_t watchdog;
    mcu_command_record_t record;

    mcu_command_dedup_init(&dedup);
    mcu_sm_init(&machine);
    mcu_watchdog_init(&watchdog, 0u);
    check(report, mcu_command_dedup_is_valid(&dedup));
    check(report, sizeof(dedup) <= MCU_COMMAND_DEDUP_STORAGE_BUDGET_BYTES);
    check(report,
          receive(&dedup,
                  &machine,
                  &watchdog,
                  73u,
                  MCU_WIRE_OPCODE_HEARTBEAT,
                  0u,
                  1u,
                  &record));
    check(report, record.outcome == MCU_COMMAND_OUTCOME_SESSION_CLOSED);
    check(report, !record.ack_available);
    check(report, !record.ordinary_event_dispatched);
    check(report, machine.state == MCU_STATE_IDLE);
    check(report, !dedup.has_last_accepted);

    check(report, !mcu_command_dedup_open_session(&dedup, false));
    check(report, !dedup.session_open);
    check(report, mcu_command_dedup_open_session(&dedup, true));
    check(report, !mcu_command_dedup_open_session(&dedup, true));
    check(report,
          receive(&dedup,
                  &machine,
                  &watchdog,
                  73u,
                  MCU_WIRE_OPCODE_HEARTBEAT,
                  0u,
                  2u,
                  &record));
    check(report, record.outcome == MCU_COMMAND_OUTCOME_ACCEPTED_NEW);
    check(report, dedup.has_last_accepted && dedup.last_accepted_id == 73u);

    check(report, mcu_command_dedup_close_session(&dedup));
    check(report, mcu_command_dedup_is_valid(&dedup));
    check(report, !dedup.session_open && !dedup.has_last_accepted);
    check(report, valid_entry_count(&dedup) == 0u);
    check(report,
          receive(&dedup,
                  &machine,
                  &watchdog,
                  73u,
                  MCU_WIRE_OPCODE_HEARTBEAT,
                  0u,
                  3u,
                  &record));
    check(report, record.outcome == MCU_COMMAND_OUTCOME_SESSION_CLOSED);

    /* The trusted transport has discarded old queued traffic, so an ID may
     * become the first serial of the new session. */
    check(report, mcu_command_dedup_open_session(&dedup, true));
    check(report,
          receive(&dedup,
                  &machine,
                  &watchdog,
                  73u,
                  MCU_WIRE_OPCODE_HEARTBEAT,
                  0u,
                  4u,
                  &record));
    check(report, record.outcome == MCU_COMMAND_OUTCOME_ACCEPTED_NEW);
}

static void test_first_command_opcode_mapping(mcu_test_report_t *report)
{
    static const mcu_wire_opcode_t opcodes[] = {
        MCU_WIRE_OPCODE_MOVE,
        MCU_WIRE_OPCODE_GRIP_OPEN,
        MCU_WIRE_OPCODE_GRIP_CLOSE,
        MCU_WIRE_OPCODE_HOLD,
        MCU_WIRE_OPCODE_HEARTBEAT,
    };
    static const mcu_wire_device_mode_t modes[] = {
        MCU_WIRE_MODE_MOVING,
        MCU_WIRE_MODE_MOVING,
        MCU_WIRE_MODE_MOVING,
        MCU_WIRE_MODE_HOLDING,
        MCU_WIRE_MODE_IDLE,
    };
    unsigned i;

    for (i = 0u; i < sizeof(opcodes) / sizeof(opcodes[0]); i++) {
        mcu_command_dedup_t dedup;
        mcu_state_machine_t machine;
        mcu_watchdog_t watchdog;
        mcu_command_record_t record;

        init_open(&dedup, &machine, &watchdog);
        check(report,
              receive(&dedup,
                      &machine,
                      &watchdog,
                      (uint16_t)(100u + i),
                      opcodes[i],
                      0u,
                      1000u,
                      &record));
        check(report, record.outcome == MCU_COMMAND_OUTCOME_ACCEPTED_NEW);
        check(report, record.ack_available);
        check(report, record.ordinary_event_dispatched);
        check(report, record.ack.result_code == MCU_WIRE_RESULT_ACCEPTED);
        check(report, record.ack.fault_code == MCU_WIRE_FAULT_NONE);
        check(report, record.ack.device_mode == modes[i]);
        check(report, ack_is_encodable(&record.ack));
        check(report,
              record.watchdog_refreshed ==
                (opcodes[i] != MCU_WIRE_OPCODE_HEARTBEAT));
        check(report, mcu_command_dedup_is_valid(&dedup));
    }
}

static void test_duplicate_and_retry_replay_once(mcu_test_report_t *report)
{
    mcu_command_dedup_t dedup;
    mcu_state_machine_t machine;
    mcu_watchdog_t watchdog;
    mcu_command_record_t first;
    mcu_command_record_t replay;
    uint64_t deadline;

    init_open(&dedup, &machine, &watchdog);
    check(report,
          receive(&dedup,
                  &machine,
                  &watchdog,
                  100u,
                  MCU_WIRE_OPCODE_MOVE,
                  0u,
                  1000u,
                  &first));
    check(report, first.outcome == MCU_COMMAND_OUTCOME_ACCEPTED_NEW);
    check(report, machine.state == MCU_STATE_EXECUTING);
    check(report, watchdog.link_watchdog_armed);
    deadline = watchdog.link_deadline_us;

    check(report,
          receive(&dedup,
                  &machine,
                  &watchdog,
                  100u,
                  MCU_WIRE_OPCODE_MOVE,
                  0u,
                  2000u,
                  &replay));
    check(report, replay.outcome == MCU_COMMAND_OUTCOME_REPLAYED);
    check(report, !replay.ordinary_event_dispatched);
    check(report, !replay.watchdog_refreshed);
    check(report, semantic_ack_equal(&first.ack, &replay.ack));
    check(report, replay.ack.retry_count == 0u);
    check(report, watchdog.link_deadline_us == deadline);
    check(report, machine.state == MCU_STATE_EXECUTING);

    check(report,
          receive(&dedup,
                  &machine,
                  &watchdog,
                  100u,
                  MCU_WIRE_OPCODE_MOVE,
                  1u,
                  3000u,
                  &replay));
    check(report, replay.outcome == MCU_COMMAND_OUTCOME_REPLAYED);
    check(report, replay.ack.retry_count == 1u);
    check(report, semantic_ack_equal(&first.ack, &replay.ack));
    check(report, watchdog.link_deadline_us == deadline);

    check(report,
          receive(&dedup,
                  &machine,
                  &watchdog,
                  100u,
                  MCU_WIRE_OPCODE_MOVE,
                  0u,
                  4000u,
                  &replay));
    check(report, replay.outcome == MCU_COMMAND_OUTCOME_REJECTED_RETRY);
    check(report, !replay.ordinary_event_dispatched);
    check(report, replay.ack.result_code == MCU_WIRE_RESULT_REJECTED);
    check(report, replay.ack.fault_code == MCU_WIRE_FAULT_DUPLICATE_FRAME);
    check(report, replay.ack.device_mode == MCU_WIRE_MODE_FAULTED);
    check(report, machine.state == MCU_STATE_FAULT);
    check(report, machine.fault_code == MCU_FAULT_DUPLICATE_FRAME);
    check(report, watchdog.link_deadline_us == deadline);
    check(report, !watchdog.link_watchdog_armed);

    /* The original semantic result remains immutable after the rejection. */
    check(report,
          receive(&dedup,
                  &machine,
                  &watchdog,
                  100u,
                  MCU_WIRE_OPCODE_MOVE,
                  2u,
                  5000u,
                  &replay));
    check(report, replay.outcome == MCU_COMMAND_OUTCOME_REPLAYED);
    check(report, semantic_ack_equal(&first.ack, &replay.ack));
    check(report, replay.ack.retry_count == 2u);
    check(report, machine.state == MCU_STATE_FAULT);
}

static void test_retry_count_does_not_wrap(mcu_test_report_t *report)
{
    mcu_command_dedup_t dedup;
    mcu_state_machine_t machine;
    mcu_watchdog_t watchdog;
    mcu_command_record_t record;

    init_open(&dedup, &machine, &watchdog);
    check(report,
          receive(&dedup,
                  &machine,
                  &watchdog,
                  1u,
                  MCU_WIRE_OPCODE_HEARTBEAT,
                  254u,
                  1u,
                  &record));
    check(report, record.outcome == MCU_COMMAND_OUTCOME_ACCEPTED_NEW);
    check(report,
          receive(&dedup,
                  &machine,
                  &watchdog,
                  1u,
                  MCU_WIRE_OPCODE_HEARTBEAT,
                  255u,
                  2u,
                  &record));
    check(report, record.outcome == MCU_COMMAND_OUTCOME_REPLAYED);
    check(report,
          receive(&dedup,
                  &machine,
                  &watchdog,
                  1u,
                  MCU_WIRE_OPCODE_HEARTBEAT,
                  0u,
                  3u,
                  &record));
    check(report, record.outcome == MCU_COMMAND_OUTCOME_REJECTED_RETRY);
    check(report, record.ack.fault_code == MCU_WIRE_FAULT_DUPLICATE_FRAME);
}

static void test_conflicting_duplicate_fails_closed(mcu_test_report_t *report)
{
    mcu_command_dedup_t dedup;
    mcu_state_machine_t machine;
    mcu_watchdog_t watchdog;
    mcu_command_record_t first;
    mcu_command_record_t conflict;
    mcu_command_record_t replay;

    init_open(&dedup, &machine, &watchdog);
    check(report,
          receive(&dedup,
                  &machine,
                  &watchdog,
                  5u,
                  MCU_WIRE_OPCODE_HEARTBEAT,
                  0u,
                  1u,
                  &first));
    check(report,
          receive(&dedup,
                  &machine,
                  &watchdog,
                  5u,
                  MCU_WIRE_OPCODE_HOLD,
                  0u,
                  2u,
                  &conflict));
    check(report, conflict.outcome == MCU_COMMAND_OUTCOME_REJECTED_CONFLICT);
    check(report, !conflict.ordinary_event_dispatched);
    check(report, conflict.ack.result_code == MCU_WIRE_RESULT_REJECTED);
    check(report, conflict.ack.fault_code == MCU_WIRE_FAULT_DUPLICATE_FRAME);
    check(report, machine.state == MCU_STATE_FAULT);
    check(report, machine.fault_code == MCU_FAULT_DUPLICATE_FRAME);

    check(report,
          receive(&dedup,
                  &machine,
                  &watchdog,
                  5u,
                  MCU_WIRE_OPCODE_HEARTBEAT,
                  1u,
                  3u,
                  &replay));
    check(report, replay.outcome == MCU_COMMAND_OUTCOME_REPLAYED);
    check(report, semantic_ack_equal(&first.ack, &replay.ack));
    check(report, !replay.ordinary_event_dispatched);
}

static void test_rejected_new_result_is_replayed(mcu_test_report_t *report)
{
    mcu_command_dedup_t dedup;
    mcu_state_machine_t machine;
    mcu_watchdog_t watchdog;
    mcu_command_record_t first;
    mcu_command_record_t replay;
    mcu_event_t stop;
    mcu_transition_result_t transition;

    init_open(&dedup, &machine, &watchdog);
    stop.kind = MCU_EVENT_STOP;
    stop.fault_code = MCU_FAULT_NONE;
    stop.reset_authorized = false;
    stop.cause_cleared = false;
    mcu_sm_dispatch(&machine, &stop, &transition);
    check(report, machine.state == MCU_STATE_SAFE_STOP);

    check(report,
          receive(&dedup,
                  &machine,
                  &watchdog,
                  90u,
                  MCU_WIRE_OPCODE_MOVE,
                  0u,
                  1u,
                  &first));
    check(report, first.outcome == MCU_COMMAND_OUTCOME_REJECTED_NEW);
    check(report, first.ordinary_event_dispatched);
    check(report, first.ack.result_code == MCU_WIRE_RESULT_REJECTED);
    check(report, first.ack.fault_code == MCU_WIRE_FAULT_MALFORMED_FRAME);
    check(report, machine.state == MCU_STATE_FAULT);

    check(report,
          receive(&dedup,
                  &machine,
                  &watchdog,
                  90u,
                  MCU_WIRE_OPCODE_MOVE,
                  1u,
                  2u,
                  &replay));
    check(report, replay.outcome == MCU_COMMAND_OUTCOME_REPLAYED);
    check(report, !replay.ordinary_event_dispatched);
    check(report, semantic_ack_equal(&first.ack, &replay.ack));
}

static void test_fixed_window_and_eviction(mcu_test_report_t *report)
{
    mcu_command_dedup_t dedup;
    mcu_state_machine_t machine;
    mcu_watchdog_t watchdog;
    mcu_command_record_t record;
    unsigned i;

    init_open(&dedup, &machine, &watchdog);
    for (i = 0u; i < MCU_COMMAND_REPLAY_WINDOW_SIZE; i++) {
        check(report,
              receive(&dedup,
                      &machine,
                      &watchdog,
                      (uint16_t)(100u + i),
                      MCU_WIRE_OPCODE_HEARTBEAT,
                      0u,
                      i,
                      &record));
        check(report, record.outcome == MCU_COMMAND_OUTCOME_ACCEPTED_NEW);
    }
    check(report, valid_entry_count(&dedup) == MCU_COMMAND_REPLAY_WINDOW_SIZE);

    check(report,
          receive(&dedup,
                  &machine,
                  &watchdog,
                  100u,
                  MCU_WIRE_OPCODE_HEARTBEAT,
                  1u,
                  20u,
                  &record));
    check(report, record.outcome == MCU_COMMAND_OUTCOME_REPLAYED);

    check(report,
          receive(&dedup,
                  &machine,
                  &watchdog,
                  108u,
                  MCU_WIRE_OPCODE_HEARTBEAT,
                  0u,
                  21u,
                  &record));
    check(report, record.outcome == MCU_COMMAND_OUTCOME_ACCEPTED_NEW);
    check(report, valid_entry_count(&dedup) == MCU_COMMAND_REPLAY_WINDOW_SIZE);

    check(report,
          receive(&dedup,
                  &machine,
                  &watchdog,
                  100u,
                  MCU_WIRE_OPCODE_HEARTBEAT,
                  2u,
                  22u,
                  &record));
    check(report, record.outcome == MCU_COMMAND_OUTCOME_REJECTED_STALE);
    check(report, record.ack.fault_code == MCU_WIRE_FAULT_DUPLICATE_FRAME);
    check(report, machine.state == MCU_STATE_FAULT);
}

static void test_all_serial_deltas(mcu_test_report_t *report)
{
    const uint16_t last = 12345u;
    uint32_t candidate;

    for (candidate = 0u; candidate <= MCU_COMMAND_ID_MAX; candidate++) {
        mcu_command_dedup_t dedup;
        mcu_state_machine_t machine;
        mcu_watchdog_t watchdog;
        mcu_command_record_t record;
        uint16_t delta = (uint16_t)(((uint16_t)candidate - last) & MCU_COMMAND_SERIAL_MASK);

        init_open(&dedup, &machine, &watchdog);
        (void)receive(&dedup,
                      &machine,
                      &watchdog,
                      last,
                      MCU_WIRE_OPCODE_HEARTBEAT,
                      0u,
                      1u,
                      &record);
        check(report,
              receive(&dedup,
                      &machine,
                      &watchdog,
                      (uint16_t)candidate,
                      MCU_WIRE_OPCODE_HEARTBEAT,
                      0u,
                      2u,
                      &record));
        if (delta == 0u) {
            check(report, record.outcome == MCU_COMMAND_OUTCOME_REPLAYED);
        } else if (delta < MCU_COMMAND_SERIAL_HALF_RANGE) {
            check(report, record.outcome == MCU_COMMAND_OUTCOME_ACCEPTED_NEW);
        } else {
            check(report, record.outcome == MCU_COMMAND_OUTCOME_REJECTED_STALE);
        }
    }
}

static void test_wrap_boundaries_and_old_epoch_rejection(mcu_test_report_t *report)
{
    mcu_command_dedup_t dedup;
    mcu_state_machine_t machine;
    mcu_watchdog_t watchdog;
    mcu_command_record_t record;

    init_open(&dedup, &machine, &watchdog);
    check(report,
          receive(&dedup,
                  &machine,
                  &watchdog,
                  32766u,
                  MCU_WIRE_OPCODE_HEARTBEAT,
                  0u,
                  1u,
                  &record));
    check(report, record.outcome == MCU_COMMAND_OUTCOME_ACCEPTED_NEW);
    check(report,
          receive(&dedup,
                  &machine,
                  &watchdog,
                  32767u,
                  MCU_WIRE_OPCODE_HEARTBEAT,
                  0u,
                  2u,
                  &record));
    check(report, record.outcome == MCU_COMMAND_OUTCOME_ACCEPTED_NEW);
    check(report,
          receive(&dedup,
                  &machine,
                  &watchdog,
                  0u,
                  MCU_WIRE_OPCODE_HEARTBEAT,
                  0u,
                  3u,
                  &record));
    check(report, record.outcome == MCU_COMMAND_OUTCOME_ACCEPTED_NEW);
    check(report, valid_entry_count(&dedup) == 1u);
    check(report, dedup.last_accepted_id == 0u);
    check(report,
          receive(&dedup,
                  &machine,
                  &watchdog,
                  1u,
                  MCU_WIRE_OPCODE_HEARTBEAT,
                  0u,
                  4u,
                  &record));
    check(report, record.outcome == MCU_COMMAND_OUTCOME_ACCEPTED_NEW);

    init_open(&dedup, &machine, &watchdog);
    (void)receive(&dedup,
                  &machine,
                  &watchdog,
                  32767u,
                  MCU_WIRE_OPCODE_HEARTBEAT,
                  0u,
                  1u,
                  &record);
    (void)receive(&dedup,
                  &machine,
                  &watchdog,
                  0u,
                  MCU_WIRE_OPCODE_HEARTBEAT,
                  0u,
                  2u,
                  &record);
    check(report,
          receive(&dedup,
                  &machine,
                  &watchdog,
                  32767u,
                  MCU_WIRE_OPCODE_HEARTBEAT,
                  1u,
                  3u,
                  &record));
    check(report, record.outcome == MCU_COMMAND_OUTCOME_REJECTED_STALE);
    check(report, record.ack.fault_code == MCU_WIRE_FAULT_DUPLICATE_FRAME);
}

static void test_forward_wrap_beats_same_numeric_cached_id(mcu_test_report_t *report)
{
    static const uint16_t serials[] = {
        0u, 5000u, 10000u, 15000u, 20000u, 25000u, 30000u, 32767u,
    };
    mcu_command_dedup_t dedup;
    mcu_state_machine_t machine;
    mcu_watchdog_t watchdog;
    mcu_command_record_t record;
    unsigned i;

    init_open(&dedup, &machine, &watchdog);
    for (i = 0u; i < sizeof(serials) / sizeof(serials[0]); i++) {
        check(report,
              receive(&dedup,
                      &machine,
                      &watchdog,
                      serials[i],
                      MCU_WIRE_OPCODE_HEARTBEAT,
                      0u,
                      i,
                      &record));
        check(report, record.outcome == MCU_COMMAND_OUTCOME_ACCEPTED_NEW);
    }
    check(report, valid_entry_count(&dedup) == MCU_COMMAND_REPLAY_WINDOW_SIZE);

    check(report,
          receive(&dedup,
                  &machine,
                  &watchdog,
                  0u,
                  MCU_WIRE_OPCODE_HEARTBEAT,
                  0u,
                  20u,
                  &record));
    check(report, record.outcome == MCU_COMMAND_OUTCOME_ACCEPTED_NEW);
    check(report, record.ordinary_event_dispatched);
    check(report, valid_entry_count(&dedup) == 1u);
    check(report, dedup.last_accepted_id == 0u);
}

static void test_stop_bypasses_full_ordinary_window(mcu_test_report_t *report)
{
    mcu_command_dedup_t dedup;
    mcu_state_machine_t machine;
    mcu_watchdog_t watchdog;
    mcu_command_record_t command_record;
    mcu_watchdog_record_t first_stop;
    mcu_watchdog_record_t duplicate_stop;
    mcu_wire_frame_t stop;
    unsigned i;

    init_open(&dedup, &machine, &watchdog);
    for (i = 0u; i < MCU_COMMAND_REPLAY_WINDOW_SIZE; i++) {
        (void)receive(&dedup,
                      &machine,
                      &watchdog,
                      (uint16_t)i,
                      MCU_WIRE_OPCODE_HEARTBEAT,
                      0u,
                      i,
                      &command_record);
    }
    check(report, valid_entry_count(&dedup) == MCU_COMMAND_REPLAY_WINDOW_SIZE);

    make_stop(&stop, MCU_STOP_ID_MIN + 61u, 0u);
    check(report,
          mcu_watchdog_receive_stop(&watchdog, &machine, &stop, 100u, &first_stop));
    check(report, machine.state == MCU_STATE_SAFE_STOP);
    check(report, first_stop.kind == MCU_WATCHDOG_RECORD_STOP_ACK);
    check(report, first_stop.frame.result_code == MCU_WIRE_RESULT_ACCEPTED);
    check(report, valid_entry_count(&dedup) == MCU_COMMAND_REPLAY_WINDOW_SIZE);

    check(report,
          mcu_watchdog_receive_stop(
            &watchdog, &machine, &stop, 101u, &duplicate_stop));
    check(report, machine.state == MCU_STATE_SAFE_STOP);
    check(report, duplicate_stop.frame.result_code == MCU_WIRE_RESULT_ACCEPTED);

    check(report, duplicate_stop.observed_at_us == first_stop.observed_at_us);
    check(report, duplicate_stop.deadline_us == first_stop.deadline_us);
    check(report,
          mcu_watchdog_confirm_stop_ack(&watchdog,
                                        stop.command_id,
                                        stop.retry_count,
                                        duplicate_stop.deadline_us));
    check(report,
          mcu_watchdog_receive_stop(
            &watchdog, &machine, &stop, 102u, &duplicate_stop));
    check(report, machine.state == MCU_STATE_SAFE_STOP);
    check(report, duplicate_stop.frame.result_code == MCU_WIRE_RESULT_ACCEPTED);

    /* Boot/session gating is ordinary-command-only. */
    mcu_command_dedup_init(&dedup);
    mcu_sm_init(&machine);
    mcu_watchdog_init(&watchdog, 0u);
    make_stop(&stop, MCU_STOP_ID_MIN + 63u, 0u);
    check(report, !dedup.session_open);
    check(report,
          mcu_watchdog_receive_stop(
            &watchdog, &machine, &stop, 200u, &duplicate_stop));
    check(report, machine.state == MCU_STATE_SAFE_STOP);
    check(report, duplicate_stop.frame.result_code == MCU_WIRE_RESULT_ACCEPTED);
}

static void test_trusted_reset_preserves_replay_history(mcu_test_report_t *report)
{
    mcu_command_dedup_t dedup;
    mcu_state_machine_t machine;
    mcu_watchdog_t watchdog;
    mcu_command_record_t first;
    mcu_command_record_t replay;
    mcu_watchdog_record_t stop_record;
    mcu_wire_frame_t stop;
    mcu_transition_result_t reset;

    init_open(&dedup, &machine, &watchdog);
    check(report,
          receive(&dedup,
                  &machine,
                  &watchdog,
                  42u,
                  MCU_WIRE_OPCODE_MOVE,
                  0u,
                  1u,
                  &first));
    make_stop(&stop, MCU_STOP_ID_MIN + 62u, 0u);
    check(report,
          mcu_watchdog_receive_stop(&watchdog, &machine, &stop, 2u, &stop_record));
    check(report,
          mcu_watchdog_confirm_stop_ack(
            &watchdog, stop.command_id, stop.retry_count, stop_record.deadline_us));
    check(report,
          mcu_watchdog_request_reset(
            &watchdog, &machine, true, true, &reset));
    check(report, machine.state == MCU_STATE_IDLE);
    check(report, dedup.has_last_accepted && dedup.last_accepted_id == 42u);

    check(report,
          receive(&dedup,
                  &machine,
                  &watchdog,
                  42u,
                  MCU_WIRE_OPCODE_MOVE,
                  1u,
                  3u,
                  &replay));
    check(report, replay.outcome == MCU_COMMAND_OUTCOME_REPLAYED);
    check(report, !replay.ordinary_event_dispatched);
    check(report, semantic_ack_equal(&first.ack, &replay.ack));
    check(report, machine.state == MCU_STATE_IDLE);
    check(report, !watchdog.link_watchdog_armed);
}

static void test_invalid_input_and_corruption(mcu_test_report_t *report)
{
    mcu_command_dedup_t dedup;
    mcu_state_machine_t machine;
    mcu_watchdog_t watchdog;
    mcu_command_record_t record;
    mcu_wire_frame_t command;

    init_open(&dedup, &machine, &watchdog);
    make_command(&command, 1u, MCU_WIRE_OPCODE_HEARTBEAT, 0u);
    record.outcome = MCU_COMMAND_OUTCOME_COUNT;
    check(report,
          !mcu_command_dedup_receive(
            0, &machine, &watchdog, &command, 0u, &record));
    check(report, record.outcome == MCU_COMMAND_OUTCOME_COUNT);
    check(report,
          !mcu_command_dedup_receive(
            &dedup, 0, &watchdog, &command, 0u, &record));
    check(report,
          !mcu_command_dedup_receive(
            &dedup, &machine, 0, &command, 0u, &record));
    check(report,
          !mcu_command_dedup_receive(
            &dedup, &machine, &watchdog, 0, 0u, &record));
    check(report,
          !mcu_command_dedup_receive(
            &dedup, &machine, &watchdog, &command, 0u, 0));

    command.kind = MCU_WIRE_FRAME_STOP;
    command.command_id = MCU_STOP_ID_MIN;
    command.opcode = MCU_WIRE_OPCODE_STOP;
    check(report,
          !mcu_command_dedup_receive(
            &dedup, &machine, &watchdog, &command, 0u, &record));
    check(report, record.outcome == MCU_COMMAND_OUTCOME_COUNT);

    dedup.initialized = 0u;
    check(report, !mcu_command_dedup_is_valid(&dedup));
    check(report,
          !mcu_command_dedup_receive(
            &dedup, &machine, &watchdog, &command, 0u, &record));
    check(report, record.outcome == MCU_COMMAND_OUTCOME_COUNT);

    mcu_command_dedup_init(0);
    check(report, !mcu_command_dedup_is_valid(0));
    check(report, !mcu_command_dedup_open_session(0, true));
    check(report, !mcu_command_dedup_close_session(0));
}

void mcu_command_dedup_run_tests(mcu_test_report_t *report)
{
    report->assertions = 0u;
    report->failures = 0u;
    report->first_failure = 0u;

    test_session_gate_and_restart_policy(report);
    test_first_command_opcode_mapping(report);
    test_duplicate_and_retry_replay_once(report);
    test_retry_count_does_not_wrap(report);
    test_conflicting_duplicate_fails_closed(report);
    test_rejected_new_result_is_replayed(report);
    test_fixed_window_and_eviction(report);
    test_all_serial_deltas(report);
    test_wrap_boundaries_and_old_epoch_rejection(report);
    test_forward_wrap_beats_same_numeric_cached_id(report);
    test_stop_bypasses_full_ordinary_window(report);
    test_trusted_reset_preserves_replay_history(report);
    test_invalid_input_and_corruption(report);
}
