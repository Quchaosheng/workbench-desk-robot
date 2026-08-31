#include "hal.h"
#include "hal_host_test.h"

#include <stdio.h>

static uint64_t host_now_us;
static uint64_t host_timer_deadline_us;
static uint32_t host_wdt_timeout_ms;
static uint64_t host_wdt_deadline_us;
static uint32_t host_wdt_feeds;
static bool host_wdt_running;
static bool host_can_initialized;
static hal_can_frame host_can_rx[HAL_HOST_CAN_QUEUE_CAPACITY];
static hal_can_frame host_can_tx[HAL_HOST_CAN_QUEUE_CAPACITY];
static uint8_t host_can_rx_count;
static uint8_t host_can_tx_count;

static void copy_can_frame(hal_can_frame *destination,
                           const hal_can_frame *source)
{
    unsigned i;

    destination->arbitration_id = source->arbitration_id;
    destination->dlc = source->dlc;
    destination->flags = source->flags;
    for (i = 0u; i < HAL_CAN_CLASSIC_DLC_MAX; i++) {
        destination->data[i] = source->data[i];
    }
}

static bool host_deadline_reached(uint64_t now_us, uint64_t deadline_us)
{
    return (uint64_t)(now_us - deadline_us) < (UINT64_C(1) << 63);
}

void hal_putc(char c)
{
    (void)putchar((int)c);
}

void hal_puts(const char *s)
{
    if (s != 0) {
        (void)fputs(s, stdout);
    }
}

void hal_put_u32(uint32_t value)
{
    (void)printf("%u", (unsigned)value);
}

void hal_report_exit(int code)
{
    (void)code;
}

void hal_report_trap(uint32_t mcause, uint32_t mepc)
{
    (void)mcause;
    (void)mepc;
}

uint64_t hal_now_us(void)
{
    return host_now_us;
}

void hal_timer_arm_us(uint64_t deadline_us)
{
    host_timer_deadline_us = deadline_us;
}

void hal_timer_disarm(void)
{
    host_timer_deadline_us = UINT64_MAX;
}

void hal_timer_enable(void)
{
}

bool hal_can_init(void)
{
    host_can_initialized = true;
    host_can_rx_count = 0u;
    host_can_tx_count = 0u;
    return true;
}

bool hal_can_send(const hal_can_frame *frame)
{
    if (!host_can_initialized || frame == 0 ||
        host_can_tx_count >= HAL_HOST_CAN_QUEUE_CAPACITY) {
        return false;
    }

    copy_can_frame(&host_can_tx[host_can_tx_count], frame);
    host_can_tx_count++;
    return true;
}

bool hal_can_recv(hal_can_frame *frame)
{
    uint8_t selected = 0u;
    uint8_t index;

    if (!host_can_initialized || frame == 0 || host_can_rx_count == 0u) {
        return false;
    }

    /* The fake models a set of frames that completed arbitration before the
     * receiver polls. Lower standard IDs win; equal IDs retain insertion
     * order. This is deterministic logic evidence, not physical bus timing. */
    for (index = 1u; index < host_can_rx_count; index++) {
        if (host_can_rx[index].arbitration_id <
            host_can_rx[selected].arbitration_id) {
            selected = index;
        }
    }
    copy_can_frame(frame, &host_can_rx[selected]);
    for (index = selected; index + 1u < host_can_rx_count; index++) {
        copy_can_frame(&host_can_rx[index], &host_can_rx[index + 1u]);
    }
    host_can_rx_count--;
    return true;
}

void hal_host_can_reset(void)
{
    host_can_initialized = false;
    host_can_rx_count = 0u;
    host_can_tx_count = 0u;
}

bool hal_host_can_inject_rx(const hal_can_frame *frame)
{
    if (!host_can_initialized || frame == 0 ||
        host_can_rx_count >= HAL_HOST_CAN_QUEUE_CAPACITY) {
        return false;
    }

    copy_can_frame(&host_can_rx[host_can_rx_count], frame);
    host_can_rx_count++;
    return true;
}

bool hal_host_can_take_tx(hal_can_frame *frame)
{
    uint8_t index;

    if (!host_can_initialized || frame == 0 || host_can_tx_count == 0u) {
        return false;
    }

    copy_can_frame(frame, &host_can_tx[0]);
    for (index = 0u; index + 1u < host_can_tx_count; index++) {
        copy_can_frame(&host_can_tx[index], &host_can_tx[index + 1u]);
    }
    host_can_tx_count--;
    return true;
}

uint8_t hal_host_can_rx_count(void)
{
    return host_can_rx_count;
}

uint8_t hal_host_can_tx_count(void)
{
    return host_can_tx_count;
}

void hal_wdt_start(uint32_t timeout_ms)
{
    host_wdt_timeout_ms = timeout_ms;
    host_wdt_running = true;
    host_wdt_deadline_us = host_now_us + (uint64_t)timeout_ms * 1000u;
    host_wdt_feeds = 0u;
}

void hal_wdt_feed(void)
{
    if (!host_wdt_running) {
        return;
    }
    host_wdt_feeds++;
    host_wdt_deadline_us = host_now_us + (uint64_t)host_wdt_timeout_ms * 1000u;
}

uint32_t hal_wdt_feed_count(void)
{
    return host_wdt_feeds;
}

bool hal_wdt_is_expired(void)
{
    return host_wdt_running && host_deadline_reached(host_now_us, host_wdt_deadline_us);
}
