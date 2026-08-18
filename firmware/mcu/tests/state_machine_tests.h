#ifndef MCU_STATE_MACHINE_TESTS_H
#define MCU_STATE_MACHINE_TESTS_H

#include <stdint.h>

typedef struct {
    uint32_t assertions;
    uint32_t failures;
    uint32_t first_failure;
} mcu_test_report_t;

void mcu_state_machine_run_tests(mcu_test_report_t *report);

#endif /* MCU_STATE_MACHINE_TESTS_H */
