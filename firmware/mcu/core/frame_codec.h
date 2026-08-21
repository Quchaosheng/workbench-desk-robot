#ifndef MCU_FRAME_CODEC_H
#define MCU_FRAME_CODEC_H

#include <stdint.h>

/* Firmware-owned CAN Wire V1.  The logical protocol remains version 1.0;
 * 0x10 is its compact on-wire representation. */
#define MCU_WIRE_VERSION_V1 0x10u
#define MCU_WIRE_DLC 8u

/* Lower CAN identifiers win arbitration, so STOP traffic has priority over
 * ordinary command, acknowledgement and telemetry traffic. */
#define MCU_CAN_ID_STOP 0x080u
#define MCU_CAN_ID_STOP_ACK 0x081u
#define MCU_CAN_ID_COMMAND 0x100u
#define MCU_CAN_ID_ACK 0x101u
#define MCU_CAN_ID_TELEMETRY 0x180u

#define MCU_COMMAND_ID_MAX 0x7fffu
#define MCU_STOP_ID_MIN 0x8000u

typedef enum {
    MCU_WIRE_FRAME_COMMAND = 0,
    MCU_WIRE_FRAME_ACK,
    MCU_WIRE_FRAME_TELEMETRY,
    MCU_WIRE_FRAME_STOP,
    MCU_WIRE_FRAME_STOP_ACK,
    MCU_WIRE_FRAME_KIND_COUNT
} mcu_wire_frame_kind_t;

/* Zero is reserved so an uninitialised/zero-filled opcode cannot execute. */
typedef enum {
    MCU_WIRE_OPCODE_RESERVED = 0,
    MCU_WIRE_OPCODE_MOVE = 1,
    MCU_WIRE_OPCODE_GRIP_OPEN = 2,
    MCU_WIRE_OPCODE_GRIP_CLOSE = 3,
    MCU_WIRE_OPCODE_HOLD = 4,
    MCU_WIRE_OPCODE_STOP = 5,
    MCU_WIRE_OPCODE_HEARTBEAT = 6,
    MCU_WIRE_OPCODE_COUNT
} mcu_wire_opcode_t;

typedef enum {
    MCU_WIRE_RESULT_ACCEPTED = 0,
    MCU_WIRE_RESULT_REJECTED = 1,
    MCU_WIRE_RESULT_COUNT
} mcu_wire_result_t;

/* Values follow the frozen logical fault registry. ACK_TIMEOUT and
 * STOP_TIMEOUT are host-only diagnostics and are rejected in decoded MCU
 * frames even though their numeric values remain reserved here. */
typedef enum {
    MCU_WIRE_FAULT_NONE = 0,
    MCU_WIRE_FAULT_ACK_TIMEOUT = 1,
    MCU_WIRE_FAULT_STOP_TIMEOUT = 2,
    MCU_WIRE_FAULT_STOP_REJECTED = 3,
    MCU_WIRE_FAULT_LINK_LOST = 4,
    MCU_WIRE_FAULT_DUPLICATE_FRAME = 5,
    MCU_WIRE_FAULT_WATCHDOG_EXPIRED = 6,
    MCU_WIRE_FAULT_MALFORMED_FRAME = 7,
    MCU_WIRE_FAULT_COUNT
} mcu_wire_fault_t;

typedef enum {
    MCU_WIRE_MODE_IDLE = 0,
    MCU_WIRE_MODE_MOVING = 1,
    MCU_WIRE_MODE_HOLDING = 2,
    MCU_WIRE_MODE_STOPPED = 3,
    MCU_WIRE_MODE_FAULTED = 4,
    MCU_WIRE_MODE_COUNT
} mcu_wire_device_mode_t;

typedef enum {
    MCU_CODEC_OK = 0,
    MCU_CODEC_INVALID_ARGUMENT,
    MCU_CODEC_BUFFER_TOO_SMALL,
    MCU_CODEC_INVALID_LENGTH,
    MCU_CODEC_UNSUPPORTED_ID,
    MCU_CODEC_INVALID_VERSION,
    MCU_CODEC_NONZERO_RESERVED,
    MCU_CODEC_INVALID_FIELD
} mcu_codec_status_t;

/* Fields absent from a frame kind must remain zero.  This makes accidental
 * reuse of a struct fail closed instead of silently dropping stale fields. */
typedef struct {
    mcu_wire_frame_kind_t kind;
    uint16_t command_id;
    uint32_t sequence_no;
    mcu_wire_opcode_t opcode;
    uint8_t retry_count;
    mcu_wire_result_t result_code;
    mcu_wire_fault_t fault_code;
    mcu_wire_device_mode_t device_mode;
} mcu_wire_frame_t;

/* Outputs are not modified on failure.  The encoder validates capacity before
 * writing and always emits exactly MCU_WIRE_DLC bytes on success. */
mcu_codec_status_t mcu_frame_encode(const mcu_wire_frame_t *frame,
                                    uint16_t *arbitration_id,
                                    uint8_t *destination,
                                    uint8_t destination_capacity,
                                    uint8_t *encoded_length);

/* The decoder validates encoded_length before reading source and publishes a
 * frame only after every byte and cross-field invariant has passed. */
mcu_codec_status_t mcu_frame_decode(uint16_t arbitration_id,
                                    const uint8_t *source,
                                    uint8_t encoded_length,
                                    mcu_wire_frame_t *frame);

#endif /* MCU_FRAME_CODEC_H */
