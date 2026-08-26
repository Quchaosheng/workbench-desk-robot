#include "watchdog.h"

#define MCU_WATCHDOG_COOKIE 0x57445431u
#define MCU_TIME_HALF_RANGE (UINT64_C(1) << 63)

static bool deadline_reached(uint64_t now_us, uint64_t deadline_us)
{
    return (uint64_t)(now_us - deadline_us) < MCU_TIME_HALF_RANGE;
}

static bool deadline_after(uint64_t now_us, uint64_t deadline_us)
{
    uint64_t delta = now_us - deadline_us;

    return delta != 0u && delta < MCU_TIME_HALF_RANGE;
}

static void clear_frame(mcu_wire_frame_t *frame)
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

static void copy_frame(mcu_wire_frame_t *destination, const mcu_wire_frame_t *source)
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

static void clear_stop_ack_cache(mcu_watchdog_t *watchdog)
{
    watchdog->stop_ack_observed_at_us = 0u;
    clear_frame(&watchdog->stop_ack_frame);
}

static void cache_stop_ack(mcu_watchdog_t *watchdog,
                           const mcu_watchdog_record_t *record)
{
    watchdog->stop_ack_observed_at_us = record->observed_at_us;
    copy_frame(&watchdog->stop_ack_frame, &record->frame);
}

static void clear_record(mcu_watchdog_record_t *record)
{
    record->kind = MCU_WATCHDOG_RECORD_NONE;
    record->fault = MCU_WATCHDOG_FAULT_NONE;
    record->observed_at_us = 0u;
    record->deadline_us = 0u;
    record->command_id = 0u;
    record->retry_count = 0u;
    clear_frame(&record->frame);
}

static bool activity_is_valid(mcu_watchdog_activity_t activity)
{
    return activity >= MCU_WATCHDOG_ACTIVITY_VALID_NEW && activity < MCU_WATCHDOG_ACTIVITY_COUNT;
}

static bool stop_matches_pending(const mcu_watchdog_t *watchdog,
                                 const mcu_wire_frame_t *stop)
{
    /* retry_count is attempt metadata, not part of STOP command semantics.
     * Equal counts are link-level replays and strictly greater counts are
     * protocol retries. A pending uint8_t retry sequence does not wrap: a
     * lower count is stale and must not roll back the correlation slot. */
    return watchdog->stop_ack_pending && watchdog->stop_command_id == stop->command_id &&
           stop->retry_count >= watchdog->stop_retry_count;
}

static mcu_wire_fault_t map_fault(mcu_fault_code_t fault_code)
{
    switch (fault_code) {
    case MCU_FAULT_STOP_REJECTED:
        return MCU_WIRE_FAULT_STOP_REJECTED;
    case MCU_FAULT_LINK_LOST:
        return MCU_WIRE_FAULT_LINK_LOST;
    case MCU_FAULT_DUPLICATE_FRAME:
        return MCU_WIRE_FAULT_DUPLICATE_FRAME;
    case MCU_FAULT_WATCHDOG_EXPIRED:
        return MCU_WIRE_FAULT_WATCHDOG_EXPIRED;
    case MCU_FAULT_MALFORMED_FRAME:
        return MCU_WIRE_FAULT_MALFORMED_FRAME;
    case MCU_FAULT_NONE:
    case MCU_FAULT_COUNT:
    default:
        return MCU_WIRE_FAULT_NONE;
    }
}

static void make_watchdog_telemetry(mcu_watchdog_t *watchdog,
                                    uint64_t now_us,
                                    uint64_t deadline_us,
                                    mcu_watchdog_record_t *record)
{
    clear_record(record);
    record->kind = MCU_WATCHDOG_RECORD_FAULT_TELEMETRY;
    record->fault = MCU_WATCHDOG_FAULT_WATCHDOG_EXPIRED;
    record->observed_at_us = now_us;
    record->deadline_us = deadline_us;
    record->frame.kind = MCU_WIRE_FRAME_TELEMETRY;
    record->frame.sequence_no = watchdog->next_telemetry_sequence++;
    record->frame.fault_code = MCU_WIRE_FAULT_WATCHDOG_EXPIRED;
    record->frame.device_mode = MCU_WIRE_MODE_FAULTED;
}

static void make_stop_ack(const mcu_wire_frame_t *stop,
                          const mcu_transition_result_t *transition,
                          uint64_t now_us,
                          uint64_t deadline_us,
                          mcu_watchdog_record_t *record)
{
    clear_record(record);
    record->kind = MCU_WATCHDOG_RECORD_STOP_ACK;
    record->fault = MCU_WATCHDOG_FAULT_NONE;
    record->observed_at_us = now_us;
    record->deadline_us = deadline_us;
    record->command_id = stop->command_id;
    record->retry_count = stop->retry_count;
    record->frame.kind = MCU_WIRE_FRAME_STOP_ACK;
    record->frame.command_id = stop->command_id;
    record->frame.opcode = MCU_WIRE_OPCODE_STOP;
    record->frame.retry_count = stop->retry_count;
    record->frame.result_code = transition->result_code == MCU_RESULT_ACCEPTED
                                    ? MCU_WIRE_RESULT_ACCEPTED
                                    : MCU_WIRE_RESULT_REJECTED;
    record->frame.fault_code = map_fault(transition->response_fault_code);
    record->frame.device_mode = transition->device_mode == MCU_DEVICE_MODE_FAULTED
                                    ? MCU_WIRE_MODE_FAULTED
                                    : MCU_WIRE_MODE_STOPPED;
}

static void replay_pending_stop_ack(mcu_watchdog_t *watchdog,
                                    const mcu_wire_frame_t *stop,
                                    uint64_t now_us,
                                    mcu_watchdog_record_t *record)
{
    bool exact_retry = watchdog->stop_retry_count == stop->retry_count;

    clear_record(record);
    record->kind = MCU_WATCHDOG_RECORD_STOP_ACK;
    record->fault = MCU_WATCHDOG_FAULT_NONE;
    record->observed_at_us = exact_retry ? watchdog->stop_ack_observed_at_us : now_us;
    record->deadline_us = watchdog->stop_deadline_us;
    record->command_id = watchdog->stop_command_id;
    record->retry_count = stop->retry_count;
    copy_frame(&record->frame, &watchdog->stop_ack_frame);
    /* Preserve the original result/fault/device mode while echoing the
     * attempt metadata carried by a protocol-level retry. */
    record->frame.retry_count = stop->retry_count;
    if (!exact_retry) {
        /* The next exact link retry must replay this most recently emitted
         * attempt, while the semantic response fields remain immutable. */
        watchdog->stop_ack_observed_at_us = now_us;
        watchdog->stop_ack_frame.retry_count = stop->retry_count;
    }
    watchdog->stop_retry_count = stop->retry_count;
}

void mcu_watchdog_init(mcu_watchdog_t *watchdog, uint32_t first_telemetry_sequence)
{
    if (watchdog == 0) {
        return;
    }

    watchdog->initialized = MCU_WATCHDOG_COOKIE;
    watchdog->next_telemetry_sequence = first_telemetry_sequence;
    watchdog->link_watchdog_armed = false;
    watchdog->watchdog_cause_active = false;
    watchdog->watchdog_record_emitted = false;
    watchdog->link_deadline_us = 0u;
    watchdog->stop_ack_pending = false;
    watchdog->stop_timeout_cause_active = false;
    watchdog->stop_timeout_record_emitted = false;
    watchdog->stop_deadline_us = 0u;
    watchdog->stop_command_id = 0u;
    watchdog->stop_retry_count = 0u;
    clear_stop_ack_cache(watchdog);
}

bool mcu_watchdog_is_valid(const mcu_watchdog_t *watchdog)
{
    if (watchdog == 0 || watchdog->initialized != MCU_WATCHDOG_COOKIE) {
        return false;
    }
    if (watchdog->stop_ack_pending && watchdog->stop_command_id < MCU_STOP_ID_MIN) {
        return false;
    }
    return true;
}

bool mcu_watchdog_note_activity(mcu_watchdog_t *watchdog,
                                const mcu_state_machine_t *machine,
                                mcu_watchdog_activity_t activity,
                                uint64_t now_us)
{
    if (!mcu_watchdog_is_valid(watchdog) || machine == 0 || !mcu_sm_is_valid(machine) ||
        !activity_is_valid(activity)) {
        return false;
    }
    if (machine->state != MCU_STATE_EXECUTING) {
        watchdog->link_watchdog_armed = false;
        return false;
    }
    if (watchdog->watchdog_cause_active || activity != MCU_WATCHDOG_ACTIVITY_VALID_NEW) {
        return false;
    }

    watchdog->link_watchdog_armed = true;
    watchdog->link_deadline_us = now_us + MCU_SOFTWARE_WATCHDOG_TIMEOUT_US;
    return true;
}

bool mcu_watchdog_poll(mcu_watchdog_t *watchdog,
                       mcu_state_machine_t *machine,
                       uint64_t now_us,
                       mcu_watchdog_record_t *record)
{
    mcu_event_t event;
    mcu_transition_result_t transition;

    if (watchdog == 0 || machine == 0 || record == 0 || !mcu_watchdog_is_valid(watchdog) ||
        !mcu_sm_is_valid(machine)) {
        return false;
    }

    if (watchdog->stop_ack_pending && deadline_after(now_us, watchdog->stop_deadline_us)) {
        clear_record(record);
        record->kind = MCU_WATCHDOG_RECORD_STOP_TIMEOUT;
        record->fault = MCU_WATCHDOG_FAULT_STOP_TIMEOUT;
        record->observed_at_us = now_us;
        record->deadline_us = watchdog->stop_deadline_us;
        record->command_id = watchdog->stop_command_id;
        record->retry_count = watchdog->stop_retry_count;
        watchdog->stop_ack_pending = false;
        clear_stop_ack_cache(watchdog);
        watchdog->stop_timeout_cause_active = true;
        watchdog->stop_timeout_record_emitted = true;
        return true;
    }

    if (machine->state != MCU_STATE_EXECUTING) {
        watchdog->link_watchdog_armed = false;
        return false;
    }
    if (!watchdog->link_watchdog_armed || !deadline_reached(now_us, watchdog->link_deadline_us) ||
        watchdog->watchdog_cause_active) {
        return false;
    }

    event.kind = MCU_EVENT_WATCHDOG_EXPIRED;
    event.fault_code = MCU_FAULT_NONE;
    event.reset_authorized = false;
    event.cause_cleared = false;
    mcu_sm_dispatch(machine, &event, &transition);
    watchdog->link_watchdog_armed = false;
    watchdog->watchdog_cause_active = true;
    if (watchdog->watchdog_record_emitted) {
        return false;
    }
    watchdog->watchdog_record_emitted = true;
    make_watchdog_telemetry(watchdog, now_us, watchdog->link_deadline_us, record);
    return true;
}

bool mcu_watchdog_receive_stop(mcu_watchdog_t *watchdog,
                               mcu_state_machine_t *machine,
                               const mcu_wire_frame_t *stop,
                               uint64_t now_us,
                               mcu_watchdog_record_t *record)
{
    uint16_t arbitration_id;
    uint8_t encoded[MCU_WIRE_DLC];
    uint8_t encoded_length;
    mcu_transition_result_t transition;
    mcu_event_t event;

    if (watchdog == 0 || machine == 0 || stop == 0 || record == 0 ||
        !mcu_watchdog_is_valid(watchdog) || !mcu_sm_is_valid(machine)) {
        return false;
    }
    if (mcu_frame_encode(stop, &arbitration_id, encoded, sizeof(encoded), &encoded_length) != MCU_CODEC_OK ||
        arbitration_id != MCU_CAN_ID_STOP || encoded_length != MCU_WIRE_DLC) {
        return false;
    }
    if (watchdog->stop_timeout_cause_active) {
        return false;
    }
    if (watchdog->stop_ack_pending) {
        if (!stop_matches_pending(watchdog, stop) ||
            deadline_after(now_us, watchdog->stop_deadline_us)) {
            return false;
        }
        replay_pending_stop_ack(watchdog, stop, now_us, record);
        return true;
    }

    event.kind = MCU_EVENT_STOP;
    event.fault_code = MCU_FAULT_NONE;
    event.reset_authorized = false;
    event.cause_cleared = false;
    mcu_sm_dispatch(machine, &event, &transition);
    watchdog->link_watchdog_armed = false;
    watchdog->stop_ack_pending = transition.result_code == MCU_RESULT_ACCEPTED;
    watchdog->stop_deadline_us = now_us + MCU_STOP_ACK_DEADLINE_US;
    watchdog->stop_command_id = stop->command_id;
    watchdog->stop_retry_count = stop->retry_count;
    make_stop_ack(stop, &transition, now_us, watchdog->stop_deadline_us, record);
    if (watchdog->stop_ack_pending) {
        cache_stop_ack(watchdog, record);
    } else {
        clear_stop_ack_cache(watchdog);
    }
    return true;
}

bool mcu_watchdog_confirm_stop_ack(mcu_watchdog_t *watchdog,
                                   uint16_t command_id,
                                   uint8_t retry_count,
                                   uint64_t now_us)
{
    if (!mcu_watchdog_is_valid(watchdog) || !watchdog->stop_ack_pending ||
        watchdog->stop_command_id != command_id || watchdog->stop_retry_count != retry_count ||
        deadline_after(now_us, watchdog->stop_deadline_us)) {
        return false;
    }

    watchdog->stop_ack_pending = false;
    clear_stop_ack_cache(watchdog);
    return true;
}

void mcu_watchdog_mark_causes_cleared(mcu_watchdog_t *watchdog)
{
    if (watchdog == 0 || !mcu_watchdog_is_valid(watchdog)) {
        return;
    }

    watchdog->watchdog_cause_active = false;
    watchdog->stop_timeout_cause_active = false;
}

bool mcu_watchdog_request_reset(mcu_watchdog_t *watchdog,
                                mcu_state_machine_t *machine,
                                bool reset_authorized,
                                bool cause_cleared,
                                mcu_transition_result_t *result)
{
    mcu_event_t event;
    bool live_cause;

    if (watchdog == 0 || machine == 0 || result == 0 || !mcu_watchdog_is_valid(watchdog)) {
        return false;
    }

    live_cause = watchdog->watchdog_cause_active || watchdog->stop_timeout_cause_active ||
                 watchdog->stop_ack_pending;
    event.kind = MCU_EVENT_TRUSTED_RESET;
    event.fault_code = MCU_FAULT_NONE;
    event.reset_authorized = reset_authorized;
    event.cause_cleared = cause_cleared && !live_cause;
    mcu_sm_dispatch(machine, &event, result);
    if (result->result_code != MCU_RESULT_ACCEPTED) {
        return false;
    }

    watchdog->link_watchdog_armed = false;
    watchdog->watchdog_cause_active = false;
    watchdog->watchdog_record_emitted = false;
    watchdog->stop_ack_pending = false;
    clear_stop_ack_cache(watchdog);
    watchdog->stop_timeout_cause_active = false;
    watchdog->stop_timeout_record_emitted = false;
    return true;
}

bool mcu_watchdog_should_feed_hardware(const mcu_watchdog_t *watchdog,
                                       const mcu_state_machine_t *machine)
{
    return mcu_watchdog_is_valid(watchdog) && machine != 0 && mcu_sm_is_valid(machine) &&
           machine->state != MCU_STATE_FAULT && !watchdog->watchdog_cause_active &&
           !watchdog->stop_timeout_cause_active;
}
