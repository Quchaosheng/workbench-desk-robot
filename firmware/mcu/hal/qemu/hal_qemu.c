/* QEMU virt machine HAL. Task FW1/FW2.
 *
 * Addresses come from QEMU's hw/riscv/virt.c memory map. They live here and
 * nowhere else — that is the whole reason this file exists.
 */
#include "hal.h"

/* NS16550A UART. */
#define UART0_BASE  0x10000000u
#define UART_THR    (*(volatile uint8_t *)(UART0_BASE + 0x00))
#define UART_LSR    (*(volatile uint8_t *)(UART0_BASE + 0x05))
#define UART_LSR_THRE 0x20u   /* transmit holding register empty */

/* CLINT: mtime is a memory-mapped 64-bit counter on this machine, ticking at
 * 10 MHz. On the CH32V307 it is the mtime CSR instead, which is why hal_now_us
 * is behind the HAL and not a macro in core/.
 */
#define CLINT_BASE      0x02000000u
#define CLINT_MTIMECMP  (*(volatile uint64_t *)(CLINT_BASE + 0x4000))
#define CLINT_MTIME     (*(volatile uint64_t *)(CLINT_BASE + 0xBFF8))
#define MTIME_HZ        10000000ull

void hal_putc(char c)
{
    while (!(UART_LSR & UART_LSR_THRE)) { }
    UART_THR = (uint8_t)c;
}

void hal_puts(const char *s)
{
    for (; *s; s++) {
        if (*s == '\n') hal_putc('\r');
        hal_putc(*s);
    }
}

void hal_put_u32(uint32_t v)
{
    /* Decimal, no printf: pulling in stdio would blow the size budget and
     * drag in an allocator, which FW9 forbids. */
    char buf[11];
    int i = 0;
    if (v == 0) { hal_putc('0'); return; }
    while (v > 0 && i < (int)sizeof(buf)) { buf[i++] = (char)('0' + (v % 10)); v /= 10; }
    while (i-- > 0) hal_putc(buf[i]);
}

void hal_report_exit(int code)
{
    hal_puts(code == 0 ? "\n[mcu] PASS\n" : "\n[mcu] FAIL code=");
    if (code != 0) { hal_put_u32((uint32_t)code); hal_putc('\n'); }

    /* Hand the exit code to the harness so `make test-qemu` fails the build.
     * QEMU's riscv virt exposes a SiFive test finisher at 0x100000:
     *   0x5555 = pass, 0x3333 | (code << 16) = fail.
     */
    volatile uint32_t *finisher = (volatile uint32_t *)0x100000u;
    *finisher = (code == 0) ? 0x5555u : (0x3333u | ((uint32_t)code << 16));
}

void hal_report_trap(uint32_t mcause, uint32_t mepc)
{
    /* A trap in a safety MCU is never routine. Say exactly what and where,
     * then let crt0 halt — no attempt to resume. */
    hal_puts("\n[mcu] TRAP mcause=");
    hal_put_u32(mcause);
    hal_puts(" mepc=");
    hal_put_u32(mepc);
    hal_putc('\n');

    volatile uint32_t *finisher = (volatile uint32_t *)0x100000u;
    *finisher = 0x3333u | (99u << 16);
}

/* Divide a 64-bit timer value without pulling __udivdi3 into the freestanding
 * rv32 image. Each half is processed with 32-bit shifts only.
 */
static uint64_t divide_u64_by_10(uint64_t value)
{
    uint32_t words[2] = {(uint32_t)(value >> 32), (uint32_t)value};
    uint32_t quotient[2] = {0, 0};
    uint32_t remainder = 0;

    for (unsigned word = 0; word < 2; word++) {
        for (int bit = 31; bit >= 0; bit--) {
            remainder = (remainder << 1) | ((words[word] >> bit) & 1u);
            if (remainder >= 10u) {
                remainder -= 10u;
                quotient[word] |= 1u << bit;
            }
        }
    }

    return ((uint64_t)quotient[0] << 32) | quotient[1];
}

/* mtime is 10 MHz on this machine, so microseconds = ticks / 10. */
uint64_t hal_now_us(void)
{
    return divide_u64_by_10(CLINT_MTIME);
}

void hal_timer_arm_us(uint64_t deadline_us)
{
    /* Same reasoning in reverse: multiply by 10, do not divide by 1000000. */
    CLINT_MTIMECMP = deadline_us * (MTIME_HZ / 1000000ull);
    /* Enable machine timer interrupt (MTIE, bit 7). */
    __asm__ volatile("csrs mie, %0" :: "r"(1u << 7));
}

void hal_timer_disarm(void)
{
    __asm__ volatile("csrc mie, %0" :: "r"(1u << 7));
    CLINT_MTIMECMP = (uint64_t)-1;
}

/* --- CAN: FW10 wires CTU CAN FD over PCI to the host vcan. Not yet. --------
 * Returning false rather than pretending to succeed: a stub that reports
 * success would let FW4's tests pass against nothing.
 */
bool hal_can_init(void) { return false; }
bool hal_can_send(const hal_can_frame *f) { (void)f; return false; }
bool hal_can_recv(hal_can_frame *out) { (void)out; return false; }

/* --- watchdog: FW5 uses the timer above; the hardware WDT model is FW20. --- */
void hal_wdt_start(uint32_t timeout_ms) { (void)timeout_ms; }
void hal_wdt_feed(void) { }
