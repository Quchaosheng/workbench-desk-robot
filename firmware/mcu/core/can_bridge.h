#ifndef MCU_CAN_BRIDGE_H
#define MCU_CAN_BRIDGE_H

#include <stdbool.h>
#include <stdint.h>

#include "command_dedup.h"
#include "frame_codec.h"
#include "hal.h"
#include "state_machine.h"
#include "watchdog.h"

/* Exact diagnostics for the boundary at which an input was rejected.  A
 * rejected raw or Wire V1 frame never reaches the safety state machine. */
typedef enum {
    MCU_CAN_BRIDGE_OK = 0,
    MCU_CAN_BRIDGE_NO_FRAME,
    MCU_CAN_BRIDGE_INVALID_ARGUMENT,
    MCU_CAN_BRIDGE_INVALID_FLAGS,
    MCU_CAN_BRIDGE_INVALID_ARBITRATION_ID,
    MCU_CAN_BRIDGE_INVALID_DLC,
    MCU_CAN_BRIDGE_UNSUPPORTED_ID,
    MCU_CAN_BRIDGE_INVALID_VERSION,
    MCU_CAN_BRIDGE_NONZERO_RESERVED,
    MCU_CAN_BRIDGE_INVALID_WIRE_FIELD,
    MCU_CAN_BRIDGE_UNEXPECTED_DIRECTION,
    MCU_CAN_BRIDGE_CORE_REJECTED,
    MCU_CAN_BRIDGE_HAL_SEND_FAILED,
    MCU_CAN_BRIDGE_STATUS_COUNT
} mcu_can_bridge_status_t;

typedef enum {
    MCU_CAN_BRIDGE_OUTCOME_NONE = 0,
    MCU_CAN_BRIDGE_OUTCOME_NO_FRAME,
    MCU_CAN_BRIDGE_OUTCOME_REJECTED,
    MCU_CAN_BRIDGE_OUTCOME_SESSION_CLOSED,
    MCU_CAN_BRIDGE_OUTCOME_COMMAND_HANDLED,
    MCU_CAN_BRIDGE_OUTCOME_STOP_HANDLED,
    MCU_CAN_BRIDGE_OUTCOME_COUNT
} mcu_can_bridge_outcome_t;

typedef struct {
    mcu_can_bridge_outcome_t outcome;
    mcu_can_bridge_status_t status;
    bool request_decoded;
    bool ordinary_event_dispatched;
    bool stop_path_entered;
    bool response_available;
    bool response_handed_off;
    mcu_wire_frame_t request;
    mcu_wire_frame_t response;
} mcu_can_bridge_record_t;

/* These conversion functions are the only mapping between the raw HAL
 * envelope and Wire V1. Outputs remain untouched when conversion fails. */
mcu_can_bridge_status_t mcu_can_bridge_encode(const mcu_wire_frame_t *frame,
                                              hal_can_frame *encoded);
mcu_can_bridge_status_t mcu_can_bridge_decode(const hal_can_frame *encoded,
                                              mcu_wire_frame_t *frame);

/* Encode one complete Wire V1 frame and hand it to the target HAL. A true HAL
 * return means transport handoff only, not bus delivery or actuator proof. */
mcu_can_bridge_status_t mcu_can_bridge_send(const mcu_wire_frame_t *frame);

/* Process one already-received raw envelope without calling hal_can_send().
 * This is shared by Host/QEMU logic tests. dedup may be null or corrupt for a
 * STOP because the safety path is independent; an ordinary command then
 * fails closed. If an accepted STOP response is returned, the caller still
 * owns transport handoff confirmation. */
bool mcu_can_bridge_process_frame(mcu_command_dedup_t *dedup,
                                  mcu_state_machine_t *machine,
                                  mcu_watchdog_t *watchdog,
                                  const hal_can_frame *encoded,
                                  uint64_t now_us,
                                  mcu_can_bridge_record_t *record);

/* Consume at most one frame from the non-blocking HAL, route STOP directly to
 * the watchdog path before ordinary-command handling, and send any response.
 * Successful handoff of an accepted STOP_ACK confirms its bounded core slot.
 * The owning target must serialize calls and configure controller/FIFO
 * priority; this function does not hide an unbounded receive queue. */
bool mcu_can_bridge_poll(mcu_command_dedup_t *dedup,
                         mcu_state_machine_t *machine,
                         mcu_watchdog_t *watchdog,
                         uint64_t now_us,
                         mcu_can_bridge_record_t *record);

#endif /* MCU_CAN_BRIDGE_H */
