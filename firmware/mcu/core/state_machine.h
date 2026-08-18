#ifndef MCU_STATE_MACHINE_H
#define MCU_STATE_MACHINE_H

#include <stdbool.h>
#include <stdint.h>

/* Platform-independent safety states.  Protocol device modes are exposed
 * separately because EXECUTING can represent moving or holding. */
typedef enum {
    MCU_STATE_IDLE = 0,
    MCU_STATE_EXECUTING,
    MCU_STATE_SAFE_STOP,
    MCU_STATE_FAULT,
    MCU_STATE_COUNT
} mcu_state_t;

typedef enum {
    MCU_DEVICE_MODE_IDLE = 0,
    MCU_DEVICE_MODE_MOVING,
    MCU_DEVICE_MODE_HOLDING,
    MCU_DEVICE_MODE_STOPPED,
    MCU_DEVICE_MODE_FAULTED,
    MCU_DEVICE_MODE_COUNT
} mcu_device_mode_t;

/* MCU-originated fault meanings from protocol v1.0.  ACK_TIMEOUT and
 * STOP_TIMEOUT are host diagnostics, so they do not belong in this core. */
typedef enum {
    MCU_FAULT_NONE = 0,
    MCU_FAULT_STOP_REJECTED,
    MCU_FAULT_LINK_LOST,
    MCU_FAULT_DUPLICATE_FRAME,
    MCU_FAULT_WATCHDOG_EXPIRED,
    MCU_FAULT_MALFORMED_FRAME,
    MCU_FAULT_COUNT
} mcu_fault_code_t;

typedef enum {
    MCU_EVENT_BEGIN_MOVE = 0,
    MCU_EVENT_BEGIN_HOLD,
    MCU_EVENT_COMPLETE,
    MCU_EVENT_HEARTBEAT,
    MCU_EVENT_STOP,
    MCU_EVENT_WATCHDOG_EXPIRED,
    MCU_EVENT_RAISE_FAULT,
    MCU_EVENT_TRUSTED_RESET,
    MCU_EVENT_COUNT
} mcu_event_kind_t;

typedef struct {
    mcu_event_kind_t kind;

    /* Used only by MCU_EVENT_RAISE_FAULT. */
    mcu_fault_code_t fault_code;

    /* Used only by MCU_EVENT_TRUSTED_RESET.  These gates come from a trusted
     * control path, never from a protocol v1.0 frame. */
    bool reset_authorized;
    bool cause_cleared;
} mcu_event_t;

/* Values deliberately match protocol v1.0 result_code. */
typedef enum {
    MCU_RESULT_ACCEPTED = 0,
    MCU_RESULT_REJECTED = 1
} mcu_result_code_t;

typedef enum {
    MCU_REASON_NONE = 0,
    MCU_REASON_INVALID_EVENT,
    MCU_REASON_INVALID_ARGUMENT,
    MCU_REASON_INVALID_STATE,
    MCU_REASON_INVALID_TRANSITION,
    MCU_REASON_RESET_NOT_AUTHORIZED,
    MCU_REASON_RESET_CAUSE_ACTIVE,
    MCU_REASON_STOP_REJECTED
} mcu_result_reason_t;

typedef struct {
    mcu_state_t state;
    mcu_device_mode_t device_mode;
    mcu_fault_code_t fault_code;
} mcu_state_machine_t;

typedef struct {
    mcu_result_code_t result_code;
    mcu_result_reason_t reason;
    mcu_state_t previous_state;
    mcu_state_t state;
    mcu_device_mode_t device_mode;

    /* Active latched cause, if any. */
    mcu_fault_code_t fault_code;

    /* Fault to place in the response for this event.  This differs from the
     * active cause when STOP is processed while an earlier fault is latched. */
    mcu_fault_code_t response_fault_code;

    bool execution_active;
    bool force_safe_outputs;
} mcu_transition_result_t;

void mcu_sm_init(mcu_state_machine_t *machine);
bool mcu_sm_is_valid(const mcu_state_machine_t *machine);
void mcu_sm_dispatch(mcu_state_machine_t *machine,
                     const mcu_event_t *event,
                     mcu_transition_result_t *result);

#endif /* MCU_STATE_MACHINE_H */
