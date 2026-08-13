#!/usr/bin/env bash
# Fault suite for the wbcan module.
#
# Each case arms a fault, sends frames, and asserts what actually arrived.
# Asserting on observable effect rather than on a log line: a driver that
# prints "injected drop-tx" while still delivering the frame would pass a
# log-scraping test and fail this one.
#
# Run: sudo ./test_wbcan.sh [iface]

set -uo pipefail

IFACE="${1:-wbcan0}"
DBG="/sys/kernel/debug/wbcan/${IFACE}"
PASS=0
FAIL=0

red()   { printf '\033[31m%s\033[0m\n' "$*"; }
green() { printf '\033[32m%s\033[0m\n' "$*"; }

need() {
	command -v "$1" >/dev/null 2>&1 || {
		red "missing $1 (apt-get install can-utils)"; exit 1; }
}
need cansend
need candump

[ -d "$DBG" ] || { red "no debugfs dir at $DBG - is the module loaded?"; exit 1; }
ip link show "$IFACE" >/dev/null 2>&1 || { red "no interface $IFACE"; exit 1; }

arm()   { echo "$*" > "$DBG/inject"; }
clear_fault() { arm "none 0"; }
stat()  { awk -v k="$1" '$1==k{print $2}' "$DBG/status"; }

wait_for_state() {
	local want="$1" attempts="${2:-40}"
	local current
	while [ "$attempts" -gt 0 ]; do
		current=$(stat state)
		[ "$current" = "$want" ] && return 0
		sleep 0.05
		attempts=$((attempts - 1))
	done
	return 1
}

# Capture compact data and error frames for a fixed window. candump -T exits
# on its own, so no stray kill.
capture() {
	local ms="$1"
	candump -L -T "$ms" -n 100 "$IFACE,0:0,#FFFFFFFF" 2>/dev/null
}

check() {
	local name="$1" want="$2" got="$3"
	if [ "$want" = "$got" ]; then
		green "PASS  $name"
		PASS=$((PASS + 1))
	else
		red   "FAIL  $name: want '$want' got '$got'"
		FAIL=$((FAIL + 1))
	fi
}

restart_if_bus_off() {
	if [ "$(stat state)" = "bus-off" ]; then
		ip link set "$IFACE" down
		ip link set "$IFACE" up
		sleep 0.2
	fi
}

echo "=== wbcan fault suite on $IFACE ==="
echo

# --- 1. baseline: no fault, frame must arrive intact ------------------------
clear_fault
out=$(capture 300 & sleep 0.1; cansend "$IFACE" 123#DEADBEEF; wait)
check "baseline delivers frame" \
      "1" "$(grep -c 'DEADBEEF' <<<"$out")"

# --- 2. drop-tx: accepted, counted, never delivered ------------------------
# The nastiest failure mode for firmware: no error, no frame.
clear_fault
arm "drop-tx 1"
out=$(capture 300 & sleep 0.1; cansend "$IFACE" 200#01020304; wait)
check "drop-tx swallows the frame" \
      "0" "$(grep -c '01020304' <<<"$out")"
check "drop-tx consumed one shot" \
      "0" "$(stat shots_left)"

# --- 3. one-shot only affects one frame -----------------------------------
clear_fault
arm "drop-tx 1"
out=$(capture 400 & sleep 0.1
      cansend "$IFACE" 201#AA
      sleep 0.05
      cansend "$IFACE" 201#BB
      wait)
check "second frame survives a one-shot fault" \
      "1" "$(grep -c 'AA$\|BB' <<<"$out" | head -1)"

# --- 4. skip-first: arm on the Nth frame ----------------------------------
clear_fault
arm "drop-tx 1 2"        # skip 2, then drop 1
out=$(capture 500 & sleep 0.1
      cansend "$IFACE" 300#11
      sleep 0.05
      cansend "$IFACE" 300#22
      sleep 0.05
      cansend "$IFACE" 300#33
      wait)
check "skip-first lets the first two through" \
      "2" "$(grep -Ec '300.*(11|22)$' <<<"$out")"
check "skip-first drops the third" \
      "0" "$(grep -c '300.*33$' <<<"$out")"

# --- 5. bit-flip corrupts exactly one bit ---------------------------------
clear_fault
arm "bit-flip 1 0 ffff 0 0"    # byte 0, bit 0
out=$(capture 300 & sleep 0.1; cansend "$IFACE" 400#F0; wait)
# 0xF0 with bit 0 flipped is 0xF1.
check "bit-flip changes byte 0 bit 0" \
      "1" "$(grep -ci 'F1' <<<"$out")"

# --- 6. id filter: only the matching id takes the fault -------------------
clear_fault
arm "drop-tx 5 0 123"          # only id 0x123
out=$(capture 400 & sleep 0.1
      cansend "$IFACE" 123#AA
      sleep 0.05
      cansend "$IFACE" 456#BB
      wait)
check "id filter drops the match" \
      "0" "$(grep -c '123.*AA' <<<"$out")"
check "id filter spares non-matching" \
      "1" "$(grep -c '456.*BB' <<<"$out")"

# --- 7. bus-off produces an error frame and changes state -----------------
# This is the case a userspace shim cannot fake.
ip link set "$IFACE" down
ip link set "$IFACE" type can restart-ms 500
ip link set "$IFACE" up
clear_fault
arm "bus-off 1"
out=$(capture 250 & sleep 0.05; cansend "$IFACE" 500#01 2>/dev/null; wait)
check "bus-off emits an error frame" \
      "1" "$(grep -c '20000040\|ERRORFRAME' <<<"$out" | head -1)"
check "bus-off moves controller state" \
      "bus-off" "$(stat state)"

# --- 8. restart-ms automatically clears state and the armed fault ---------
if wait_for_state "error-active" 40; then
	restarted="error-active"
else
	restarted=$(stat state)
fi
check "restart-ms returns to error-active" \
      "error-active" "$restarted"
check "automatic restart clears the armed fault" \
      "none" "$(stat armed_fault)"
out=$(capture 300 & sleep 0.1; cansend "$IFACE" 501#02; wait)
check "automatic restart restores transmission" \
      "1" "$(grep -c '501.*02' <<<"$out")"

# --- 9. manual CAN-core restart remains supported --------------------------
ip link set "$IFACE" down
ip link set "$IFACE" type can restart-ms 0
ip link set "$IFACE" up
clear_fault
arm "bus-off 1"
cansend "$IFACE" 502#03 2>/dev/null
if wait_for_state "bus-off" 10; then
	manual_bus_off="bus-off"
else
	manual_bus_off=$(stat state)
fi
check "manual restart setup reaches bus-off" \
      "bus-off" "$manual_bus_off"
ip link set "$IFACE" type can restart
check "manual restart returns to error-active" \
      "error-active" "$(stat state)"
check "manual restart clears the armed fault" \
      "none" "$(stat armed_fault)"
out=$(capture 300 & sleep 0.1; cansend "$IFACE" 503#04; wait)
check "manual restart restores transmission" \
      "1" "$(grep -c '503.*04' <<<"$out")"

# --- 10. arb-lost is an error but not terminal -----------------------------
clear_fault
arm "arb-lost 1"
out=$(capture 300 & sleep 0.1; cansend "$IFACE" 600#01; wait)
check "arb-lost emits an error frame" \
      "1" "$(grep -ci 'ERRORFRAME\|20000002' <<<"$out" | head -1)"
check "arb-lost leaves the bus usable" \
      "error-active" "$(stat state)"

# --- 11. counters are trustworthy -----------------------------------------
clear_fault
before=$(stat tx_frames)
cansend "$IFACE" 700#01
sleep 0.1
after=$(stat tx_frames)
check "tx counter advances" \
      "1" "$(( after - before ))"

# --- 12. rejecting a bad ABI write ----------------------------------------
if echo "not-a-mode 1" > "$DBG/inject" 2>/dev/null; then
	check "bad fault name rejected" "rejected" "accepted"
else
	check "bad fault name rejected" "rejected" "rejected"
fi
if echo "bit-flip 1 0 ffff 0 9" > "$DBG/inject" 2>/dev/null; then
	check "out-of-range bit rejected" "rejected" "accepted"
else
	check "out-of-range bit rejected" "rejected" "rejected"
fi

clear_fault
restart_if_bus_off

echo
echo "=== $PASS passed, $FAIL failed ==="
[ "$FAIL" -eq 0 ]
