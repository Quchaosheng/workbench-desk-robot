#include <stdio.h>

#include "state_machine_tests.h"

int main(void)
{
    mcu_test_report_t report;

    mcu_state_machine_run_tests(&report);
    printf("[mcu-host] state-machine assertions=%u failures=%u first_failure=%u\n",
           (unsigned)report.assertions,
           (unsigned)report.failures,
           (unsigned)report.first_failure);
    return report.failures == 0u ? 0 : 1;
}
