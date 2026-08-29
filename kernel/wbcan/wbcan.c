// SPDX-License-Identifier: GPL-2.0
/*
 * wbcan - a virtual CAN device with programmable fault injection.
 *
 * vcan is a perfect wire: every frame you write comes back out. Real CAN is
 * not. Controllers go bus-off, TX mailboxes fill up, arbitration is lost, bit
 * errors corrupt payloads. Firmware that has only ever seen vcan has never
 * executed its own error paths.
 *
 * This driver is vcan plus a fault plane. You arm a fault over debugfs, the
 * next N frames hit it, and the error surfaces the way the CAN core expects:
 * error frames on the socket, state transitions through CAN_STATE_*, and the
 * TX/RX error counters moving. So the firmware under test sees a bus going
 * bad rather than a special test API.
 *
 * Used by firmware/mcu task FW13 (register-level fault injection) and by the
 * 40-fault suite in FW15. See docs/decisions/ADR-0003-mcu-riscv-qemu.md.
 *
 * Why a kernel module and not userspace: bus-off state, error counters and
 * error-frame generation live in the kernel CAN core. A userspace bridge can
 * drop or mangle frames, but it cannot make can_get_state() report
 * CAN_STATE_BUS_OFF, and that transition is exactly what the firmware's
 * recovery path keys on.
 */

#define pr_fmt(fmt) KBUILD_MODNAME ": " fmt

#include <linux/ethtool.h>
#include <linux/module.h>
#include <linux/init.h>
#include <linux/netdevice.h>
#include <linux/if_arp.h>
#include <linux/debugfs.h>
#include <linux/delay.h>
#include <linux/err.h>
#include <linux/slab.h>
#include <linux/spinlock.h>
#include <linux/string.h>
#include <linux/u64_stats_sync.h>
#include <linux/can.h>
#include <linux/can/dev.h>
#include <linux/can/error.h>
#include <linux/can/skb.h>

#define WBCAN_ECHO_SKB_MAX	4

/* Fault modes. Values are the debugfs ABI; do not renumber. */
enum wbcan_fault {
	WBCAN_FAULT_NONE	= 0,
	WBCAN_FAULT_DROP_TX	= 1,	/* frame vanishes after being accepted */
	WBCAN_FAULT_DROP_RX	= 2,	/* frame never reaches the peer socket */
	WBCAN_FAULT_BIT_FLIP	= 3,	/* corrupt one payload bit */
	WBCAN_FAULT_BUS_OFF	= 4,	/* controller leaves the bus */
	WBCAN_FAULT_TX_FULL	= 5,	/* mailboxes full: -ENOBUFS to the stack */
	WBCAN_FAULT_ARB_LOST	= 6,	/* lost arbitration, TX aborted */
	WBCAN_FAULT_STUFF_ERR	= 7,	/* protocol violation on the wire */
	WBCAN_FAULT_MAX
};

static const char *const wbcan_fault_names[] = {
	[WBCAN_FAULT_NONE]	= "none",
	[WBCAN_FAULT_DROP_TX]	= "drop-tx",
	[WBCAN_FAULT_DROP_RX]	= "drop-rx",
	[WBCAN_FAULT_BIT_FLIP]	= "bit-flip",
	[WBCAN_FAULT_BUS_OFF]	= "bus-off",
	[WBCAN_FAULT_TX_FULL]	= "tx-full",
	[WBCAN_FAULT_ARB_LOST]	= "arb-lost",
	[WBCAN_FAULT_STUFF_ERR]	= "stuff-err",
};

static bool fail_error_skb;
module_param(fail_error_skb, bool, 0600);
MODULE_PARM_DESC(fail_error_skb, "fail CAN error SKB allocation for testing");

static unsigned int test_restart_delay_ms;
module_param(test_restart_delay_ms, uint, 0600);
MODULE_PARM_DESC(test_restart_delay_ms,
		 "test-only delay before serializing CAN restart");

static unsigned int test_stop_delay_ms;
module_param(test_stop_delay_ms, uint, 0600);
MODULE_PARM_DESC(test_stop_delay_ms,
		 "test-only delay around TX drain and stop publication");

struct wbcan_priv {
	struct can_priv		can;	/* must be first: can_priv contract */
	struct net_device	*dev;
	struct dentry		*dbg_dir;

	spinlock_t		lock;	/* guards fault configuration and stats */
	struct u64_stats_sync	stats_sync;	/* protects netdev stat snapshots */

	enum wbcan_fault	fault;
	u32			fault_count;	/* frames left to affect; 0 = off */
	u32			fault_after;	/* skip this many first */
	canid_t			match_id;	/* includes CAN_EFF_FLAG */
	bool			match_any;
	u8			flip_byte;
	u8			flip_bit;

	/*
	 * Observability. A fault you cannot count is a fault you cannot
	 * assert on from a test.
	 */
	u64			stat_tx;
	u64			stat_rx;
	u64			stat_injected;
	u64			stat_seen;
	u64			stat_restart_attempts;
	u64			stat_stop_attempts;
};

static void wbcan_stats_add(struct wbcan_priv *priv, u64 tx_packets,
			    u64 tx_bytes, u64 tx_errors, u64 tx_dropped,
			    u64 rx_packets, u64 rx_bytes, u64 rx_dropped)
{
	struct net_device_stats *stats = &priv->dev->stats;
	unsigned long flags;

	spin_lock_irqsave(&priv->lock, flags);
	u64_stats_update_begin(&priv->stats_sync);
	stats->tx_packets += tx_packets;
	stats->tx_bytes += tx_bytes;
	stats->tx_errors += tx_errors;
	stats->tx_dropped += tx_dropped;
	stats->rx_packets += rx_packets;
	stats->rx_bytes += rx_bytes;
	stats->rx_dropped += rx_dropped;
	u64_stats_update_end(&priv->stats_sync);
	spin_unlock_irqrestore(&priv->lock, flags);
}

static void wbcan_get_stats64(struct net_device *dev,
			      struct rtnl_link_stats64 *stats)
{
	struct wbcan_priv *priv = netdev_priv(dev);
	unsigned int start;

	do {
		start = u64_stats_fetch_begin(&priv->stats_sync);
		stats->tx_packets = dev->stats.tx_packets;
		stats->tx_bytes = dev->stats.tx_bytes;
		stats->tx_errors = dev->stats.tx_errors;
		stats->tx_dropped = dev->stats.tx_dropped;
		stats->rx_packets = dev->stats.rx_packets;
		stats->rx_bytes = dev->stats.rx_bytes;
		stats->rx_dropped = dev->stats.rx_dropped;
	} while (u64_stats_fetch_retry(&priv->stats_sync, start));
}

struct wbcan_status_snapshot {
	enum can_state		state;
	bool			queue_stopped;
	enum wbcan_fault	fault;
	u32			fault_count;
	u32			fault_after;
	canid_t			match_id;
	bool			match_any;
	u64			stat_tx;
	u64			stat_rx;
	u64			stat_injected;
	u64			stat_seen;
	u64			stat_restart_attempts;
	u64			stat_stop_attempts;
	u32			bus_errors;
};

/*
 * Controller-state ownership follows the netdev/CAN-core lifecycle rather
 * than the private fault lock:
 *
 * - ndo_start_xmit() and its injected error transitions are serialized by
 *   the single netdev TX queue;
 * - bus-off stops that queue before publishing the terminal state;
 * - do_set_mode() runs only while CAN core recovery keeps the queue stopped;
 * - ndo_open()/ndo_stop() run under RTNL, and ndo_stop() disables TX before
 *   closing the CAN device.
 *
 * Debugfs snapshots the fault plane under the private lock and reads the
 * independently published CAN state/queue bits without taking the netdev TX
 * lock. Formatting remains outside the private lock, so status observation
 * cannot extend the TX critical path. The state and queue values may describe
 * adjacent instants; they are diagnostic telemetry, not control authority.
 */

/* ------------------------------------------------------------------ helpers */

/* Decide whether this frame takes the fault, and consume one shot if so.
 * Called with the lock held.
 */
static canid_t wbcan_match_key(canid_t id)
{
	if (id & CAN_EFF_FLAG)
		return CAN_EFF_FLAG | (id & CAN_EFF_MASK);
	return id & CAN_SFF_MASK;
}

static bool wbcan_should_inject(struct wbcan_priv *priv, struct sk_buff *skb,
				enum wbcan_fault *fault, u8 *flip_byte,
				u8 *flip_bit)
{
	struct can_frame *cf = (struct can_frame *)skb->data;

	if (priv->fault == WBCAN_FAULT_NONE || priv->fault_count == 0)
		return false;

	if (!priv->match_any && wbcan_match_key(cf->can_id) != priv->match_id)
		return false;
	if (priv->fault == WBCAN_FAULT_BIT_FLIP &&
	    ((cf->can_id & CAN_RTR_FLAG) ||
	     priv->flip_byte >= can_skb_get_data_len(skb)))
		return false;

	priv->stat_seen++;

	if (priv->fault_after > 0) {
		priv->fault_after--;
		return false;
	}

	priv->fault_count--;
	priv->stat_injected++;
	*fault = priv->fault;
	*flip_byte = priv->flip_byte;
	*flip_bit = priv->flip_bit;
	return true;
}

/* Push a CAN error frame up to userspace and move the controller state.
 *
 * This is the part a userspace shim cannot do. can_change_state() updates
 * can_priv state and berr counters, and the error frame is what candump
 * renders as "ERRORFRAME" and what a firmware's error handler reads.
 */
static void wbcan_emit_error(struct net_device *dev, enum wbcan_fault fault)
{
	struct wbcan_priv *priv = netdev_priv(dev);
	struct can_frame *cf = NULL;
	struct sk_buff *skb;
	enum can_state tx_state = READ_ONCE(priv->can.state);
	enum can_state rx_state = tx_state;
	unsigned long flags;

	skb = READ_ONCE(fail_error_skb) ? NULL : alloc_can_err_skb(dev, &cf);

	switch (fault) {
	case WBCAN_FAULT_BUS_OFF:
		/*
		 * Bus-off is terminal until the driver is restarted. The CAN
		 * core handles the restart timer if restart-ms is set, which
		 * is what FW19 exercises. State recovery must not depend on
		 * allocating the optional error frame.
		 */
		netif_stop_queue(dev);
		tx_state = CAN_STATE_BUS_OFF;
		rx_state = CAN_STATE_BUS_OFF;
		if (READ_ONCE(priv->can.state) != CAN_STATE_BUS_OFF)
			can_change_state(dev, cf, tx_state, rx_state);
		else if (cf)
			cf->can_id |= CAN_ERR_BUSOFF;
		can_bus_off(dev);
		break;

	case WBCAN_FAULT_ARB_LOST:
		spin_lock_irqsave(&priv->lock, flags);
		priv->can.can_stats.arbitration_lost++;
		spin_unlock_irqrestore(&priv->lock, flags);
		if (!cf)
			break;
		cf->can_id |= CAN_ERR_LOSTARB;
		/*
		 * Bit position that lost. 0 means unspecified, which is
		 * honest here: we are not modelling a real bit timeline.
		 */
		cf->data[0] = 0;
		break;

	case WBCAN_FAULT_STUFF_ERR:
		/*
		 * This is a bounded protocol-error model: one warning per
		 * injected frame, then the next fault-free frame recovers to
		 * active. We do not pretend to model TEC/REC progression.
		 */
		spin_lock_irqsave(&priv->lock, flags);
		priv->can.can_stats.bus_error++;
		spin_unlock_irqrestore(&priv->lock, flags);
		tx_state = CAN_STATE_ERROR_WARNING;
		/* can_change_state() warns when the calculated state is unchanged. */
		if (max(tx_state, rx_state) != READ_ONCE(priv->can.state))
			can_change_state(dev, cf, tx_state, rx_state);
		if (!cf)
			break;
		cf->can_id |= CAN_ERR_PROT;
		cf->data[2] = CAN_ERR_PROT_STUFF;
		break;

	default:
		if (!cf)
			return;
		cf->can_id |= CAN_ERR_CRTL;
		cf->data[1] = CAN_ERR_CRTL_UNSPEC;
		break;
	}

	if (skb && netif_rx(skb) != NET_RX_SUCCESS)
		wbcan_stats_add(priv, 0, 0, 0, 0, 0, 0, 1);
}

/* --------------------------------------------------------------- netdev ops */

static int wbcan_open(struct net_device *dev)
{
	struct wbcan_priv *priv = netdev_priv(dev);
	int err;

	err = open_candev(dev);
	if (err)
		return err;
	netif_tx_lock_bh(dev);
	WRITE_ONCE(priv->can.state, CAN_STATE_ERROR_ACTIVE);
	netif_tx_unlock_bh(dev);
	netif_start_queue(dev);
	return 0;
}

static int wbcan_stop(struct net_device *dev)
{
	struct wbcan_priv *priv = netdev_priv(dev);
	unsigned int delay_ms;
	unsigned long flags;

	/* Stop new submissions and wait for an in-flight start_xmit(). */
	netif_tx_disable(dev);
	spin_lock_irqsave(&priv->lock, flags);
	priv->stat_stop_attempts++;
	spin_unlock_irqrestore(&priv->lock, flags);
	delay_ms = min(READ_ONCE(test_stop_delay_ms), 1000U);
	if (delay_ms)
		msleep(delay_ms);
	netif_tx_lock_bh(dev);
	netif_stop_queue(dev);
	WRITE_ONCE(priv->can.state, CAN_STATE_STOPPED);
	netif_tx_unlock_bh(dev);
	if (delay_ms)
		msleep(delay_ms);
	/* A restart worker that was queued before STOPPED must be cancelled. */
	close_candev(dev);
	/* A worker may have committed ACTIVE before STOPPED was published. */
	netif_tx_disable(dev);
	return 0;
}

static netdev_tx_t wbcan_start_xmit(struct sk_buff *skb, struct net_device *dev)
{
	struct wbcan_priv *priv = netdev_priv(dev);
	struct can_frame *cf = (struct can_frame *)skb->data;
	struct sk_buff *rx_skb;
	enum wbcan_fault fault = WBCAN_FAULT_NONE;
	u8 flip_byte = 0;
	u8 flip_bit = 0;
	bool loop;
	unsigned int len;
	unsigned long flags;
	enum can_state state;

	if (can_dev_dropped_skb(dev, skb))
		return NETDEV_TX_OK;

	/* Loopback of our own error frames would be circular. */
	if (cf->can_id & CAN_ERR_FLAG) {
		kfree_skb(skb);
		return NETDEV_TX_OK;
	}

	state = READ_ONCE(priv->can.state);
	if (state == CAN_STATE_BUS_OFF || state == CAN_STATE_STOPPED ||
	    state == CAN_STATE_SLEEPING) {
		/*
		 * Queue lifecycle should keep these states out of start_xmit().
		 * If a future caller violates that boundary, consume the frame
		 * rather than accepting traffic in a terminal controller state.
		 */
		netif_stop_queue(dev);
		wbcan_stats_add(priv, 0, 0, 0, 1, 0, 0, 0);
		kfree_skb(skb);
		return NETDEV_TX_OK;
	}

	spin_lock_irqsave(&priv->lock, flags);
	wbcan_should_inject(priv, skb, &fault, &flip_byte, &flip_bit);
	spin_unlock_irqrestore(&priv->lock, flags);
	len = can_skb_get_data_len(skb);

	switch (fault) {
	case WBCAN_FAULT_TX_FULL:
		/*
		 * Mailboxes full. Stopping the queue and returning BUSY is
		 * how a real driver applies backpressure; the stack will
		 * retry when we wake it.
		 */
		netif_stop_queue(dev);
		wbcan_emit_error(dev, fault);
		/*
		 * Wake immediately: we are modelling a transient full
		 * condition, not a wedge. Without this the test hangs.
		 */
		netif_wake_queue(dev);
		return NETDEV_TX_BUSY;

	default:
		break;
	}

	/* The frame is now accepted and will not be retried by the stack. */
	skb_tx_timestamp(skb);

	switch (fault) {
	case WBCAN_FAULT_BUS_OFF:
	case WBCAN_FAULT_ARB_LOST:
	case WBCAN_FAULT_STUFF_ERR:
		spin_lock_irqsave(&priv->lock, flags);
		priv->stat_tx++;
		spin_unlock_irqrestore(&priv->lock, flags);
		wbcan_emit_error(dev, fault);
		wbcan_stats_add(priv, 0, 0, 1, 0, 0, 0, 0);
		kfree_skb(skb);
		return NETDEV_TX_OK;

	case WBCAN_FAULT_DROP_TX:
		/*
		 * Accepted, counted, never delivered. This is the nastiest
		 * failure for firmware: no error, no frame.
		 */
		spin_lock_irqsave(&priv->lock, flags);
		priv->stat_tx++;
		spin_unlock_irqrestore(&priv->lock, flags);
		wbcan_stats_add(priv, 1, len, 0, 0, 0, 0, 0);
		kfree_skb(skb);
		return NETDEV_TX_OK;

	default:
		break;
	}

	/* Count frames accepted by the driver; a BUSY retry is not a frame. */
	spin_lock_irqsave(&priv->lock, flags);
	priv->stat_tx++;
	spin_unlock_irqrestore(&priv->lock, flags);
	if (fault == WBCAN_FAULT_NONE &&
	    READ_ONCE(priv->can.state) == CAN_STATE_ERROR_WARNING)
		can_change_state(dev, NULL, CAN_STATE_ERROR_ACTIVE,
				 CAN_STATE_ERROR_ACTIVE);

	wbcan_stats_add(priv, 1, len, 0, 0, 0, 0, 0);
	loop = skb->pkt_type == PACKET_LOOPBACK;
	if (!loop) {
		consume_skb(skb);
		return NETDEV_TX_OK;
	}

	/*
	 * Preserve the originating socket so CAN_RAW_RECV_OWN_MSGS and receive
	 * confirmation flags retain their standard SocketCAN meaning. Bit-flip
	 * needs a private data copy because packet taps may hold shared clones.
	 */
	if (fault == WBCAN_FAULT_BIT_FLIP) {
		rx_skb = skb_copy(skb, GFP_ATOMIC);
		if (rx_skb)
			can_skb_set_owner(rx_skb, skb->sk);
		consume_skb(skb);
	} else {
		rx_skb = can_create_echo_skb(skb);
	}
	if (!rx_skb) {
		wbcan_stats_add(priv, 0, 0, 0, 0, 0, 0, 1);
		return NETDEV_TX_OK;
	}

	if (fault == WBCAN_FAULT_BIT_FLIP) {
		struct can_frame *rcf = (struct can_frame *)rx_skb->data;

		if (flip_byte < rcf->len) {
			rcf->data[flip_byte] ^= (1u << flip_bit);
			netdev_dbg(dev, "flipped byte %u bit %u of id 0x%x\n",
				   flip_byte, flip_bit, rcf->can_id);
		}
	}

	if (fault == WBCAN_FAULT_DROP_RX) {
		kfree_skb(rx_skb);
		wbcan_stats_add(priv, 0, 0, 0, 0, 0, 0, 1);
	} else {
		rx_skb->dev = dev;
		rx_skb->ip_summed = CHECKSUM_UNNECESSARY;
		rx_skb->pkt_type = PACKET_BROADCAST;
		if (netif_rx(rx_skb) == NET_RX_SUCCESS) {
			wbcan_stats_add(priv, 0, 0, 0, 0, 1, len, 0);

			spin_lock_irqsave(&priv->lock, flags);
			priv->stat_rx++;
			spin_unlock_irqrestore(&priv->lock, flags);
		} else {
			wbcan_stats_add(priv, 0, 0, 0, 0, 0, 0, 1);
		}
	}

	return NETDEV_TX_OK;
}

/* Called by the CAN core's restart timer, and by `ip link set can0 type can
 * restart`. FW19's bus-off recovery test drives this path.
 */
static int wbcan_set_mode(struct net_device *dev, enum can_mode mode)
{
	struct wbcan_priv *priv = netdev_priv(dev);
	unsigned int delay_ms;
	unsigned long flags;

	switch (mode) {
	case CAN_MODE_START:
		spin_lock_irqsave(&priv->lock, flags);
		priv->stat_restart_attempts++;
		spin_unlock_irqrestore(&priv->lock, flags);

		delay_ms = min(READ_ONCE(test_restart_delay_ms), 1000U);
		if (delay_ms)
			msleep(delay_ms);

		/* CAN core recovery owns this callback and keeps TX stopped. */
		netif_tx_lock_bh(dev);
		if (READ_ONCE(priv->can.state) != CAN_STATE_BUS_OFF) {
			netif_tx_unlock_bh(dev);
			return -EBUSY;
		}

		spin_lock_irqsave(&priv->lock, flags);
		/*
		 * Clear the armed fault on restart. Leaving it armed would
		 * make recovery tests flap for reasons the test did not ask
		 * for.
		 */
		priv->fault = WBCAN_FAULT_NONE;
		priv->fault_count = 0;
		spin_unlock_irqrestore(&priv->lock, flags);

		WRITE_ONCE(priv->can.state, CAN_STATE_ERROR_ACTIVE);
		netif_wake_queue(dev);
		netif_tx_unlock_bh(dev);
		netdev_info(dev, "restarted, fault plane cleared\n");
		return 0;
	default:
		return -EOPNOTSUPP;
	}
}

static int wbcan_change_mtu(struct net_device *dev, int new_mtu)
{
	if (dev->flags & IFF_UP)
		return -EBUSY;
	if (new_mtu != CAN_MTU)
		return -EINVAL;

	WRITE_ONCE(dev->mtu, new_mtu);
	return 0;
}

static const struct net_device_ops wbcan_netdev_ops = {
	.ndo_open	= wbcan_open,
	.ndo_stop	= wbcan_stop,
	.ndo_start_xmit	= wbcan_start_xmit,
	.ndo_change_mtu	= wbcan_change_mtu,
	.ndo_get_stats64	= wbcan_get_stats64,
};

static const struct ethtool_ops wbcan_ethtool_ops = {
	.get_ts_info	= ethtool_op_get_ts_info,
};

/* --------------------------------------------------------------- debugfs ABI
 *
 * echo "<mode> <count> [after] [id] [byte] [bit]" > /sys/kernel/debug/wbcan/<dev>/inject
 *
 *   arm 3 frames of drop-tx:            echo "drop-tx 3" > inject
 *   flip bit 2 of byte 0, 4th frame on: echo "bit-flip 1 3 any 0 2" > inject
 *   bus-off only for standard id 0x123: echo "bus-off 1 0 s:123" > inject
 *   drop extended id 0x123:             echo "drop-tx 1 0 e:123" > inject
 *
 * Text, not ioctl: a shell script in CI has to drive this, and a text ABI is
 * one line of bash instead of a helper binary.
 */

static int wbcan_parse_match_id(const char *value, bool *match_any,
				canid_t *match_id)
{
	const char *number = value;
	bool extended = false;
	u32 id;

	if (sysfs_streq(value, "any") || sysfs_streq(value, "ffff")) {
		*match_any = true;
		*match_id = 0;
		return 0;
	}

	if (!strncmp(value, "s:", 2)) {
		number += 2;
	} else if (!strncmp(value, "e:", 2)) {
		number += 2;
		extended = true;
	}
	if (kstrtou32(number, 16, &id))
		return -EINVAL;
	if (!strncmp(value, "s:", 2) && id > CAN_SFF_MASK)
		return -ERANGE;
	if (!strncmp(value, "e:", 2) && id > CAN_EFF_MASK)
		return -ERANGE;
	if (value == number && id > CAN_SFF_MASK) {
		if (id > CAN_EFF_MASK)
			return -ERANGE;
		extended = true;
	}

	*match_any = false;
	*match_id = id | (extended ? CAN_EFF_FLAG : 0);
	return 0;
}

static ssize_t wbcan_inject_write(struct file *file, const char __user *ubuf,
				  size_t len, loff_t *ppos)
{
	struct wbcan_priv *priv = file->private_data;
	char buf[96], **argv;
	canid_t match_id = 0;
	bool match_any = true;
	u32 count = 0, after = 0, byte = 0, bit = 0;
	unsigned long flags;
	int argc, i, err = 0, fault = -1;

	if (len == 0 || len >= sizeof(buf))
		return -EINVAL;
	if (copy_from_user(buf, ubuf, len))
		return -EFAULT;
	buf[len] = '\0';

	argv = argv_split(GFP_KERNEL, buf, &argc);
	if (!argv)
		return -ENOMEM;
	if (argc < 1) {
		err = -EINVAL;
		goto out;
	}

	for (i = 0; i < WBCAN_FAULT_MAX; i++) {
		if (wbcan_fault_names[i] && sysfs_streq(argv[0], wbcan_fault_names[i])) {
			fault = i;
			break;
		}
	}
	if (fault < 0) {
		pr_warn("unknown fault mode '%s'\n", argv[0]);
		err = -EINVAL;
		goto out;
	}

	if (fault == WBCAN_FAULT_NONE) {
		if (argc > 2 || (argc == 2 && (kstrtou32(argv[1], 10, &count) || count))) {
			err = -EINVAL;
			goto out;
		}
		goto apply;
	}
	if ((fault == WBCAN_FAULT_BIT_FLIP && argc != 6) ||
	    (fault != WBCAN_FAULT_BIT_FLIP && (argc < 2 || argc > 4)) ||
	    kstrtou32(argv[1], 10, &count) || count == 0) {
		err = -EINVAL;
		goto out;
	}
	if (argc >= 3 && kstrtou32(argv[2], 10, &after)) {
		err = -EINVAL;
		goto out;
	}
	if (argc >= 4 && wbcan_parse_match_id(argv[3], &match_any, &match_id)) {
		err = -EINVAL;
		goto out;
	}
	if (fault == WBCAN_FAULT_BIT_FLIP &&
	    (kstrtou32(argv[4], 10, &byte) || byte > 7 ||
	     kstrtou32(argv[5], 10, &bit) || bit > 7)) {
		err = -EINVAL;
		goto out;
	}

apply:
	spin_lock_irqsave(&priv->lock, flags);
	priv->fault       = fault;
	priv->fault_count = count;
	priv->fault_after = after;
	priv->match_id    = match_id;
	priv->match_any   = match_any;
	priv->flip_byte   = (u8)byte;
	priv->flip_bit    = (u8)bit;
	priv->stat_seen   = 0;
	spin_unlock_irqrestore(&priv->lock, flags);

	netdev_info(priv->dev, "armed %s count=%u after=%u match=%s0x%x\n",
		    wbcan_fault_names[fault], count, after,
		    match_any ? "any/" : (match_id & CAN_EFF_FLAG) ? "e:" : "s:",
		    match_id & CAN_EFF_MASK);

out:
	argv_free(argv);
	return err ? err : len;
}

static int wbcan_status_show(struct seq_file *s, void *unused)
{
	struct wbcan_priv *priv = s->private;
	struct wbcan_status_snapshot snapshot;
	unsigned long flags;

	spin_lock_irqsave(&priv->lock, flags);
	snapshot.state = READ_ONCE(priv->can.state);
	snapshot.queue_stopped = netif_queue_stopped(priv->dev);
	snapshot.fault = priv->fault;
	snapshot.fault_count = priv->fault_count;
	snapshot.fault_after = priv->fault_after;
	snapshot.match_id = priv->match_id;
	snapshot.match_any = priv->match_any;
	snapshot.stat_tx = priv->stat_tx;
	snapshot.stat_rx = priv->stat_rx;
	snapshot.stat_injected = priv->stat_injected;
	snapshot.stat_seen = priv->stat_seen;
	snapshot.stat_restart_attempts = priv->stat_restart_attempts;
	snapshot.stat_stop_attempts = priv->stat_stop_attempts;
	snapshot.bus_errors = priv->can.can_stats.bus_error;
	spin_unlock_irqrestore(&priv->lock, flags);

	seq_printf(s, "state         %s\n",
		   snapshot.state == CAN_STATE_ERROR_ACTIVE  ? "error-active"  :
		   snapshot.state == CAN_STATE_ERROR_WARNING ? "error-warning" :
		   snapshot.state == CAN_STATE_ERROR_PASSIVE ? "error-passive" :
		   snapshot.state == CAN_STATE_BUS_OFF       ? "bus-off"       :
		   snapshot.state == CAN_STATE_STOPPED       ? "stopped"       :
							"sleeping");
	seq_printf(s, "queue_stopped %s\n",
		   snapshot.queue_stopped ? "yes" : "no");
	seq_printf(s, "armed_fault   %s\n", wbcan_fault_names[snapshot.fault]);
	seq_printf(s, "shots_left    %u\n", snapshot.fault_count);
	seq_printf(s, "skip_first    %u\n", snapshot.fault_after);
	if (snapshot.match_any)
		seq_puts(s, "match_id      any\n");
	else
		seq_printf(s, "match_id      %c:%x\n",
			   snapshot.match_id & CAN_EFF_FLAG ? 'e' : 's',
			   snapshot.match_id & CAN_EFF_MASK);
	seq_printf(s, "tx_frames     %llu\n", snapshot.stat_tx);
	seq_printf(s, "rx_frames     %llu\n", snapshot.stat_rx);
	seq_printf(s, "candidates    %llu\n", snapshot.stat_seen);
	seq_printf(s, "injected      %llu\n", snapshot.stat_injected);
	seq_printf(s, "restart_attempts %llu\n", snapshot.stat_restart_attempts);
	seq_printf(s, "stop_attempts %llu\n", snapshot.stat_stop_attempts);
	seq_printf(s, "bus_errors    %u\n", snapshot.bus_errors);

	return 0;
}

static int wbcan_status_open(struct inode *inode, struct file *file)
{
	return single_open(file, wbcan_status_show, inode->i_private);
}

static int wbcan_inject_open(struct inode *inode, struct file *file)
{
	file->private_data = inode->i_private;
	return 0;
}

static const struct file_operations wbcan_inject_fops = {
	.owner	= THIS_MODULE,
	.open	= wbcan_inject_open,
	.write	= wbcan_inject_write,
	.llseek	= noop_llseek,
};

static const struct file_operations wbcan_status_fops = {
	.owner	= THIS_MODULE,
	.open	= wbcan_status_open,
	.read	= seq_read,
	.llseek	= seq_lseek,
	.release = single_release,
};

/* ----------------------------------------------------------------- lifecycle */

static struct net_device *wbcan_dev;
static struct dentry *wbcan_dbg_root;
static bool fail_debugfs;
module_param(fail_debugfs, bool, 0400);
MODULE_PARM_DESC(fail_debugfs, "fail debugfs setup to test init cleanup");

static int wbcan_debugfs_err(const struct dentry *entry)
{
	if (IS_ERR(entry))
		return PTR_ERR(entry);
	return entry ? 0 : -ENODEV;
}

/*
 * Lifecycle is intentionally singleton-only: module load creates wbcan0 and
 * module unload removes it. This is not an RTNL link kind, so `ip link add
 * ... type wbcan` is intentionally unsupported.
 */
static int __init wbcan_init(void)
{
	struct wbcan_priv *priv;
	struct dentry *entry;
	int err;

	/*
	 * echo_skb_max 0: we do our own loopback in start_xmit rather than
	 * using can_put_echo_skb, because the fault plane needs to decide
	 * whether the frame comes back at all.
	 */
	wbcan_dev = alloc_candev(sizeof(struct wbcan_priv), 0);
	if (!wbcan_dev)
		return -ENOMEM;

	priv = netdev_priv(wbcan_dev);
	priv->dev = wbcan_dev;
	spin_lock_init(&priv->lock);
	u64_stats_init(&priv->stats_sync);
	priv->fault = WBCAN_FAULT_NONE;
	priv->match_any = true;

	wbcan_dev->netdev_ops = &wbcan_netdev_ops;
	wbcan_dev->ethtool_ops = &wbcan_ethtool_ops;
	wbcan_dev->flags |= IFF_ECHO;
	strscpy(wbcan_dev->name, "wbcan0", IFNAMSIZ);

	/*
	 * No real bit timing: there is no wire. Advertising fixed bitrate
	 * keeps `ip link set up` from demanding timing parameters, and makes
	 * it obvious this device does not model the physical layer. That is
	 * FW18's job, on the board.
	 */
	priv->can.bittiming.bitrate = 1000000;
	priv->can.ctrlmode_supported = CAN_CTRLMODE_LOOPBACK |
				       CAN_CTRLMODE_BERR_REPORTING;
	priv->can.do_set_mode = wbcan_set_mode;
	WRITE_ONCE(priv->can.state, CAN_STATE_STOPPED);
	/*
	 * alloc_candev() leaves the TX queue runnable until ndo_open(). Keep
	 * the queue stopped while the singleton is registered but down, so a
	 * fresh load has one coherent stopped-state snapshot.
	 */
	netif_stop_queue(wbcan_dev);

	err = register_candev(wbcan_dev);
	if (err)
		goto err_free;

	wbcan_dbg_root = debugfs_create_dir(KBUILD_MODNAME, NULL);
	err = wbcan_debugfs_err(wbcan_dbg_root);
	if (err) {
		wbcan_dbg_root = NULL;
		goto err_unregister;
	}
	priv->dbg_dir = debugfs_create_dir(wbcan_dev->name, wbcan_dbg_root);
	err = wbcan_debugfs_err(priv->dbg_dir);
	if (err) {
		priv->dbg_dir = NULL;
		goto err_debugfs;
	}
	if (fail_debugfs) {
		err = -EIO;
		goto err_debugfs;
	}
	entry = debugfs_create_file("inject", 0200, priv->dbg_dir, priv,
				    &wbcan_inject_fops);
	err = wbcan_debugfs_err(entry);
	if (err)
		goto err_debugfs;
	entry = debugfs_create_file("status", 0444, priv->dbg_dir, priv,
				    &wbcan_status_fops);
	err = wbcan_debugfs_err(entry);
	if (err)
		goto err_debugfs;

	netdev_info(wbcan_dev, "registered; fault plane ready at %s/%s/inject\n",
		    KBUILD_MODNAME, wbcan_dev->name);
	return 0;

err_debugfs:
	debugfs_remove_recursive(wbcan_dbg_root);
	wbcan_dbg_root = NULL;
err_unregister:
	unregister_candev(wbcan_dev);
err_free:
	free_candev(wbcan_dev);
	wbcan_dev = NULL;
	return err;
}

static void __exit wbcan_exit(void)
{
	if (!wbcan_dev)
		return;

	debugfs_remove_recursive(wbcan_dbg_root);
	wbcan_dbg_root = NULL;
	unregister_candev(wbcan_dev);
	free_candev(wbcan_dev);
	wbcan_dev = NULL;
}

module_init(wbcan_init);
module_exit(wbcan_exit);

MODULE_LICENSE("GPL");
MODULE_DESCRIPTION("Virtual CAN device with programmable fault injection");
