#include "frame_codec.h"

#include <stdbool.h>

static bool is_ordinary_opcode(mcu_wire_opcode_t opcode)
{
    return opcode == MCU_WIRE_OPCODE_MOVE || opcode == MCU_WIRE_OPCODE_GRIP_OPEN ||
           opcode == MCU_WIRE_OPCODE_GRIP_CLOSE || opcode == MCU_WIRE_OPCODE_HOLD ||
           opcode == MCU_WIRE_OPCODE_HEARTBEAT;
}

static bool is_non_faulted_mode(mcu_wire_device_mode_t mode)
{
    return mode >= MCU_WIRE_MODE_IDLE && mode <= MCU_WIRE_MODE_STOPPED;
}

static bool absent_command_fields_are_zero(const mcu_wire_frame_t *frame)
{
    return frame->command_id == 0u && frame->opcode == MCU_WIRE_OPCODE_RESERVED &&
           frame->retry_count == 0u && frame->result_code == MCU_WIRE_RESULT_ACCEPTED;
}

static bool absent_response_fields_are_zero(const mcu_wire_frame_t *frame)
{
    return frame->sequence_no == 0u && frame->result_code == MCU_WIRE_RESULT_ACCEPTED &&
           frame->fault_code == MCU_WIRE_FAULT_NONE && frame->device_mode == MCU_WIRE_MODE_IDLE;
}

static bool ordinary_ack_is_valid(const mcu_wire_frame_t *frame)
{
    if (frame->result_code == MCU_WIRE_RESULT_ACCEPTED) {
        return frame->fault_code == MCU_WIRE_FAULT_NONE && is_non_faulted_mode(frame->device_mode);
    }
    if (frame->result_code != MCU_WIRE_RESULT_REJECTED || frame->device_mode != MCU_WIRE_MODE_FAULTED) {
        return false;
    }
    return frame->fault_code == MCU_WIRE_FAULT_DUPLICATE_FRAME ||
           frame->fault_code == MCU_WIRE_FAULT_MALFORMED_FRAME;
}

static bool stop_ack_is_valid(const mcu_wire_frame_t *frame)
{
    if (frame->result_code == MCU_WIRE_RESULT_ACCEPTED) {
        return frame->fault_code == MCU_WIRE_FAULT_NONE && frame->device_mode == MCU_WIRE_MODE_STOPPED;
    }
    return frame->result_code == MCU_WIRE_RESULT_REJECTED &&
           frame->fault_code == MCU_WIRE_FAULT_STOP_REJECTED &&
           frame->device_mode == MCU_WIRE_MODE_FAULTED;
}

static bool telemetry_is_valid(const mcu_wire_frame_t *frame)
{
    if (!absent_command_fields_are_zero(frame)) {
        return false;
    }
    if (frame->fault_code == MCU_WIRE_FAULT_NONE) {
        return is_non_faulted_mode(frame->device_mode);
    }
    return (frame->fault_code == MCU_WIRE_FAULT_LINK_LOST ||
            frame->fault_code == MCU_WIRE_FAULT_WATCHDOG_EXPIRED) &&
           frame->device_mode == MCU_WIRE_MODE_FAULTED;
}

static bool frame_is_valid(const mcu_wire_frame_t *frame)
{
    switch (frame->kind) {
    case MCU_WIRE_FRAME_COMMAND:
        return frame->command_id <= MCU_COMMAND_ID_MAX && is_ordinary_opcode(frame->opcode) &&
               absent_response_fields_are_zero(frame);
    case MCU_WIRE_FRAME_ACK:
        return frame->command_id <= MCU_COMMAND_ID_MAX && is_ordinary_opcode(frame->opcode) &&
               frame->sequence_no == 0u && ordinary_ack_is_valid(frame);
    case MCU_WIRE_FRAME_TELEMETRY:
        return telemetry_is_valid(frame);
    case MCU_WIRE_FRAME_STOP:
        return frame->command_id >= MCU_STOP_ID_MIN && frame->opcode == MCU_WIRE_OPCODE_STOP &&
               absent_response_fields_are_zero(frame);
    case MCU_WIRE_FRAME_STOP_ACK:
        return frame->command_id >= MCU_STOP_ID_MIN && frame->opcode == MCU_WIRE_OPCODE_STOP &&
               frame->sequence_no == 0u && stop_ack_is_valid(frame);
    case MCU_WIRE_FRAME_KIND_COUNT:
    default:
        return false;
    }
}

static uint16_t frame_kind_to_id(mcu_wire_frame_kind_t kind)
{
    switch (kind) {
    case MCU_WIRE_FRAME_COMMAND:
        return MCU_CAN_ID_COMMAND;
    case MCU_WIRE_FRAME_ACK:
        return MCU_CAN_ID_ACK;
    case MCU_WIRE_FRAME_TELEMETRY:
        return MCU_CAN_ID_TELEMETRY;
    case MCU_WIRE_FRAME_STOP:
        return MCU_CAN_ID_STOP;
    case MCU_WIRE_FRAME_STOP_ACK:
        return MCU_CAN_ID_STOP_ACK;
    case MCU_WIRE_FRAME_KIND_COUNT:
    default:
        return 0xffffu;
    }
}

static bool id_to_frame_kind(uint16_t arbitration_id, mcu_wire_frame_kind_t *kind)
{
    switch (arbitration_id) {
    case MCU_CAN_ID_COMMAND:
        *kind = MCU_WIRE_FRAME_COMMAND;
        return true;
    case MCU_CAN_ID_ACK:
        *kind = MCU_WIRE_FRAME_ACK;
        return true;
    case MCU_CAN_ID_TELEMETRY:
        *kind = MCU_WIRE_FRAME_TELEMETRY;
        return true;
    case MCU_CAN_ID_STOP:
        *kind = MCU_WIRE_FRAME_STOP;
        return true;
    case MCU_CAN_ID_STOP_ACK:
        *kind = MCU_WIRE_FRAME_STOP_ACK;
        return true;
    default:
        return false;
    }
}

static void write_u16_be(uint8_t *destination, uint16_t value)
{
    destination[0] = (uint8_t)(value >> 8);
    destination[1] = (uint8_t)value;
}

static void write_u32_be(uint8_t *destination, uint32_t value)
{
    destination[0] = (uint8_t)(value >> 24);
    destination[1] = (uint8_t)(value >> 16);
    destination[2] = (uint8_t)(value >> 8);
    destination[3] = (uint8_t)value;
}

static uint16_t read_u16_be(const uint8_t *source)
{
    return (uint16_t)(((uint16_t)source[0] << 8) | source[1]);
}

static uint32_t read_u32_be(const uint8_t *source)
{
    return ((uint32_t)source[0] << 24) | ((uint32_t)source[1] << 16) |
           ((uint32_t)source[2] << 8) | source[3];
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

mcu_codec_status_t mcu_frame_encode(const mcu_wire_frame_t *frame,
                                    uint16_t *arbitration_id,
                                    uint8_t *destination,
                                    uint8_t destination_capacity,
                                    uint8_t *encoded_length)
{
    uint8_t encoded[MCU_WIRE_DLC] = {0u};
    uint16_t encoded_id;
    unsigned i;

    if (frame == 0 || arbitration_id == 0 || destination == 0 || encoded_length == 0) {
        return MCU_CODEC_INVALID_ARGUMENT;
    }
    if (destination_capacity < MCU_WIRE_DLC) {
        return MCU_CODEC_BUFFER_TOO_SMALL;
    }
    if (!frame_is_valid(frame)) {
        return MCU_CODEC_INVALID_FIELD;
    }

    encoded_id = frame_kind_to_id(frame->kind);
    encoded[0] = MCU_WIRE_VERSION_V1;
    switch (frame->kind) {
    case MCU_WIRE_FRAME_COMMAND:
    case MCU_WIRE_FRAME_STOP:
        write_u16_be(&encoded[1], frame->command_id);
        encoded[3] = (uint8_t)frame->opcode;
        encoded[4] = frame->retry_count;
        break;
    case MCU_WIRE_FRAME_ACK:
    case MCU_WIRE_FRAME_STOP_ACK:
        write_u16_be(&encoded[1], frame->command_id);
        encoded[3] = (uint8_t)frame->opcode;
        encoded[4] = frame->retry_count;
        encoded[5] = (uint8_t)frame->result_code;
        encoded[6] = (uint8_t)frame->fault_code;
        encoded[7] = (uint8_t)frame->device_mode;
        break;
    case MCU_WIRE_FRAME_TELEMETRY:
        write_u32_be(&encoded[1], frame->sequence_no);
        encoded[5] = (uint8_t)frame->fault_code;
        encoded[6] = (uint8_t)frame->device_mode;
        break;
    case MCU_WIRE_FRAME_KIND_COUNT:
    default:
        return MCU_CODEC_INVALID_FIELD;
    }

    for (i = 0u; i < MCU_WIRE_DLC; i++) {
        destination[i] = encoded[i];
    }
    *arbitration_id = encoded_id;
    *encoded_length = MCU_WIRE_DLC;
    return MCU_CODEC_OK;
}

mcu_codec_status_t mcu_frame_decode(uint16_t arbitration_id,
                                    const uint8_t *source,
                                    uint8_t encoded_length,
                                    mcu_wire_frame_t *frame)
{
    mcu_wire_frame_t decoded;

    if (frame == 0) {
        return MCU_CODEC_INVALID_ARGUMENT;
    }
    if (encoded_length != MCU_WIRE_DLC) {
        return MCU_CODEC_INVALID_LENGTH;
    }
    if (source == 0) {
        return MCU_CODEC_INVALID_ARGUMENT;
    }
    clear_frame(&decoded);
    if (!id_to_frame_kind(arbitration_id, &decoded.kind)) {
        return MCU_CODEC_UNSUPPORTED_ID;
    }
    if (source[0] != MCU_WIRE_VERSION_V1) {
        return MCU_CODEC_INVALID_VERSION;
    }

    switch (decoded.kind) {
    case MCU_WIRE_FRAME_COMMAND:
    case MCU_WIRE_FRAME_STOP:
        if (source[5] != 0u || source[6] != 0u || source[7] != 0u) {
            return MCU_CODEC_NONZERO_RESERVED;
        }
        decoded.command_id = read_u16_be(&source[1]);
        decoded.opcode = (mcu_wire_opcode_t)source[3];
        decoded.retry_count = source[4];
        break;
    case MCU_WIRE_FRAME_ACK:
    case MCU_WIRE_FRAME_STOP_ACK:
        decoded.command_id = read_u16_be(&source[1]);
        decoded.opcode = (mcu_wire_opcode_t)source[3];
        decoded.retry_count = source[4];
        decoded.result_code = (mcu_wire_result_t)source[5];
        decoded.fault_code = (mcu_wire_fault_t)source[6];
        decoded.device_mode = (mcu_wire_device_mode_t)source[7];
        break;
    case MCU_WIRE_FRAME_TELEMETRY:
        if (source[7] != 0u) {
            return MCU_CODEC_NONZERO_RESERVED;
        }
        decoded.sequence_no = read_u32_be(&source[1]);
        decoded.fault_code = (mcu_wire_fault_t)source[5];
        decoded.device_mode = (mcu_wire_device_mode_t)source[6];
        break;
    case MCU_WIRE_FRAME_KIND_COUNT:
    default:
        return MCU_CODEC_UNSUPPORTED_ID;
    }

    if (!frame_is_valid(&decoded)) {
        return MCU_CODEC_INVALID_FIELD;
    }
    copy_frame(frame, &decoded);
    return MCU_CODEC_OK;
}
