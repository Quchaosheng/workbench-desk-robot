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

.PHONY: all clean load unload reload test checkpatch help

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

# The kernel's own checker. Catches the style issues a maintainer would.
checkpatch:
	@if [ -x "$(KDIR)/scripts/checkpatch.pl" ]; then \
	  $(KDIR)/scripts/checkpatch.pl --no-tree --file --strict wbcan.c; \
	else \
	  echo "checkpatch.pl not found under $(KDIR)/scripts/"; exit 1; \
	fi

help:
	@echo "make           build wbcan.ko against $(KDIR)"
	@echo "make load      insmod and bring up $(IFACE)"
	@echo "make test      run the fault suite"
	@echo "make checkpatch  kernel style check"
	@echo ""
	@echo "Arm a fault by hand:"
	@echo "  echo 'drop-tx 3' | sudo tee /sys/kernel/debug/wbcan/$(IFACE)/inject"
	@echo "  cat /sys/kernel/debug/wbcan/$(IFACE)/status"
