#ifndef MCU_HAL_HOST_TEST_H
#define MCU_HAL_HOST_TEST_H

#include <stdbool.h>
#include <stdint.h>

#include "hal.h"

/* Fixed test-only queues for the x86_64 fake HAL. They model bounded
 * transport handoff and deterministic arbitration; they are not a board CAN
 * driver or evidence of physical delivery. */
#define HAL_HOST_CAN_QUEUE_CAPACITY 16u

void hal_host_can_reset(void);
bool hal_host_can_inject_rx(const hal_can_frame *frame);
bool hal_host_can_take_tx(hal_can_frame *frame);
uint8_t hal_host_can_rx_count(void);
uint8_t hal_host_can_tx_count(void);

#endif /* MCU_HAL_HOST_TEST_H */
