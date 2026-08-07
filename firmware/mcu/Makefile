# Safety MCU firmware. See ../../docs/decisions/ADR-0003-mcu-riscv-qemu.md
#
# Three targets from one core/:
#   make host   -> x86_64 test binary, runs in milliseconds
#   make qemu    -> rv32imac ELF for QEMU
#   make board   -> rv32imac ELF to flash on CH32V307 (P3)

# Upstream GCC is fine for CH32V307; WCH private instructions are CH584/585 only.
# Override if you use the xpack toolchain: make CROSS=riscv-none-elf-
CROSS   ?= riscv64-unknown-elf-
RVCC    := $(CROSS)gcc
RVOBJDUMP := $(CROSS)objdump
RVSIZE  := $(CROSS)size

HOSTCC  ?= cc

BUILD   := build
CORE    := $(wildcard core/*.c)

# rv32imac: no FPU. -mabi=ilp32 (not ilp32f/d) so a stray double is a link error
# rather than silently pulling in soft-float.
RVARCH  := -march=rv32imac -mabi=ilp32
RVFLAGS := $(RVARCH) -Os -g -ffreestanding -nostdlib -nostartfiles \
           -ffunction-sections -fdata-sections -Wl,--gc-sections \
           -Wall -Wextra -Werror -Icore
HOSTFLAGS := -O1 -g -Wall -Wextra -Werror -Icore -Ihal/host -DMCU_HOST_BUILD

# Size budget, enforced by FW16. Generous on purpose: 256KB flash / 64KB RAM.
# Blowing it means the design drifted, not that the part is too small.
MAX_TEXT := 32768
MAX_BSS  := 8192

.PHONY: all host qemu board test-host test-qemu size-check verify-no-fp clean

all: host qemu

# ---------------------------------------------------------------- host target
# Needs a main(), which lives in tests/. Until FW3 writes the state machine and
# its tests there is nothing to link, so say so instead of failing with an
# undefined-reference wall.
host:
	@if [ -z "$(wildcard tests/*.c)" ]; then \
	  echo "tests/ is empty - host tests arrive with FW3. Nothing to build."; \
	else \
	  mkdir -p $(BUILD)/host; \
	  $(HOSTCC) $(HOSTFLAGS) $(CORE) $(wildcard hal/host/*.c) \
	    $(wildcard tests/*.c) -o $(BUILD)/host/test-runner; \
	fi

test-host: host
	@if [ -x $(BUILD)/host/test-runner ]; then $(BUILD)/host/test-runner; \
	 else echo "no host test binary yet (FW3)"; fi

# ---------------------------------------------------------------- qemu target
qemu: $(BUILD)/qemu/mcu.elf

# main() for this target is hal/qemu/main_qemu.c, picked up by the glob.
# core/ deliberately has no entry point.
$(BUILD)/qemu/mcu.elf: $(CORE) $(wildcard hal/qemu/*.c) hal/qemu/crt0.S hal/qemu/link.ld
	@command -v $(RVCC) >/dev/null 2>&1 || { \
	  echo "$(RVCC) not found."; \
	  echo "  apt:   sudo apt-get install gcc-riscv64-unknown-elf"; \
	  echo "  xpack: make CROSS=riscv-none-elf-"; \
	  exit 1; }
	@mkdir -p $(BUILD)/qemu
	$(RVCC) $(RVFLAGS) -Ihal/qemu -T hal/qemu/link.ld \
	  hal/qemu/crt0.S $(CORE) $(wildcard hal/qemu/*.c) -o $@
	@$(RVSIZE) $@

# QEMU virt machine, no BIOS: it jumps straight to our entry at 0x80000000.
# Exit code comes back through the test runner's semihosting-free convention:
# main() returns, crt0 writes the code to the UART and halts.
test-qemu: qemu
	@qemu-system-riscv32 -machine virt -nographic -bios none \
	  -kernel $(BUILD)/qemu/mcu.elf \
	  -no-reboot -semihosting-config enable=on,target=native

# --------------------------------------------------------------- board target
board: $(BUILD)/board/mcu.elf

$(BUILD)/board/mcu.elf: $(CORE) $(wildcard hal/ch32v307/*.c)
	@if [ -z "$(wildcard hal/ch32v307/*.c)" ]; then \
	  echo "hal/ch32v307/ is empty — that is task FW17 (P3)."; exit 1; fi
	@mkdir -p $(BUILD)/board
	$(RVCC) $(RVFLAGS) -Ihal/ch32v307 -T hal/ch32v307/link.ld \
	  hal/ch32v307/crt0.S $(CORE) $(wildcard hal/ch32v307/*.c) -o $@

# ------------------------------------------------------- static guarantees FW9
# Three things a safety binary must not contain. Checked, not assumed.
verify-no-fp: qemu
	@echo "checking for floating-point instructions..."
	@if $(RVOBJDUMP) -d $(BUILD)/qemu/mcu.elf | grep -qE '\sf(add|sub|mul|div|cvt|ld|sd|mv)'; then \
	  echo "FAIL: floating-point instruction emitted. rv32imac has no FPU."; \
	  $(RVOBJDUMP) -d $(BUILD)/qemu/mcu.elf | grep -E '\sf(add|sub|mul|div|cvt|ld|sd|mv)' | head; \
	  exit 1; fi
	@echo "checking for dynamic allocation..."
	@if $(RVOBJDUMP) -t $(BUILD)/qemu/mcu.elf | grep -qE '\b(malloc|calloc|realloc|free)\b'; then \
	  echo "FAIL: allocator symbol linked in. The safety path must not have an"; \
	  echo "      allocation-failure branch."; exit 1; fi
	@echo "ok: no FP, no allocator"

size-check: qemu
	@text=$$($(RVSIZE) -A $(BUILD)/qemu/mcu.elf | awk '/^\.text/{print $$2}'); \
	 bss=$$($(RVSIZE) -A $(BUILD)/qemu/mcu.elf | awk '/^\.bss/{print $$2}'); \
	 echo ".text=$$text (max $(MAX_TEXT))  .bss=$$bss (max $(MAX_BSS))"; \
	 [ "$${text:-0}" -le $(MAX_TEXT) ] || { echo "FAIL: .text over budget"; exit 1; }; \
	 [ "$${bss:-0}" -le $(MAX_BSS) ] || { echo "FAIL: .bss over budget"; exit 1; }

clean:
	rm -rf $(BUILD)
