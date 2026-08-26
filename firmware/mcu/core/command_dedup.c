#include "command_dedup.h"

#define MCU_COMMAND_DEDUP_COOKIE 0x44454431u

_Static_assert(sizeof(mcu_command_dedup_t) <= MCU_COMMAND_DEDUP_STORAGE_BUDGET_BYTES,
               "command dedup state exceeds its fixed storage budget");

static bool ordinary_opcode_is_valid(mcu_wire_opcode_t opcode)
{
    return opcode == MCU_WIRE_OPCODE_MOVE || opcode == MCU_WIRE_OPCODE_GRIP_OPEN ||
           opcode == MCU_WIRE_OPCODE_GRIP_CLOSE || opcode == MCU_WIRE_OPCODE_HOLD ||
           opcode == MCU_WIRE_OPCODE_HEARTBEAT;
}

static bool cached_response_is_valid(const mcu_command_replay_entry_t *entry)
{
    if (!entry->valid || entry->command_id > MCU_COMMAND_ID_MAX ||
        !ordinary_opcode_is_valid(entry->opcode)) {
        return false;
    }
    if (entry->result_code == MCU_WIRE_RESULT_ACCEPTED) {
        return entry->fault_code == MCU_WIRE_FAULT_NONE &&
               entry->device_mode >= MCU_WIRE_MODE_IDLE &&
               entry->device_mode <= MCU_WIRE_MODE_STOPPED;
    }
    return entry->result_code == MCU_WIRE_RESULT_REJECTED &&
           (entry->fault_code == MCU_WIRE_FAULT_DUPLICATE_FRAME ||
            entry->fault_code == MCU_WIRE_FAULT_MALFORMED_FRAME) &&
           entry->device_mode == MCU_WIRE_MODE_FAULTED;
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

static void clear_record(mcu_command_record_t *record)
{
    record->outcome = MCU_COMMAND_OUTCOME_NONE;
    record->ack_available = false;
    record->ordinary_event_dispatched = false;
    record->watchdog_refreshed = false;
    clear_frame(&record->ack);
}

static void clear_entry(mcu_command_replay_entry_t *entry)
{
    entry->valid = false;
    entry->command_id = 0u;
    entry->opcode = MCU_WIRE_OPCODE_RESERVED;
    entry->last_retry_count = 0u;
    entry->result_code = MCU_WIRE_RESULT_ACCEPTED;
    entry->fault_code = MCU_WIRE_FAULT_NONE;
    entry->device_mode = MCU_WIRE_MODE_IDLE;
}

static void clear_history(mcu_command_dedup_t *dedup)
{
    unsigned i;

    dedup->has_last_accepted = false;
    dedup->last_accepted_id = 0u;
    dedup->next_slot = 0u;
    for (i = 0u; i < MCU_COMMAND_REPLAY_WINDOW_SIZE; i++) {
        clear_entry(&dedup->entries[i]);
    }
}

void mcu_command_dedup_init(mcu_command_dedup_t *dedup)
{
    if (dedup == 0) {
        return;
    }

    dedup->initialized = MCU_COMMAND_DEDUP_COOKIE;
    dedup->session_open = false;
    clear_history(dedup);
}

bool mcu_command_dedup_is_valid(const mcu_command_dedup_t *dedup)
{
    unsigned i;
    unsigned j;
    unsigned last_matches = 0u;
    unsigned valid_entries = 0u;

    if (dedup == 0 || dedup->initialized != MCU_COMMAND_DEDUP_COOKIE ||
        dedup->next_slot >= MCU_COMMAND_REPLAY_WINDOW_SIZE) {
        return false;
    }
    if (dedup->has_last_accepted && dedup->last_accepted_id > MCU_COMMAND_ID_MAX) {
        return false;
    }

    for (i = 0u; i < MCU_COMMAND_REPLAY_WINDOW_SIZE; i++) {
        const mcu_command_replay_entry_t *entry = &dedup->entries[i];

        if (!entry->valid) {
            continue;
        }
        valid_entries++;
        if (!cached_response_is_valid(entry)) {
            return false;
        }
        if (dedup->has_last_accepted && entry->command_id == dedup->last_accepted_id) {
            last_matches++;
        }
        for (j = i + 1u; j < MCU_COMMAND_REPLAY_WINDOW_SIZE; j++) {
            if (dedup->entries[j].valid && dedup->entries[j].command_id == entry->command_id) {
                return false;
            }
        }
    }

    if (!dedup->session_open) {
        return !dedup->has_last_accepted && valid_entries == 0u && dedup->next_slot == 0u;
    }
    if (!dedup->has_last_accepted) {
        return valid_entries == 0u && dedup->next_slot == 0u;
    }
    return valid_entries > 0u && last_matches == 1u;
}

bool mcu_command_dedup_open_session(mcu_command_dedup_t *dedup,
                                    bool queued_traffic_discarded)
{
    if (!mcu_command_dedup_is_valid(dedup) || dedup->session_open ||
        !queued_traffic_discarded) {
        return false;
    }

    clear_history(dedup);
    dedup->session_open = true;
    return true;
}

bool mcu_command_dedup_close_session(mcu_command_dedup_t *dedup)
{
    if (!mcu_command_dedup_is_valid(dedup)) {
        return false;
    }

    clear_history(dedup);
    dedup->session_open = false;
    return true;
}

static mcu_command_replay_entry_t *find_entry(mcu_command_dedup_t *dedup,
                                               uint16_t command_id)
{
    unsigned i;

    for (i = 0u; i < MCU_COMMAND_REPLAY_WINDOW_SIZE; i++) {
        if (dedup->entries[i].valid && dedup->entries[i].command_id == command_id) {
            return &dedup->entries[i];
        }
    }
    return 0;
}

static mcu_wire_device_mode_t map_mode(mcu_device_mode_t mode)
{
    switch (mode) {
    case MCU_DEVICE_MODE_IDLE:
        return MCU_WIRE_MODE_IDLE;
    case MCU_DEVICE_MODE_MOVING:
        return MCU_WIRE_MODE_MOVING;
    case MCU_DEVICE_MODE_HOLDING:
        return MCU_WIRE_MODE_HOLDING;
    case MCU_DEVICE_MODE_STOPPED:
        return MCU_WIRE_MODE_STOPPED;
    case MCU_DEVICE_MODE_FAULTED:
    case MCU_DEVICE_MODE_COUNT:
    default:
        return MCU_WIRE_MODE_FAULTED;
    }
}

static void make_ack(const mcu_wire_frame_t *command,
                     mcu_wire_result_t result_code,
                     mcu_wire_fault_t fault_code,
                     mcu_wire_device_mode_t device_mode,
                     mcu_wire_frame_t *ack)
{
    clear_frame(ack);
    ack->kind = MCU_WIRE_FRAME_ACK;
    ack->command_id = command->command_id;
    ack->opcode = command->opcode;
    ack->retry_count = command->retry_count;
    ack->result_code = result_code;
    ack->fault_code = fault_code;
    ack->device_mode = device_mode;
}

static void make_cached_ack(const mcu_wire_frame_t *command,
                            const mcu_command_replay_entry_t *entry,
                            mcu_wire_frame_t *ack)
{
    make_ack(command,
             entry->result_code,
             entry->fault_code,
             entry->device_mode,
             ack);
}

static void raise_duplicate_fault(mcu_state_machine_t *machine)
{
    mcu_event_t event;
    mcu_transition_result_t transition;

    event.kind = MCU_EVENT_RAISE_FAULT;
    event.fault_code = MCU_FAULT_DUPLICATE_FRAME;
    event.reset_authorized = false;
    event.cause_cleared = false;
    mcu_sm_dispatch(machine, &event, &transition);
}

static void reject_correlation(mcu_state_machine_t *machine,
                               mcu_watchdog_t *watchdog,
                               const mcu_wire_frame_t *command,
                               uint64_t now_us,
                               mcu_command_outcome_t outcome,
                               mcu_watchdog_activity_t activity,
                               mcu_command_record_t *record)
{
    raise_duplicate_fault(machine);
    clear_record(record);
    record->outcome = outcome;
    record->ack_available = true;
    make_ack(command,
             MCU_WIRE_RESULT_REJECTED,
             MCU_WIRE_FAULT_DUPLICATE_FRAME,
             MCU_WIRE_MODE_FAULTED,
             &record->ack);
    record->watchdog_refreshed =
      mcu_watchdog_note_activity(watchdog, machine, activity, now_us);
}

static mcu_event_kind_t opcode_to_event(mcu_wire_opcode_t opcode)
{
    switch (opcode) {
    case MCU_WIRE_OPCODE_HOLD:
        return MCU_EVENT_BEGIN_HOLD;
    case MCU_WIRE_OPCODE_HEARTBEAT:
        return MCU_EVENT_HEARTBEAT;
    case MCU_WIRE_OPCODE_MOVE:
    case MCU_WIRE_OPCODE_GRIP_OPEN:
    case MCU_WIRE_OPCODE_GRIP_CLOSE:
    case MCU_WIRE_OPCODE_RESERVED:
    case MCU_WIRE_OPCODE_STOP:
    case MCU_WIRE_OPCODE_COUNT:
    default:
        return MCU_EVENT_BEGIN_MOVE;
    }
}

static void dispatch_new_command(mcu_state_machine_t *machine,
                                 const mcu_wire_frame_t *command,
                                 mcu_transition_result_t *transition)
{
    mcu_event_t event;

    event.kind = opcode_to_event(command->opcode);
    event.fault_code = MCU_FAULT_NONE;
    event.reset_authorized = false;
    event.cause_cleared = false;
    mcu_sm_dispatch(machine, &event, transition);
}

static void cache_new_result(mcu_command_dedup_t *dedup,
                             const mcu_wire_frame_t *command,
                             const mcu_wire_frame_t *ack)
{
    mcu_command_replay_entry_t *entry = &dedup->entries[dedup->next_slot];

    entry->valid = true;
    entry->command_id = command->command_id;
    entry->opcode = command->opcode;
    entry->last_retry_count = command->retry_count;
    entry->result_code = ack->result_code;
    entry->fault_code = ack->fault_code;
    entry->device_mode = ack->device_mode;
    dedup->next_slot = (uint8_t)((dedup->next_slot + 1u) % MCU_COMMAND_REPLAY_WINDOW_SIZE);
    dedup->has_last_accepted = true;
    dedup->last_accepted_id = command->command_id;
}

static uint16_t serial_delta(uint16_t candidate, uint16_t last_accepted)
{
    return (uint16_t)((candidate - last_accepted) & MCU_COMMAND_SERIAL_MASK);
}

bool mcu_command_dedup_receive(mcu_command_dedup_t *dedup,
                               mcu_state_machine_t *machine,
                               mcu_watchdog_t *watchdog,
                               const mcu_wire_frame_t *command,
                               uint64_t now_us,
                               mcu_command_record_t *record)
{
    uint16_t arbitration_id;
    uint8_t encoded[MCU_WIRE_DLC];
    uint8_t encoded_length;
    mcu_command_replay_entry_t *entry;
    mcu_transition_result_t transition;
    uint16_t delta;
    bool wrapped;

    if (dedup == 0 || machine == 0 || watchdog == 0 || command == 0 || record == 0 ||
        !mcu_command_dedup_is_valid(dedup) || !mcu_sm_is_valid(machine) ||
        !mcu_watchdog_is_valid(watchdog)) {
        return false;
    }
    if (mcu_frame_encode(command,
                         &arbitration_id,
                         encoded,
                         sizeof(encoded),
                         &encoded_length) != MCU_CODEC_OK ||
        arbitration_id != MCU_CAN_ID_COMMAND || encoded_length != MCU_WIRE_DLC) {
        return false;
    }

    clear_record(record);
    if (!dedup->session_open) {
        record->outcome = MCU_COMMAND_OUTCOME_SESSION_CLOSED;
        return true;
    }

    delta = dedup->has_last_accepted
              ? serial_delta(command->command_id, dedup->last_accepted_id)
              : 1u;
    entry = find_entry(dedup, command->command_id);
    /* A half-range-new candidate wins over an old retained ID with the same
     * numeric value. That is what distinguishes a genuine serial wrap from a
     * delayed old-epoch replay when Wire V1 has no epoch field. */
    if (dedup->has_last_accepted && delta != 0u &&
        delta < MCU_COMMAND_SERIAL_HALF_RANGE) {
        entry = 0;
    }
    if (entry != 0) {
        if (entry->opcode != command->opcode) {
            reject_correlation(machine,
                               watchdog,
                               command,
                               now_us,
                               MCU_COMMAND_OUTCOME_REJECTED_CONFLICT,
                               MCU_WATCHDOG_ACTIVITY_DUPLICATE,
                               record);
            return true;
        }
        if (command->retry_count < entry->last_retry_count) {
            reject_correlation(machine,
                               watchdog,
                               command,
                               now_us,
                               MCU_COMMAND_OUTCOME_REJECTED_RETRY,
                               MCU_WATCHDOG_ACTIVITY_STALE,
                               record);
            return true;
        }

        record->outcome = MCU_COMMAND_OUTCOME_REPLAYED;
        record->ack_available = true;
        make_cached_ack(command, entry, &record->ack);
        record->watchdog_refreshed = mcu_watchdog_note_activity(
          watchdog,
          machine,
          command->retry_count == entry->last_retry_count
            ? MCU_WATCHDOG_ACTIVITY_DUPLICATE
            : MCU_WATCHDOG_ACTIVITY_RETRY,
          now_us);
        entry->last_retry_count = command->retry_count;
        return true;
    }

    if (dedup->has_last_accepted &&
        (delta == 0u || delta >= MCU_COMMAND_SERIAL_HALF_RANGE)) {
        reject_correlation(machine,
                           watchdog,
                           command,
                           now_us,
                           MCU_COMMAND_OUTCOME_REJECTED_STALE,
                           MCU_WATCHDOG_ACTIVITY_STALE,
                           record);
        return true;
    }

    wrapped = dedup->has_last_accepted && command->command_id < dedup->last_accepted_id;
    if (wrapped) {
        /* A forward max-to-zero transition begins a new serial epoch. Wire V1
         * carries no epoch bit, so no pre-wrap cache entry may survive. */
        clear_history(dedup);
    }

    dispatch_new_command(machine, command, &transition);
    record->outcome = transition.result_code == MCU_RESULT_ACCEPTED
                        ? MCU_COMMAND_OUTCOME_ACCEPTED_NEW
                        : MCU_COMMAND_OUTCOME_REJECTED_NEW;
    record->ack_available = true;
    record->ordinary_event_dispatched = true;
    if (transition.result_code == MCU_RESULT_ACCEPTED) {
        make_ack(command,
                 MCU_WIRE_RESULT_ACCEPTED,
                 MCU_WIRE_FAULT_NONE,
                 map_mode(transition.device_mode),
                 &record->ack);
    } else {
        make_ack(command,
                 MCU_WIRE_RESULT_REJECTED,
                 MCU_WIRE_FAULT_MALFORMED_FRAME,
                 MCU_WIRE_MODE_FAULTED,
                 &record->ack);
    }
    cache_new_result(dedup, command, &record->ack);
    record->watchdog_refreshed = mcu_watchdog_note_activity(
      watchdog, machine, MCU_WATCHDOG_ACTIVITY_VALID_NEW, now_us);
    return true;
}
