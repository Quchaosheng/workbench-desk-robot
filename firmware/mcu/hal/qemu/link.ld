/* QEMU riscv32 "virt" machine.
 *
 * With -bios none -kernel, QEMU loads the ELF and jumps to 0x80000000.
 * That is where RAM starts on this machine, so text and data share it.
 * The real board (FW17) has flash at 0x00000000 and RAM at 0x20000000, which
 * is why link.ld is per-HAL and not shared.
 */

MEMORY
{
  RAM (rwx) : ORIGIN = 0x80000000, LENGTH = 8M
}

/* Deliberately generous here; the CH32V307 script will be tight (64K).
 * Stack size is what FW9 has to bound statically.
 */
__stack_size = 4K;

ENTRY(_start)

SECTIONS
{
  .text : ALIGN(4)
  {
    KEEP(*(.text.entry))     /* crt0 must land first: QEMU jumps to ORIGIN */
    *(.text .text.*)
    *(.rodata .rodata.*)
  } > RAM

  .data : ALIGN(4)
  {
    __data_start = .;
    *(.data .data.*)

    /* crt0 loads gp from this. The linker defines __global_pointer$ itself
     * only when it supplies its own script; we supply ours, so it has to be
     * declared here or `la gp, __global_pointer$` in crt0.S will not link.
     *
     * It has to sit here, inside SECTIONS and after __data_start, because a
     * PROVIDE at file scope cannot reference a symbol defined later.
     *
     * 0x800 in: gp-relative loads use a signed 12-bit offset, so sitting in
     * the middle of the small-data area reaches most of it in one instruction.
     */
    PROVIDE(__global_pointer$ = . + 0x800);

    *(.sdata .sdata.*)
    __data_end = .;
  } > RAM

  .bss (NOLOAD) : ALIGN(4)
  {
    __bss_start = .;
    *(.bss .bss.*)
    *(.sbss .sbss.*)
    *(COMMON)
    __bss_end = .;
  } > RAM

  /* Stack at the top, growing down. __stack_top is what crt0 loads into sp. */
  .stack (NOLOAD) : ALIGN(16)
  {
    __stack_bottom = .;
    . += __stack_size;
    __stack_top = .;
  } > RAM

  /* Nothing should reach these on a freestanding build. Listing them keeps
   * them out of .text rather than silently padding it.
   */
  /DISCARD/ : { *(.comment) *(.note.*) *(.eh_frame) }
}

/* Detecting a stray soft-float dependency belongs in `make verify-no-fp`,
 * which greps objdump output. A linker ASSERT cannot see it: libgcc's
 * __adddf3 and friends are ordinary functions in .text, not a distinct
 * section, so SIZEOF() has nothing to test.
 */
