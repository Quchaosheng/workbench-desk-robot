#include "can_bridge.h"

_Static_assert(HAL_CAN_CLASSIC_DLC_MAX == MCU_WIRE_DLC,
               "HAL Classic CAN payload must match Wire V1 DLC");
_Static_assert(MCU_CAN_ID_TELEMETRY <= HAL_CAN_STANDARD_ID_MAX,
               "Wire V1 identifiers must fit the standard CAN envelope");

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

static void clear_record(mcu_can_bridge_record_t *record)
{
    record->outcome = MCU_CAN_BRIDGE_OUTCOME_NONE;
    record->status = MCU_CAN_BRIDGE_OK;
    record->request_decoded = false;
    record->ordinary_event_dispatched = false;
    record->stop_path_entered = false;
    record->response_available = false;
    record->response_handed_off = false;
    clear_wire_frame(&record->request);
    clear_wire_frame(&record->response);
}

static void copy_record(mcu_can_bridge_record_t *destination,
                        const mcu_can_bridge_record_t *source)
{
    destination->outcome = source->outcome;
    destination->status = source->status;
    destination->request_decoded = source->request_decoded;
    destination->ordinary_event_dispatched = source->ordinary_event_dispatched;
    destination->stop_path_entered = source->stop_path_entered;
    destination->response_available = source->response_available;
    destination->response_handed_off = source->response_handed_off;
    copy_wire_frame(&destination->request, &source->request);
    copy_wire_frame(&destination->response, &source->response);
}

static mcu_can_bridge_status_t map_codec_status(mcu_codec_status_t status)
{
    switch (status) {
    case MCU_CODEC_OK:
        return MCU_CAN_BRIDGE_OK;
    case MCU_CODEC_INVALID_ARGUMENT:
        return MCU_CAN_BRIDGE_INVALID_ARGUMENT;
    case MCU_CODEC_INVALID_LENGTH:
        return MCU_CAN_BRIDGE_INVALID_DLC;
    case MCU_CODEC_UNSUPPORTED_ID:
        return MCU_CAN_BRIDGE_UNSUPPORTED_ID;
    case MCU_CODEC_INVALID_VERSION:
        return MCU_CAN_BRIDGE_INVALID_VERSION;
    case MCU_CODEC_NONZERO_RESERVED:
        return MCU_CAN_BRIDGE_NONZERO_RESERVED;
    case MCU_CODEC_INVALID_FIELD:
        return MCU_CAN_BRIDGE_INVALID_WIRE_FIELD;
    case MCU_CODEC_BUFFER_TOO_SMALL:
    default:
        return MCU_CAN_BRIDGE_CORE_REJECTED;
    }
}

mcu_can_bridge_status_t mcu_can_bridge_encode(const mcu_wire_frame_t *frame,
                                              hal_can_frame *encoded)
{
    hal_can_frame local;
    uint8_t encoded_length = 0u;
    mcu_codec_status_t codec_status;

    if (frame == 0 || encoded == 0) {
        return MCU_CAN_BRIDGE_INVALID_ARGUMENT;
    }

    local.arbitration_id = 0u;
    local.dlc = 0u;
    local.flags = (uint8_t)HAL_CAN_FRAME_FLAG_NONE;
    codec_status = mcu_frame_encode(frame,
                                    &local.arbitration_id,
                                    local.data,
                                    sizeof(local.data),
                                    &encoded_length);
    if (codec_status != MCU_CODEC_OK) {
        return map_codec_status(codec_status);
    }
    if (local.arbitration_id > HAL_CAN_STANDARD_ID_MAX) {
        return MCU_CAN_BRIDGE_INVALID_ARBITRATION_ID;
    }
    if (encoded_length != MCU_WIRE_DLC || encoded_length > HAL_CAN_CLASSIC_DLC_MAX) {
        return MCU_CAN_BRIDGE_CORE_REJECTED;
    }

    local.dlc = encoded_length;
    copy_hal_frame(encoded, &local);
    return MCU_CAN_BRIDGE_OK;
}

mcu_can_bridge_status_t mcu_can_bridge_decode(const hal_can_frame *encoded,
                                              mcu_wire_frame_t *frame)
{
    mcu_wire_frame_t decoded;
    mcu_codec_status_t codec_status;

    if (encoded == 0 || frame == 0) {
        return MCU_CAN_BRIDGE_INVALID_ARGUMENT;
    }
    if (encoded->flags != (uint8_t)HAL_CAN_FRAME_FLAG_NONE) {
        return MCU_CAN_BRIDGE_INVALID_FLAGS;
    }
    if (encoded->arbitration_id > HAL_CAN_STANDARD_ID_MAX) {
        return MCU_CAN_BRIDGE_INVALID_ARBITRATION_ID;
    }
    if (encoded->dlc != MCU_WIRE_DLC) {
        return MCU_CAN_BRIDGE_INVALID_DLC;
    }

    codec_status = mcu_frame_decode(encoded->arbitration_id,
                                    encoded->data,
                                    encoded->dlc,
                                    &decoded);
    if (codec_status != MCU_CODEC_OK) {
        return map_codec_status(codec_status);
    }

    copy_wire_frame(frame, &decoded);
    return MCU_CAN_BRIDGE_OK;
}

mcu_can_bridge_status_t mcu_can_bridge_send(const mcu_wire_frame_t *frame)
{
    hal_can_frame encoded;
    mcu_can_bridge_status_t status = mcu_can_bridge_encode(frame, &encoded);

    if (status != MCU_CAN_BRIDGE_OK) {
        return status;
    }
    return hal_can_send(&encoded) ? MCU_CAN_BRIDGE_OK
                                  : MCU_CAN_BRIDGE_HAL_SEND_FAILED;
}

static bool safety_dependencies_are_valid(const mcu_state_machine_t *machine,
                                          const mcu_watchdog_t *watchdog)
{
    return mcu_sm_is_valid(machine) && mcu_watchdog_is_valid(watchdog);
}

bool mcu_can_bridge_process_frame(mcu_command_dedup_t *dedup,
                                  mcu_state_machine_t *machine,
                                  mcu_watchdog_t *watchdog,
                                  const hal_can_frame *encoded,
                                  uint64_t now_us,
                                  mcu_can_bridge_record_t *record)
{
    mcu_can_bridge_record_t local;
    mcu_can_bridge_status_t status;

    if (machine == 0 || watchdog == 0 || encoded == 0 || record == 0 ||
        !safety_dependencies_are_valid(machine, watchdog)) {
        return false;
    }

    clear_record(&local);
    status = mcu_can_bridge_decode(encoded, &local.request);
    if (status != MCU_CAN_BRIDGE_OK) {
        local.outcome = MCU_CAN_BRIDGE_OUTCOME_REJECTED;
        local.status = status;
        copy_record(record, &local);
        return true;
    }
    local.request_decoded = true;

    /* STOP is deliberately tested before the ordinary path. It bypasses the
     * session gate and replay window and is never converted into a command. */
    if (local.request.kind == MCU_WIRE_FRAME_STOP) {
        mcu_watchdog_record_t stop_record;

        local.stop_path_entered = true;
        if (!mcu_watchdog_receive_stop(watchdog,
                                       machine,
                                       &local.request,
                                       now_us,
                                       &stop_record)) {
            local.outcome = MCU_CAN_BRIDGE_OUTCOME_REJECTED;
            local.status = MCU_CAN_BRIDGE_CORE_REJECTED;
            copy_record(record, &local);
            return true;
        }
        local.outcome = MCU_CAN_BRIDGE_OUTCOME_STOP_HANDLED;
        local.response_available = true;
        copy_wire_frame(&local.response, &stop_record.frame);
        copy_record(record, &local);
        return true;
    }

    if (local.request.kind == MCU_WIRE_FRAME_COMMAND) {
        mcu_command_record_t command_record;

        if (dedup == 0 || !mcu_command_dedup_is_valid(dedup) ||
            !mcu_command_dedup_receive(dedup,
                                       machine,
                                       watchdog,
                                       &local.request,
                                       now_us,
                                       &command_record)) {
            local.outcome = MCU_CAN_BRIDGE_OUTCOME_REJECTED;
            local.status = MCU_CAN_BRIDGE_CORE_REJECTED;
            copy_record(record, &local);
            return true;
        }
        local.ordinary_event_dispatched = command_record.ordinary_event_dispatched;
        if (!command_record.ack_available) {
            local.outcome = MCU_CAN_BRIDGE_OUTCOME_SESSION_CLOSED;
            copy_record(record, &local);
            return true;
        }
        local.outcome = MCU_CAN_BRIDGE_OUTCOME_COMMAND_HANDLED;
        local.response_available = true;
        copy_wire_frame(&local.response, &command_record.ack);
        copy_record(record, &local);
        return true;
    }

    /* ACK, STOP_ACK and telemetry are MCU-originated under Wire V1. A frame
     * with one of those IDs on the MCU ingress is validly encoded but has the
     * wrong direction and must not reach safety state. */
    local.outcome = MCU_CAN_BRIDGE_OUTCOME_REJECTED;
    local.status = MCU_CAN_BRIDGE_UNEXPECTED_DIRECTION;
    copy_record(record, &local);
    return true;
}

bool mcu_can_bridge_poll(mcu_command_dedup_t *dedup,
                         mcu_state_machine_t *machine,
                         mcu_watchdog_t *watchdog,
                         uint64_t now_us,
                         mcu_can_bridge_record_t *record)
{
    hal_can_frame encoded;
    mcu_can_bridge_record_t local;
    mcu_can_bridge_status_t send_status;

    if (machine == 0 || watchdog == 0 || record == 0 ||
        !safety_dependencies_are_valid(machine, watchdog)) {
        return false;
    }
    if (!hal_can_recv(&encoded)) {
        clear_record(&local);
        local.outcome = MCU_CAN_BRIDGE_OUTCOME_NO_FRAME;
        local.status = MCU_CAN_BRIDGE_NO_FRAME;
        copy_record(record, &local);
        return true;
    }
    if (!mcu_can_bridge_process_frame(dedup,
                                      machine,
                                      watchdog,
                                      &encoded,
                                      now_us,
                                      &local)) {
        return false;
    }
    if (!local.response_available) {
        copy_record(record, &local);
        return true;
    }

    send_status = mcu_can_bridge_send(&local.response);
    if (send_status != MCU_CAN_BRIDGE_OK) {
        local.status = send_status;
        copy_record(record, &local);
        return true;
    }
    local.response_handed_off = true;

    if (local.response.kind == MCU_WIRE_FRAME_STOP_ACK &&
        local.response.result_code == MCU_WIRE_RESULT_ACCEPTED &&
        !mcu_watchdog_confirm_stop_ack(watchdog,
                                       local.response.command_id,
                                       local.response.retry_count,
                                       now_us)) {
        local.status = MCU_CAN_BRIDGE_CORE_REJECTED;
    }
    copy_record(record, &local);
    return true;
}
