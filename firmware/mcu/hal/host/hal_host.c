#include "hal.h"

#include <stdio.h>

static uint64_t host_now_us;
static uint64_t host_timer_deadline_us;
static uint32_t host_wdt_timeout_ms;
static uint64_t host_wdt_deadline_us;
static uint32_t host_wdt_feeds;
static bool host_wdt_running;

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
    return false;
}

bool hal_can_send(const hal_can_frame *frame)
{
    (void)frame;
    return false;
}

bool hal_can_recv(hal_can_frame *frame)
{
    (void)frame;
    return false;
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
