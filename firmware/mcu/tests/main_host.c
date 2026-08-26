#include <stdio.h>

#include "frame_codec_tests.h"
#include "state_machine_tests.h"
#include "watchdog_tests.h"

int main(void)
{
    mcu_test_report_t state_machine_report;
    mcu_test_report_t frame_codec_report;
    mcu_test_report_t watchdog_report;

    mcu_state_machine_run_tests(&state_machine_report);
    printf("[mcu-host] state-machine assertions=%u failures=%u first_failure=%u\n",
           (unsigned)state_machine_report.assertions,
           (unsigned)state_machine_report.failures,
           (unsigned)state_machine_report.first_failure);

    mcu_frame_codec_run_tests(&frame_codec_report);
    printf("[mcu-host] frame-codec assertions=%u failures=%u first_failure=%u\n",
           (unsigned)frame_codec_report.assertions,
           (unsigned)frame_codec_report.failures,
           (unsigned)frame_codec_report.first_failure);

    mcu_watchdog_run_tests(&watchdog_report);
    printf("[mcu-host] watchdog assertions=%u failures=%u first_failure=%u\n",
           (unsigned)watchdog_report.assertions,
           (unsigned)watchdog_report.failures,
           (unsigned)watchdog_report.first_failure);
    return state_machine_report.failures == 0u && frame_codec_report.failures == 0u &&
             watchdog_report.failures == 0u
             ? 0
             : 1;
}
