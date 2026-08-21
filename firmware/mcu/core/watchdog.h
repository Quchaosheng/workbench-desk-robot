#ifndef MCU_WATCHDOG_H
#define MCU_WATCHDOG_H

#include <stdbool.h>
#include <stdint.h>

#include "frame_codec.h"
#include "state_machine.h"

/* Controlled implementation constants for Wire V1 timing.  The values are
 * deliberately small enough for deterministic QEMU evidence and are not
 * physical CH32V307 latency or E-stop measurements. */
#define MCU_HEARTBEAT_PERIOD_US 50000ull
#define MCU_SOFTWARE_WATCHDOG_TIMEOUT_US 150000ull
#define MCU_STOP_ACK_DEADLINE_US 10000ull
#define MCU_HARDWARE_WATCHDOG_PERIOD_MS 500u

typedef enum {
    MCU_WATCHDOG_ACTIVITY_VALID_NEW = 0,
    MCU_WATCHDOG_ACTIVITY_RETRY,
    MCU_WATCHDOG_ACTIVITY_DUPLICATE,
    MCU_WATCHDOG_ACTIVITY_STALE,
    MCU_WATCHDOG_ACTIVITY_MALFORMED,
    MCU_WATCHDOG_ACTIVITY_STOP,
    MCU_WATCHDOG_ACTIVITY_COUNT
} mcu_watchdog_activity_t;

typedef enum {
    MCU_WATCHDOG_RECORD_NONE = 0,
    MCU_WATCHDOG_RECORD_FAULT_TELEMETRY,
    MCU_WATCHDOG_RECORD_STOP_ACK,
    MCU_WATCHDOG_RECORD_STOP_TIMEOUT,
    MCU_WATCHDOG_RECORD_COUNT
} mcu_watchdog_record_kind_t;

typedef enum {
    MCU_WATCHDOG_FAULT_NONE = 0,
    MCU_WATCHDOG_FAULT_WATCHDOG_EXPIRED,
    MCU_WATCHDOG_FAULT_STOP_TIMEOUT,
    MCU_WATCHDOG_FAULT_COUNT
} mcu_watchdog_fault_t;

typedef struct {
    mcu_watchdog_record_kind_t kind;
    mcu_watchdog_fault_t fault;
    uint64_t observed_at_us;
    uint64_t deadline_us;
    uint16_t command_id;
    uint8_t retry_count;
    mcu_wire_frame_t frame;
} mcu_watchdog_record_t;

typedef struct {
    uint32_t initialized;
    uint32_t next_telemetry_sequence;

    bool link_watchdog_armed;
    bool watchdog_cause_active;
    bool watchdog_record_emitted;
    uint64_t link_deadline_us;

    bool stop_ack_pending;
    bool stop_timeout_cause_active;
    bool stop_timeout_record_emitted;
    uint64_t stop_deadline_us;
    uint16_t stop_command_id;
    uint8_t stop_retry_count;
    uint64_t stop_ack_observed_at_us;
    mcu_wire_frame_t stop_ack_frame;
} mcu_watchdog_t;

void mcu_watchdog_init(mcu_watchdog_t *watchdog, uint32_t first_telemetry_sequence);
bool mcu_watchdog_is_valid(const mcu_watchdog_t *watchdog);

/* Only callers that have already validated the complete frame and accepted a
 * serially new command may pass VALID_NEW.  Retry, duplicate, stale,
 * malformed and STOP activity never refreshes the execution watchdog. */
bool mcu_watchdog_note_activity(mcu_watchdog_t *watchdog,
                                const mcu_state_machine_t *machine,
                                mcu_watchdog_activity_t activity,
                                uint64_t now_us);

/* Poll is allocation-free and deterministic.  It publishes at most one
 * record per call and leaves the output untouched when no deadline fired. */
bool mcu_watchdog_poll(mcu_watchdog_t *watchdog,
                       mcu_state_machine_t *machine,
                       uint64_t now_us,
                       mcu_watchdog_record_t *record);

/* A valid STOP is dispatched before this function returns.  The returned ACK
 * is ready for transport immediately; the caller must confirm handoff through
 * mcu_watchdog_confirm_stop_ack(). */
bool mcu_watchdog_receive_stop(mcu_watchdog_t *watchdog,
                               mcu_state_machine_t *machine,
                               const mcu_wire_frame_t *stop,
                               uint64_t now_us,
                               mcu_watchdog_record_t *record);

/* Confirmation at the exact deadline is still within the inclusive bound.
 * A late confirmation is rejected and leaves the timeout cause observable via
 * poll(). */
bool mcu_watchdog_confirm_stop_ack(mcu_watchdog_t *watchdog,
                                   uint16_t command_id,
                                   uint8_t retry_count,
                                   uint64_t now_us);

/* Trusted safety-control operation: this does not authorize reset.  It records
 * that the external owner has cleared live timing causes. */
void mcu_watchdog_mark_causes_cleared(mcu_watchdog_t *watchdog);

/* Reset still goes through the existing state-machine authorization and cause
 * gates.  A live timing cause forces cause_cleared=false regardless of the
 * caller's requested value. */
bool mcu_watchdog_request_reset(mcu_watchdog_t *watchdog,
                                mcu_state_machine_t *machine,
                                bool reset_authorized,
                                bool cause_cleared,
                                mcu_transition_result_t *result);

/* Hardware watchdog feed is allowed only for a valid non-fault state without
 * an active timing cause. A hung loop or a timed-out safety path cannot call
 * this function successfully. */
bool mcu_watchdog_should_feed_hardware(const mcu_watchdog_t *watchdog,
                                       const mcu_state_machine_t *machine);

#endif /* MCU_WATCHDOG_H */
