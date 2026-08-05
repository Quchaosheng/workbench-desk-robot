/* Moved to hal/qemu/main_qemu.c.
 *
 * It read __stack_bottom/__stack_top, which are QEMU link.ld symbols, and it
 * defined main(), which collides with the host test runner's main(). Both are
 * target-specific, so both belong in a hal/.
 *
 * core/ holds no entry point. That is what lets it compile unchanged for
 * qemu, ch32v307 and host.
 *
 * This file is intentionally empty rather than deleted, so that
 * `ls core/*.c` in the CI probe does not match on a stub with no logic. Once
 * FW3 lands state_machine.c, delete this file.
 */
