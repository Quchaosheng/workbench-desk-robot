#include "state_machine.h"

static bool fault_code_is_valid(mcu_fault_code_t fault_code)
{
    return fault_code >= MCU_FAULT_NONE && fault_code < MCU_FAULT_COUNT;
}

static bool active_fault_is_valid(mcu_fault_code_t fault_code)
{
    return fault_code > MCU_FAULT_NONE && fault_code < MCU_FAULT_COUNT;
}

bool mcu_sm_is_valid(const mcu_state_machine_t *machine)
{
    if (machine == 0 || !fault_code_is_valid(machine->fault_code)) {
        return false;
    }

    switch (machine->state) {
    case MCU_STATE_IDLE:
        return machine->device_mode == MCU_DEVICE_MODE_IDLE && machine->fault_code == MCU_FAULT_NONE;
    case MCU_STATE_EXECUTING:
        return (machine->device_mode == MCU_DEVICE_MODE_MOVING ||
                machine->device_mode == MCU_DEVICE_MODE_HOLDING) &&
               machine->fault_code == MCU_FAULT_NONE;
    case MCU_STATE_SAFE_STOP:
        return machine->device_mode == MCU_DEVICE_MODE_STOPPED && machine->fault_code == MCU_FAULT_NONE;
    case MCU_STATE_FAULT:
        return machine->device_mode == MCU_DEVICE_MODE_FAULTED && active_fault_is_valid(machine->fault_code);
    case MCU_STATE_COUNT:
    default:
        return false;
    }
}

void mcu_sm_init(mcu_state_machine_t *machine)
{
    if (machine == 0) {
        return;
    }

    machine->state = MCU_STATE_IDLE;
    machine->device_mode = MCU_DEVICE_MODE_IDLE;
    machine->fault_code = MCU_FAULT_NONE;
}

static void enter_idle(mcu_state_machine_t *machine)
{
    machine->state = MCU_STATE_IDLE;
    machine->device_mode = MCU_DEVICE_MODE_IDLE;
    machine->fault_code = MCU_FAULT_NONE;
}

static void enter_executing(mcu_state_machine_t *machine, mcu_device_mode_t mode)
{
    machine->state = MCU_STATE_EXECUTING;
    machine->device_mode = mode;
    machine->fault_code = MCU_FAULT_NONE;
}

static void enter_safe_stop(mcu_state_machine_t *machine)
{
    machine->state = MCU_STATE_SAFE_STOP;
    machine->device_mode = MCU_DEVICE_MODE_STOPPED;
    machine->fault_code = MCU_FAULT_NONE;
}

static void enter_fault(mcu_state_machine_t *machine, mcu_fault_code_t fault_code)
{
    /* Preserve the first active cause. Later traffic must not overwrite the
     * evidence that originally latched the fault. */
    if (machine->state != MCU_STATE_FAULT || !active_fault_is_valid(machine->fault_code)) {
        machine->fault_code = fault_code;
    }
    machine->state = MCU_STATE_FAULT;
    machine->device_mode = MCU_DEVICE_MODE_FAULTED;
}

static void make_result(mcu_transition_result_t *result,
                        const mcu_state_machine_t *machine,
                        mcu_state_t previous_state,
                        mcu_result_code_t result_code,
                        mcu_result_reason_t reason,
                        mcu_fault_code_t response_fault_code)
{
    result->result_code = result_code;
    result->reason = reason;
    result->previous_state = previous_state;
    result->state = machine->state;
    result->device_mode = machine->device_mode;
    result->fault_code = machine->fault_code;
    result->response_fault_code = response_fault_code;
    result->execution_active = machine->state == MCU_STATE_EXECUTING;
    result->force_safe_outputs = machine->state != MCU_STATE_EXECUTING;
}

static void null_machine_result(mcu_transition_result_t *result)
{
    mcu_state_machine_t safe;

    safe.state = MCU_STATE_FAULT;
    safe.device_mode = MCU_DEVICE_MODE_FAULTED;
    safe.fault_code = MCU_FAULT_MALFORMED_FRAME;
    make_result(result,
                &safe,
                MCU_STATE_FAULT,
                MCU_RESULT_REJECTED,
                MCU_REASON_INVALID_ARGUMENT,
                MCU_FAULT_MALFORMED_FRAME);
}

static void reject_start(mcu_state_machine_t *machine,
                          mcu_state_t previous_state,
                          mcu_transition_result_t *result)
{
    enter_fault(machine, MCU_FAULT_MALFORMED_FRAME);
    make_result(result,
                machine,
                previous_state,
                MCU_RESULT_REJECTED,
                MCU_REASON_INVALID_TRANSITION,
                MCU_FAULT_MALFORMED_FRAME);
}

static void handle_reset(mcu_state_machine_t *machine,
                         mcu_state_t previous_state,
                         const mcu_event_t *event,
                         mcu_transition_result_t *result)
{
    if (!event->reset_authorized) {
        make_result(result,
                    machine,
                    previous_state,
                    MCU_RESULT_REJECTED,
                    MCU_REASON_RESET_NOT_AUTHORIZED,
                    MCU_FAULT_NONE);
        return;
    }
    if (!event->cause_cleared) {
        make_result(result,
                    machine,
                    previous_state,
                    MCU_RESULT_REJECTED,
                    MCU_REASON_RESET_CAUSE_ACTIVE,
                    MCU_FAULT_NONE);
        return;
    }
    if (machine->state == MCU_STATE_EXECUTING) {
        enter_fault(machine, MCU_FAULT_MALFORMED_FRAME);
        make_result(result,
                    machine,
                    previous_state,
                    MCU_RESULT_REJECTED,
                    MCU_REASON_INVALID_TRANSITION,
                    MCU_FAULT_MALFORMED_FRAME);
        return;
    }

    enter_idle(machine);
    make_result(result, machine, previous_state, MCU_RESULT_ACCEPTED, MCU_REASON_NONE, MCU_FAULT_NONE);
}

void mcu_sm_dispatch(mcu_state_machine_t *machine,
                     const mcu_event_t *event,
                     mcu_transition_result_t *result)
{
    mcu_transition_result_t ignored_result;
    bool result_missing;
    mcu_state_t previous_state;

    result_missing = result == 0;
    if (result_missing) {
        /* A caller cannot suppress safety processing by omitting the output
         * buffer. The local buffer preserves the normal dispatch path for
         * STOP, while non-STOP events are rejected below as invalid input. */
        result = &ignored_result;
    }
    if (machine == 0) {
        null_machine_result(result);
        return;
    }

    previous_state = machine->state;
    if (!mcu_sm_is_valid(machine)) {
        machine->state = MCU_STATE_FAULT;
        machine->device_mode = MCU_DEVICE_MODE_FAULTED;
        machine->fault_code = MCU_FAULT_MALFORMED_FRAME;
        make_result(result,
                    machine,
                    previous_state,
                    MCU_RESULT_REJECTED,
                    MCU_REASON_INVALID_STATE,
                    MCU_FAULT_MALFORMED_FRAME);
        return;
    }
    if (event == 0) {
        enter_fault(machine, MCU_FAULT_MALFORMED_FRAME);
        make_result(result,
                    machine,
                    previous_state,
                    MCU_RESULT_REJECTED,
                    MCU_REASON_INVALID_ARGUMENT,
                    MCU_FAULT_MALFORMED_FRAME);
        return;
    }
    if (result_missing && event->kind != MCU_EVENT_STOP) {
        enter_fault(machine, MCU_FAULT_MALFORMED_FRAME);
        make_result(result,
                    machine,
                    previous_state,
                    MCU_RESULT_REJECTED,
                    MCU_REASON_INVALID_ARGUMENT,
                    MCU_FAULT_MALFORMED_FRAME);
        return;
    }

    switch (event->kind) {
    case MCU_EVENT_BEGIN_MOVE:
        if (machine->state != MCU_STATE_IDLE) {
            reject_start(machine, previous_state, result);
            return;
        }
        enter_executing(machine, MCU_DEVICE_MODE_MOVING);
        make_result(result, machine, previous_state, MCU_RESULT_ACCEPTED, MCU_REASON_NONE, MCU_FAULT_NONE);
        return;

    case MCU_EVENT_BEGIN_HOLD:
        if (machine->state != MCU_STATE_IDLE) {
            reject_start(machine, previous_state, result);
            return;
        }
        enter_executing(machine, MCU_DEVICE_MODE_HOLDING);
        make_result(result, machine, previous_state, MCU_RESULT_ACCEPTED, MCU_REASON_NONE, MCU_FAULT_NONE);
        return;

    case MCU_EVENT_COMPLETE:
        if (machine->state != MCU_STATE_EXECUTING) {
            make_result(result,
                        machine,
                        previous_state,
                        MCU_RESULT_REJECTED,
                        MCU_REASON_INVALID_TRANSITION,
                        MCU_FAULT_NONE);
            return;
        }
        enter_idle(machine);
        make_result(result, machine, previous_state, MCU_RESULT_ACCEPTED, MCU_REASON_NONE, MCU_FAULT_NONE);
        return;

    case MCU_EVENT_HEARTBEAT:
        if (machine->state == MCU_STATE_FAULT) {
            make_result(result,
                        machine,
                        previous_state,
                        MCU_RESULT_REJECTED,
                        MCU_REASON_INVALID_TRANSITION,
                        machine->fault_code);
            return;
        }
        make_result(result, machine, previous_state, MCU_RESULT_ACCEPTED, MCU_REASON_NONE, MCU_FAULT_NONE);
        return;

    case MCU_EVENT_STOP:
        if (machine->state == MCU_STATE_FAULT) {
            make_result(result,
                        machine,
                        previous_state,
                        MCU_RESULT_REJECTED,
                        MCU_REASON_STOP_REJECTED,
                        MCU_FAULT_STOP_REJECTED);
            return;
        }
        enter_safe_stop(machine);
        make_result(result, machine, previous_state, MCU_RESULT_ACCEPTED, MCU_REASON_NONE, MCU_FAULT_NONE);
        return;

    case MCU_EVENT_WATCHDOG_EXPIRED:
        enter_fault(machine, MCU_FAULT_WATCHDOG_EXPIRED);
        make_result(result,
                    machine,
                    previous_state,
                    MCU_RESULT_ACCEPTED,
                    MCU_REASON_NONE,
                    MCU_FAULT_WATCHDOG_EXPIRED);
        return;

    case MCU_EVENT_RAISE_FAULT:
        if (!active_fault_is_valid(event->fault_code) || event->fault_code == MCU_FAULT_STOP_REJECTED) {
            enter_fault(machine, MCU_FAULT_MALFORMED_FRAME);
            make_result(result,
                        machine,
                        previous_state,
                        MCU_RESULT_REJECTED,
                        MCU_REASON_INVALID_ARGUMENT,
                        MCU_FAULT_MALFORMED_FRAME);
            return;
        }
        enter_fault(machine, event->fault_code);
        make_result(result, machine, previous_state, MCU_RESULT_ACCEPTED, MCU_REASON_NONE, event->fault_code);
        return;

    case MCU_EVENT_TRUSTED_RESET:
        handle_reset(machine, previous_state, event, result);
        return;

    case MCU_EVENT_COUNT:
    default:
        enter_fault(machine, MCU_FAULT_MALFORMED_FRAME);
        make_result(result,
                    machine,
                    previous_state,
                    MCU_RESULT_REJECTED,
                    MCU_REASON_INVALID_EVENT,
                    MCU_FAULT_MALFORMED_FRAME);
        return;
    }
}
