#include "state_machine_tests.h"

#include "state_machine.h"

typedef struct {
    mcu_state_t state;
    mcu_result_code_t result_code;
} expected_transition_t;

static const expected_transition_t transition_table[MCU_STATE_COUNT][MCU_EVENT_COUNT] = {
    [MCU_STATE_IDLE] = {
        [MCU_EVENT_BEGIN_MOVE] = {MCU_STATE_EXECUTING, MCU_RESULT_ACCEPTED},
        [MCU_EVENT_BEGIN_HOLD] = {MCU_STATE_EXECUTING, MCU_RESULT_ACCEPTED},
        [MCU_EVENT_COMPLETE] = {MCU_STATE_IDLE, MCU_RESULT_REJECTED},
        [MCU_EVENT_HEARTBEAT] = {MCU_STATE_IDLE, MCU_RESULT_ACCEPTED},
        [MCU_EVENT_STOP] = {MCU_STATE_SAFE_STOP, MCU_RESULT_ACCEPTED},
        [MCU_EVENT_WATCHDOG_EXPIRED] = {MCU_STATE_FAULT, MCU_RESULT_ACCEPTED},
        [MCU_EVENT_RAISE_FAULT] = {MCU_STATE_FAULT, MCU_RESULT_ACCEPTED},
        [MCU_EVENT_TRUSTED_RESET] = {MCU_STATE_IDLE, MCU_RESULT_ACCEPTED},
    },
    [MCU_STATE_EXECUTING] = {
        [MCU_EVENT_BEGIN_MOVE] = {MCU_STATE_FAULT, MCU_RESULT_REJECTED},
        [MCU_EVENT_BEGIN_HOLD] = {MCU_STATE_FAULT, MCU_RESULT_REJECTED},
        [MCU_EVENT_COMPLETE] = {MCU_STATE_IDLE, MCU_RESULT_ACCEPTED},
        [MCU_EVENT_HEARTBEAT] = {MCU_STATE_EXECUTING, MCU_RESULT_ACCEPTED},
        [MCU_EVENT_STOP] = {MCU_STATE_SAFE_STOP, MCU_RESULT_ACCEPTED},
        [MCU_EVENT_WATCHDOG_EXPIRED] = {MCU_STATE_FAULT, MCU_RESULT_ACCEPTED},
        [MCU_EVENT_RAISE_FAULT] = {MCU_STATE_FAULT, MCU_RESULT_ACCEPTED},
        [MCU_EVENT_TRUSTED_RESET] = {MCU_STATE_FAULT, MCU_RESULT_REJECTED},
    },
    [MCU_STATE_SAFE_STOP] = {
        [MCU_EVENT_BEGIN_MOVE] = {MCU_STATE_FAULT, MCU_RESULT_REJECTED},
        [MCU_EVENT_BEGIN_HOLD] = {MCU_STATE_FAULT, MCU_RESULT_REJECTED},
        [MCU_EVENT_COMPLETE] = {MCU_STATE_SAFE_STOP, MCU_RESULT_REJECTED},
        [MCU_EVENT_HEARTBEAT] = {MCU_STATE_SAFE_STOP, MCU_RESULT_ACCEPTED},
        [MCU_EVENT_STOP] = {MCU_STATE_SAFE_STOP, MCU_RESULT_ACCEPTED},
        [MCU_EVENT_WATCHDOG_EXPIRED] = {MCU_STATE_FAULT, MCU_RESULT_ACCEPTED},
        [MCU_EVENT_RAISE_FAULT] = {MCU_STATE_FAULT, MCU_RESULT_ACCEPTED},
        [MCU_EVENT_TRUSTED_RESET] = {MCU_STATE_IDLE, MCU_RESULT_ACCEPTED},
    },
    [MCU_STATE_FAULT] = {
        [MCU_EVENT_BEGIN_MOVE] = {MCU_STATE_FAULT, MCU_RESULT_REJECTED},
        [MCU_EVENT_BEGIN_HOLD] = {MCU_STATE_FAULT, MCU_RESULT_REJECTED},
        [MCU_EVENT_COMPLETE] = {MCU_STATE_FAULT, MCU_RESULT_REJECTED},
        [MCU_EVENT_HEARTBEAT] = {MCU_STATE_FAULT, MCU_RESULT_REJECTED},
        [MCU_EVENT_STOP] = {MCU_STATE_FAULT, MCU_RESULT_REJECTED},
        [MCU_EVENT_WATCHDOG_EXPIRED] = {MCU_STATE_FAULT, MCU_RESULT_ACCEPTED},
        [MCU_EVENT_RAISE_FAULT] = {MCU_STATE_FAULT, MCU_RESULT_ACCEPTED},
        [MCU_EVENT_TRUSTED_RESET] = {MCU_STATE_IDLE, MCU_RESULT_ACCEPTED},
    },
};

static void check(mcu_test_report_t *report, bool condition)
{
    report->assertions++;
    if (!condition) {
        report->failures++;
        if (report->first_failure == 0u) {
            report->first_failure = report->assertions;
        }
    }
}

static void seed_machine(mcu_state_machine_t *machine, mcu_state_t state)
{
    machine->state = state;
    machine->fault_code = MCU_FAULT_NONE;

    switch (state) {
    case MCU_STATE_IDLE:
        machine->device_mode = MCU_DEVICE_MODE_IDLE;
        break;
    case MCU_STATE_EXECUTING:
        machine->device_mode = MCU_DEVICE_MODE_MOVING;
        break;
    case MCU_STATE_SAFE_STOP:
        machine->device_mode = MCU_DEVICE_MODE_STOPPED;
        break;
    case MCU_STATE_FAULT:
        machine->device_mode = MCU_DEVICE_MODE_FAULTED;
        machine->fault_code = MCU_FAULT_WATCHDOG_EXPIRED;
        break;
    case MCU_STATE_COUNT:
    default:
        machine->device_mode = MCU_DEVICE_MODE_FAULTED;
        machine->fault_code = MCU_FAULT_MALFORMED_FRAME;
        break;
    }
}

static void init_event(mcu_event_t *event, mcu_event_kind_t kind)
{
    event->kind = kind;
    event->fault_code = MCU_FAULT_LINK_LOST;
    event->reset_authorized = true;
    event->cause_cleared = true;
}

#define DISPATCH_KIND(machine, kind, result) \
    do { \
        mcu_event_t dispatch_event; \
        init_event(&dispatch_event, (kind)); \
        mcu_sm_dispatch((machine), &dispatch_event, (result)); \
    } while (0)

static void check_result_invariants(mcu_test_report_t *report,
                                    const mcu_state_machine_t *machine,
                                    const mcu_transition_result_t *result)
{
    check(report, mcu_sm_is_valid(machine));
    check(report, result->state == machine->state);
    check(report, result->device_mode == machine->device_mode);
    check(report, result->fault_code == machine->fault_code);
    check(report, result->execution_active == (machine->state == MCU_STATE_EXECUTING));
    check(report, result->force_safe_outputs == (machine->state != MCU_STATE_EXECUTING));
    check(report, result->execution_active != result->force_safe_outputs);
}

static void test_exhaustive_transition_table(mcu_test_report_t *report)
{
    mcu_state_t state;
    mcu_event_kind_t kind;

    for (state = MCU_STATE_IDLE; state < MCU_STATE_COUNT; state++) {
        for (kind = MCU_EVENT_BEGIN_MOVE; kind < MCU_EVENT_COUNT; kind++) {
            mcu_state_machine_t machine;
            mcu_event_t event;
            mcu_transition_result_t result;
            const expected_transition_t *expected = &transition_table[state][kind];

            init_event(&event, kind);
            seed_machine(&machine, state);
            mcu_sm_dispatch(&machine, &event, &result);

            check(report, result.previous_state == state);
            check(report, result.state == expected->state);
            check(report, result.result_code == expected->result_code);
            check_result_invariants(report, &machine, &result);
        }
    }
}

static void test_protocol_mode_mapping(mcu_test_report_t *report)
{
    mcu_state_machine_t machine;
    mcu_transition_result_t result;

    mcu_sm_init(&machine);
    check(report, machine.state == MCU_STATE_IDLE);
    check(report, machine.device_mode == MCU_DEVICE_MODE_IDLE);
    check(report, machine.fault_code == MCU_FAULT_NONE);

    DISPATCH_KIND(&machine, MCU_EVENT_BEGIN_MOVE, &result);
    check(report, result.device_mode == MCU_DEVICE_MODE_MOVING);
    DISPATCH_KIND(&machine, MCU_EVENT_COMPLETE, &result);
    check(report, result.device_mode == MCU_DEVICE_MODE_IDLE);
    DISPATCH_KIND(&machine, MCU_EVENT_BEGIN_HOLD, &result);
    check(report, result.device_mode == MCU_DEVICE_MODE_HOLDING);
    DISPATCH_KIND(&machine, MCU_EVENT_STOP, &result);
    check(report, result.device_mode == MCU_DEVICE_MODE_STOPPED);
}

static void test_stop_is_idempotent_and_highest_priority(mcu_test_report_t *report)
{
    mcu_state_machine_t machine;
    mcu_transition_result_t first;
    mcu_transition_result_t second;

    mcu_sm_init(&machine);
    DISPATCH_KIND(&machine, MCU_EVENT_BEGIN_MOVE, &first);
    DISPATCH_KIND(&machine, MCU_EVENT_STOP, &first);
    DISPATCH_KIND(&machine, MCU_EVENT_STOP, &second);

    check(report, first.result_code == MCU_RESULT_ACCEPTED);
    check(report, first.state == MCU_STATE_SAFE_STOP);
    check(report, second.result_code == MCU_RESULT_ACCEPTED);
    check(report, second.previous_state == MCU_STATE_SAFE_STOP);
    check(report, second.state == MCU_STATE_SAFE_STOP);
    check(report, second.response_fault_code == MCU_FAULT_NONE);
    check(report, second.force_safe_outputs);
}

static void test_faulted_stop_preserves_original_cause(mcu_test_report_t *report)
{
    mcu_state_machine_t machine;
    mcu_transition_result_t result;

    seed_machine(&machine, MCU_STATE_FAULT);
    DISPATCH_KIND(&machine, MCU_EVENT_STOP, &result);

    check(report, result.result_code == MCU_RESULT_REJECTED);
    check(report, result.reason == MCU_REASON_STOP_REJECTED);
    check(report, result.state == MCU_STATE_FAULT);
    check(report, result.fault_code == MCU_FAULT_WATCHDOG_EXPIRED);
    check(report, result.response_fault_code == MCU_FAULT_STOP_REJECTED);
    check(report, result.force_safe_outputs);
}

static void test_reset_requires_both_trusted_gates(mcu_test_report_t *report)
{
    mcu_state_machine_t machine;
    mcu_event_t reset;
    mcu_transition_result_t result;

    init_event(&reset, MCU_EVENT_TRUSTED_RESET);
    seed_machine(&machine, MCU_STATE_SAFE_STOP);
    reset.reset_authorized = false;
    mcu_sm_dispatch(&machine, &reset, &result);
    check(report, result.result_code == MCU_RESULT_REJECTED);
    check(report, result.reason == MCU_REASON_RESET_NOT_AUTHORIZED);
    check(report, machine.state == MCU_STATE_SAFE_STOP);

    reset.reset_authorized = true;
    reset.cause_cleared = false;
    mcu_sm_dispatch(&machine, &reset, &result);
    check(report, result.result_code == MCU_RESULT_REJECTED);
    check(report, result.reason == MCU_REASON_RESET_CAUSE_ACTIVE);
    check(report, machine.state == MCU_STATE_SAFE_STOP);

    reset.cause_cleared = true;
    mcu_sm_dispatch(&machine, &reset, &result);
    check(report, result.result_code == MCU_RESULT_ACCEPTED);
    check(report, result.state == MCU_STATE_IDLE);
    check(report, !result.execution_active);

    seed_machine(&machine, MCU_STATE_FAULT);
    reset.reset_authorized = false;
    mcu_sm_dispatch(&machine, &reset, &result);
    check(report, result.state == MCU_STATE_FAULT);
    check(report, result.fault_code == MCU_FAULT_WATCHDOG_EXPIRED);
}

static void test_watchdog_and_faults_are_latched(mcu_test_report_t *report)
{
    mcu_state_machine_t machine;
    mcu_transition_result_t result;
    mcu_event_t fault;

    init_event(&fault, MCU_EVENT_RAISE_FAULT);
    mcu_sm_init(&machine);
    DISPATCH_KIND(&machine, MCU_EVENT_BEGIN_MOVE, &result);
    DISPATCH_KIND(&machine, MCU_EVENT_WATCHDOG_EXPIRED, &result);
    check(report, result.state == MCU_STATE_FAULT);
    check(report, result.fault_code == MCU_FAULT_WATCHDOG_EXPIRED);
    check(report, !result.execution_active);
    check(report, result.force_safe_outputs);

    fault.fault_code = MCU_FAULT_LINK_LOST;
    mcu_sm_dispatch(&machine, &fault, &result);
    check(report, result.state == MCU_STATE_FAULT);
    check(report, result.fault_code == MCU_FAULT_WATCHDOG_EXPIRED);

    DISPATCH_KIND(&machine, MCU_EVENT_BEGIN_MOVE, &result);
    check(report, result.result_code == MCU_RESULT_REJECTED);
    check(report, result.state == MCU_STATE_FAULT);
    check(report, result.fault_code == MCU_FAULT_WATCHDOG_EXPIRED);
}

static void test_invalid_inputs_fail_closed(mcu_test_report_t *report)
{
    mcu_state_machine_t machine;
    mcu_event_t event;
    mcu_transition_result_t result;

    init_event(&event, MCU_EVENT_RAISE_FAULT);
    mcu_sm_init(&machine);
    event.fault_code = MCU_FAULT_NONE;
    mcu_sm_dispatch(&machine, &event, &result);
    check(report, result.result_code == MCU_RESULT_REJECTED);
    check(report, result.reason == MCU_REASON_INVALID_ARGUMENT);
    check(report, result.state == MCU_STATE_FAULT);
    check(report, result.fault_code == MCU_FAULT_MALFORMED_FRAME);

    mcu_sm_init(&machine);
    init_event(&event, MCU_EVENT_COUNT);
    mcu_sm_dispatch(&machine, &event, &result);
    check(report, result.result_code == MCU_RESULT_REJECTED);
    check(report, result.reason == MCU_REASON_INVALID_EVENT);
    check(report, result.state == MCU_STATE_FAULT);
    check(report, result.force_safe_outputs);

    mcu_sm_init(&machine);
    machine.device_mode = MCU_DEVICE_MODE_MOVING;
    DISPATCH_KIND(&machine, MCU_EVENT_HEARTBEAT, &result);
    check(report, result.result_code == MCU_RESULT_REJECTED);
    check(report, result.reason == MCU_REASON_INVALID_STATE);
    check(report, result.state == MCU_STATE_FAULT);
    check(report, result.fault_code == MCU_FAULT_MALFORMED_FRAME);

    mcu_sm_init(&machine);
    mcu_sm_dispatch(&machine, 0, &result);
    check(report, result.result_code == MCU_RESULT_REJECTED);
    check(report, result.reason == MCU_REASON_INVALID_ARGUMENT);
    check(report, result.state == MCU_STATE_FAULT);
    check(report, result.fault_code == MCU_FAULT_MALFORMED_FRAME);

    mcu_sm_init(&machine);
    init_event(&event, MCU_EVENT_BEGIN_MOVE);
    mcu_sm_dispatch(&machine, &event, 0);
    check(report, machine.state == MCU_STATE_IDLE);
    check(report, machine.device_mode == MCU_DEVICE_MODE_IDLE);
    check(report, machine.fault_code == MCU_FAULT_NONE);
    check(report, mcu_sm_is_valid(&machine));

    DISPATCH_KIND(0, MCU_EVENT_STOP, &result);
    check(report, result.result_code == MCU_RESULT_REJECTED);
    check(report, result.reason == MCU_REASON_INVALID_ARGUMENT);
    check(report, result.state == MCU_STATE_FAULT);
    check(report, result.force_safe_outputs);
}

static void test_nominal_virtual_mcu_parity_vector(mcu_test_report_t *report)
{
    mcu_state_machine_t machine;
    mcu_event_t reset;
    mcu_transition_result_t result;

    init_event(&reset, MCU_EVENT_TRUSTED_RESET);
    mcu_sm_init(&machine);
    DISPATCH_KIND(&machine, MCU_EVENT_BEGIN_MOVE, &result);
    check(report, result.state == MCU_STATE_EXECUTING);
    DISPATCH_KIND(&machine, MCU_EVENT_COMPLETE, &result);
    check(report, result.state == MCU_STATE_IDLE);
    DISPATCH_KIND(&machine, MCU_EVENT_BEGIN_MOVE, &result);
    check(report, result.state == MCU_STATE_EXECUTING);
    DISPATCH_KIND(&machine, MCU_EVENT_STOP, &result);
    check(report, result.state == MCU_STATE_SAFE_STOP);
    mcu_sm_dispatch(&machine, &reset, &result);
    check(report, result.state == MCU_STATE_IDLE);
    DISPATCH_KIND(&machine, MCU_EVENT_WATCHDOG_EXPIRED, &result);
    check(report, result.state == MCU_STATE_FAULT);
}

static void test_deterministic_replay(mcu_test_report_t *report)
{
    static const mcu_event_kind_t sequence[] = {
        MCU_EVENT_BEGIN_MOVE,
        MCU_EVENT_HEARTBEAT,
        MCU_EVENT_STOP,
        MCU_EVENT_STOP,
        MCU_EVENT_TRUSTED_RESET,
        MCU_EVENT_BEGIN_HOLD,
        MCU_EVENT_COMPLETE,
    };
    mcu_state_machine_t first;
    mcu_state_machine_t second;
    unsigned i;

    mcu_sm_init(&first);
    mcu_sm_init(&second);
    for (i = 0; i < sizeof(sequence) / sizeof(sequence[0]); i++) {
        mcu_transition_result_t first_result;
        mcu_transition_result_t second_result;

        DISPATCH_KIND(&first, sequence[i], &first_result);
        DISPATCH_KIND(&second, sequence[i], &second_result);

        check(report, first_result.result_code == second_result.result_code);
        check(report, first_result.reason == second_result.reason);
        check(report, first_result.state == second_result.state);
        check(report, first_result.device_mode == second_result.device_mode);
        check(report, first_result.fault_code == second_result.fault_code);
        check(report, first_result.response_fault_code == second_result.response_fault_code);
    }
}

void mcu_state_machine_run_tests(mcu_test_report_t *report)
{
    if (report == 0) {
        return;
    }

    report->assertions = 0u;
    report->failures = 0u;
    report->first_failure = 0u;

    test_exhaustive_transition_table(report);
    test_protocol_mode_mapping(report);
    test_stop_is_idempotent_and_highest_priority(report);
    test_faulted_stop_preserves_original_cause(report);
    test_reset_requires_both_trusted_gates(report);
    test_watchdog_and_faults_are_latched(report);
    test_invalid_inputs_fail_closed(report);
    test_nominal_virtual_mcu_parity_vector(report);
    test_deterministic_replay(report);
}
