# wbcan - virtual CAN device with programmable fault injection.
#
# Out-of-tree build against the running kernel's headers.
#   make            build wbcan.ko
#   make load       insmod, bring the interface up
#   make unload     take it down, rmmod
#   make test       run the fault suite (needs the module loaded)
#   make checkpatch run the kernel's own style checker, if available

KDIR  ?= /lib/modules/$(shell uname -r)/build
PWD   := $(shell pwd)
IFACE ?= wbcan0
STRESS_REPORT ?= /tmp/wbcan-stress-report.json
STRESS_PRODUCERS ?= 4
STRESS_FRAMES ?= 250

.PHONY: all clean load unload reload test stress checkpatch help

all:
	@if [ ! -d "$(KDIR)" ]; then \
	  echo "kernel headers not found at $(KDIR)"; \
	  echo "  Debian/Ubuntu: sudo apt-get install linux-headers-\$$(uname -r)"; \
	  echo "  Fedora:        sudo dnf install kernel-devel"; \
	  exit 1; \
	fi
	$(MAKE) -C $(KDIR) M=$(PWD) modules

clean:
	@if [ -d "$(KDIR)" ]; then $(MAKE) -C $(KDIR) M=$(PWD) clean; else rm -f *.o *.ko *.mod* .*.cmd modules.order Module.symvers; fi

# can-dev provides alloc_candev/register_candev. On most distros it is a
# module, not built in, so load it first or insmod fails on symbols.
load: all
	sudo modprobe can
	sudo modprobe can-raw
	sudo modprobe can-dev
	sudo insmod ./wbcan.ko
	@# restart-ms is what makes the CAN core auto-recover from bus-off,
	@# which is the behaviour FW19 has to survive.
	sudo ip link set $(IFACE) type can restart-ms 100
	sudo ip link set $(IFACE) up
	@ip -details link show $(IFACE)

unload:
	-sudo ip link set $(IFACE) down
	-sudo rmmod wbcan

reload: unload load

test:
	@sudo ./test_wbcan.sh $(IFACE)

stress:
	@if [ ! -d "/sys/kernel/debug/wbcan/$(IFACE)" ]; then \
		echo "wbcan debugfs is unavailable at /sys/kernel/debug/wbcan/$(IFACE)"; \
		echo "load the module and bring $(IFACE) up before running stress"; \
		exit 1; \
	fi
	@sudo python3 ./test_state_concurrency.py $(IFACE) /sys/kernel/debug/wbcan/$(IFACE) \
		--report $(STRESS_REPORT) --producers $(STRESS_PRODUCERS) --frames-per-producer $(STRESS_FRAMES)
	@python3 ./test_state_concurrency.py --validate-report $(STRESS_REPORT)
	@echo "wbcan stress evidence: $(STRESS_REPORT)"

# The kernel's own checker. Catches the style issues a maintainer would.
checkpatch:
	@if [ -x "$(KDIR)/scripts/checkpatch.pl" ]; then \
	  $(KDIR)/scripts/checkpatch.pl --no-tree --file --strict wbcan.c; \
	else \
	  echo "checkpatch.pl not found under $(KDIR)/scripts/"; exit 1; \
	fi

help:
	@echo "make           build wbcan.ko against $(KDIR)"
	@echo "make load      create and bring up the module-load singleton $(IFACE)"
	@echo "make test      run the fault suite"
	@echo "make stress    run the bounded concurrency and stats probe"
	@echo "make checkpatch  kernel style check"
	@echo "ip link add type wbcan is unsupported; unload before loading another"
	@echo ""
	@echo "Arm a fault by hand:"
	@echo "  echo 'drop-tx 3' | sudo tee /sys/kernel/debug/wbcan/$(IFACE)/inject"
	@echo "  cat /sys/kernel/debug/wbcan/$(IFACE)/status"
