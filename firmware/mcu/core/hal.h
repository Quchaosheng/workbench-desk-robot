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
 * Raw controller envelope, before Wire V1 decoding.  The arbitration ID is
 * the standard 11-bit CAN identifier; it is not the logical 16-bit command
 * ID stored in payload bytes 1..2.  Keeping those names distinct prevents a
 * STOP command_id (>= 0x8000) from being written into an 11-bit controller
 * register.
 *
 * flags is deliberately a byte rather than C bit-fields so every target maps
 * controller metadata explicitly.  Wire V1 accepts only flags == NONE,
 * DLC == 8 and arbitration_id <= 0x7ff.  The bridge rejects all other
 * envelopes before decoding or safety-state mutation.
 */
#define HAL_CAN_STANDARD_ID_MAX 0x07ffu
#define HAL_CAN_CLASSIC_DLC_MAX 8u

typedef enum {
    HAL_CAN_FRAME_FLAG_NONE = 0u,
    HAL_CAN_FRAME_FLAG_EXTENDED_ID = 1u << 0,
    HAL_CAN_FRAME_FLAG_REMOTE = 1u << 1,
    HAL_CAN_FRAME_FLAG_ERROR = 1u << 2,
    HAL_CAN_FRAME_FLAG_FD = 1u << 3
} hal_can_frame_flag_t;

typedef struct {
    uint16_t arbitration_id;
    uint8_t dlc;
    uint8_t flags;
    uint8_t data[HAL_CAN_CLASSIC_DLC_MAX];
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
