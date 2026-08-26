/* The HAL boundary. Task FW1.
 *
 * core/ calls these. It never touches a register directly. Every target
 * (qemu, ch32v307, host) implements this header and nothing wider.
 *
 * The rule from ADR-0003: an #ifdef CH32V307 in core/ means this boundary was
 * drawn wrong. If core/ needs something the board can do and QEMU cannot, the
 * fix is a new function here, implemented three times.
 */
#ifndef MCU_HAL_H
#define MCU_HAL_H

#include <stdint.h>
#include <stdbool.h>

/* ---------------------------------------------------------------- diagnostics
 * Byte sink. On QEMU this is the 16550 UART; on the board, USART1; on host,
 * stdout. core/ uses it for test output only — never in the safety path, since
 * a blocking write is unbounded time.
 */
void hal_putc(char c);
void hal_puts(const char *s);
void hal_put_u32(uint32_t v);

/* Called by crt0 when main returns, and from the trap handler. */
void hal_report_exit(int code);
void hal_report_trap(uint32_t mcause, uint32_t mepc);

/* ---------------------------------------------------------------------- time
 * Monotonic tick count. Backed by mtime on RISC-V, a plain counter on host.
 *
 * uint64_t on purpose: a 32-bit microsecond counter wraps in 71 minutes, and
 * a watchdog that misbehaves once every 71 minutes is worse than one that
 * never works. FW6 handles wraparound for CAN sequence numbers, where the
 * width is fixed by the wire format; here we are free to just not wrap.
 */
uint64_t hal_now_us(void);

/* Arm a one-shot timer interrupt at an absolute time. Used by FW5. */
void hal_timer_arm_us(uint64_t deadline_us);
void hal_timer_disarm(void);
/* Enable the target's global timer-interrupt delivery after setup. */
void hal_timer_enable(void);

/* ----------------------------------------------------------------------- CAN
 * Frame as it goes on the wire. Matches mcu_protocol.schema.json.
 *
 * QEMU gives us CTU CAN FD over PCI; the board gives us the CH32V307
 * peripheral. Neither detail appears above this line.
 */
typedef struct {
    uint16_t id;        /* <=32767 command, >=32768 stop. Enforced in FW4. */
    uint8_t  len;       /* 0..8 */
    uint8_t  data[8];
} hal_can_frame;

bool hal_can_init(void);
bool hal_can_send(const hal_can_frame *f);

/* Non-blocking. Returns false when nothing is pending. */
bool hal_can_recv(hal_can_frame *out);

/* ------------------------------------------------------------------ watchdog
 * Hardware watchdog, distinct from the software timeout in core/. On the board
 * this is IWDG (FW20) and cannot be stopped once started, which is the point.
 * On QEMU it is modelled well enough to test the feed path.
 */
void hal_wdt_start(uint32_t timeout_ms);
void hal_wdt_feed(void);
uint32_t hal_wdt_feed_count(void);
bool hal_wdt_is_expired(void);

#endif /* MCU_HAL_H */
