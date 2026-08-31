#include <stdio.h>

#include "can_bridge_host_tests.h"
#include "can_bridge_tests.h"
#include "command_dedup_tests.h"
#include "frame_codec_tests.h"
#include "state_machine_tests.h"
#include "watchdog_tests.h"

int main(void)
{
    mcu_test_report_t state_machine_report;
    mcu_test_report_t frame_codec_report;
    mcu_test_report_t watchdog_report;
    mcu_test_report_t command_dedup_report;
    mcu_test_report_t can_bridge_report;
    mcu_test_report_t can_bridge_host_report;

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

    mcu_command_dedup_run_tests(&command_dedup_report);
    printf("[mcu-host] command-dedup assertions=%u failures=%u first_failure=%u\n",
           (unsigned)command_dedup_report.assertions,
           (unsigned)command_dedup_report.failures,
           (unsigned)command_dedup_report.first_failure);

    mcu_can_bridge_run_tests(&can_bridge_report);
    printf("[mcu-host] can-bridge assertions=%u failures=%u first_failure=%u\n",
           (unsigned)can_bridge_report.assertions,
           (unsigned)can_bridge_report.failures,
           (unsigned)can_bridge_report.first_failure);

    mcu_can_bridge_host_run_tests(&can_bridge_host_report);
    printf("[mcu-host] can-bridge-host assertions=%u failures=%u first_failure=%u\n",
           (unsigned)can_bridge_host_report.assertions,
           (unsigned)can_bridge_host_report.failures,
           (unsigned)can_bridge_host_report.first_failure);
    return state_machine_report.failures == 0u && frame_codec_report.failures == 0u &&
             watchdog_report.failures == 0u && command_dedup_report.failures == 0u &&
             can_bridge_report.failures == 0u && can_bridge_host_report.failures == 0u
             ? 0
             : 1;
}
