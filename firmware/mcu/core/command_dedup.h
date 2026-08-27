#ifndef MCU_COMMAND_DEDUP_H
#define MCU_COMMAND_DEDUP_H

#include <stdbool.h>
#include <stdint.h>

#include "frame_codec.h"
#include "state_machine.h"
#include "watchdog.h"

/* Ordinary command IDs use the low 15 bits as a serial number.  Eight
 * retained results cover the current bounded host implementation (one
 * in-flight command plus retries) while keeping firmware memory fixed. */
#define MCU_COMMAND_SERIAL_MASK 0x7fffu
#define MCU_COMMAND_SERIAL_HALF_RANGE 0x4000u
#define MCU_COMMAND_REPLAY_WINDOW_SIZE 8u
#define MCU_COMMAND_DEDUP_STORAGE_BUDGET_BYTES 256u

typedef enum {
    MCU_COMMAND_OUTCOME_NONE = 0,
    MCU_COMMAND_OUTCOME_SESSION_CLOSED,
    MCU_COMMAND_OUTCOME_ACCEPTED_NEW,
    MCU_COMMAND_OUTCOME_REJECTED_NEW,
    MCU_COMMAND_OUTCOME_REPLAYED,
    MCU_COMMAND_OUTCOME_REJECTED_CONFLICT,
    MCU_COMMAND_OUTCOME_REJECTED_STALE,
    MCU_COMMAND_OUTCOME_REJECTED_RETRY,
    MCU_COMMAND_OUTCOME_COUNT
} mcu_command_outcome_t;

typedef struct {
    mcu_command_outcome_t outcome;
    bool ack_available;
    /* True only when a serially new ordinary command reached the safety state
     * machine. Replays and correlation rejections never set this flag. */
    bool ordinary_event_dispatched;
    bool watchdog_refreshed;
    mcu_wire_frame_t ack;
} mcu_command_record_t;

typedef struct {
    bool valid;
    uint16_t command_id;
    mcu_wire_opcode_t opcode;
    uint8_t last_retry_count;
    mcu_wire_result_t result_code;
    mcu_wire_fault_t fault_code;
    mcu_wire_device_mode_t device_mode;
} mcu_command_replay_entry_t;

typedef struct {
    uint32_t initialized;
    bool session_open;
    bool has_last_accepted;
    uint16_t last_accepted_id;
    uint8_t next_slot;
    mcu_command_replay_entry_t entries[MCU_COMMAND_REPLAY_WINDOW_SIZE];
} mcu_command_dedup_t;

/* Boot initialization deliberately leaves ordinary command dispatch closed.
 * STOP remains owned by mcu_watchdog_receive_stop() and is not gated here. */
void mcu_command_dedup_init(mcu_command_dedup_t *dedup);
bool mcu_command_dedup_is_valid(const mcu_command_dedup_t *dedup);

/* This trusted transport gate may open only after queued pre-session traffic
 * has been discarded. Reopening an already active session is rejected so a
 * caller cannot silently erase replay history. */
bool mcu_command_dedup_open_session(mcu_command_dedup_t *dedup,
                                    bool queued_traffic_discarded);
bool mcu_command_dedup_close_session(mcu_command_dedup_t *dedup);

/* Receive one fully decoded ordinary COMMAND. Structurally invalid input and
 * corrupt dependencies return false without modifying the output. A closed
 * session returns a record with no ACK. Every other successful call returns a
 * correlated ACK; only a serially new command dispatches an ordinary event.
 *
 * MOVE and grip commands enter MOVING, HOLD enters HOLDING, and HEARTBEAT
 * preserves the current safe state. Only accepted serially new activity can
 * refresh the software watchdog. */
bool mcu_command_dedup_receive(mcu_command_dedup_t *dedup,
                               mcu_state_machine_t *machine,
                               mcu_watchdog_t *watchdog,
                               const mcu_wire_frame_t *command,
                               uint64_t now_us,
                               mcu_command_record_t *record);

#endif /* MCU_COMMAND_DEDUP_H */
