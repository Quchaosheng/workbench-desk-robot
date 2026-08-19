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

#include <linux/module.h>
#include <linux/init.h>
#include <linux/netdevice.h>
#include <linux/if_arp.h>
#include <linux/debugfs.h>
#include <linux/err.h>
#include <linux/slab.h>
#include <linux/spinlock.h>
#include <linux/string.h>
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

struct wbcan_priv {
	struct can_priv		can;	/* must be first: can_priv contract */
	struct net_device	*dev;
	struct dentry		*dbg_dir;

	spinlock_t		lock;	/* guards the fault plane below */

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
};

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
	struct can_frame *cf;
	struct sk_buff *skb;
	enum can_state tx_state = priv->can.state;
	enum can_state rx_state = priv->can.state;

	skb = alloc_can_err_skb(dev, &cf);

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
		can_change_state(dev, cf, tx_state, rx_state);
		can_bus_off(dev);
		break;

	case WBCAN_FAULT_ARB_LOST:
		if (!cf)
			return;
		cf->can_id |= CAN_ERR_LOSTARB;
		/*
		 * Bit position that lost. 0 means unspecified, which is
		 * honest here: we are not modelling a real bit timeline.
		 */
		cf->data[0] = 0;
		priv->can.can_stats.arbitration_lost++;
		break;

	case WBCAN_FAULT_STUFF_ERR:
		if (!cf)
			return;
		cf->can_id |= CAN_ERR_PROT;
		cf->data[2] = CAN_ERR_PROT_STUFF;
		/*
		 * This is a bounded protocol-error model: one warning per
		 * injected frame, then the next fault-free frame recovers to
		 * active. We do not pretend to model TEC/REC progression.
		 */
		priv->can.can_stats.bus_error++;
		tx_state = CAN_STATE_ERROR_WARNING;
		can_change_state(dev, cf, tx_state, rx_state);
		break;

	default:
		if (!cf)
			return;
		cf->can_id |= CAN_ERR_CRTL;
		cf->data[1] = CAN_ERR_CRTL_UNSPEC;
		break;
	}

	if (skb)
		netif_rx(skb);
}

/* --------------------------------------------------------------- netdev ops */

static int wbcan_open(struct net_device *dev)
{
	struct wbcan_priv *priv = netdev_priv(dev);
	int err;

	err = open_candev(dev);
	if (err)
		return err;
	priv->can.state = CAN_STATE_ERROR_ACTIVE;
	netif_start_queue(dev);
	return 0;
}

static int wbcan_stop(struct net_device *dev)
{
	struct wbcan_priv *priv = netdev_priv(dev);

	netif_stop_queue(dev);
	close_candev(dev);
	priv->can.state = CAN_STATE_STOPPED;
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

	if (can_dev_dropped_skb(dev, skb))
		return NETDEV_TX_OK;

	/* Loopback of our own error frames would be circular. */
	if (cf->can_id & CAN_ERR_FLAG) {
		kfree_skb(skb);
		return NETDEV_TX_OK;
	}

	spin_lock_irqsave(&priv->lock, flags);

	if (priv->can.state == CAN_STATE_BUS_OFF) {
		spin_unlock_irqrestore(&priv->lock, flags);
		/*
		 * A real controller does not quietly accept frames while
		 * bus-off. Report it so the firmware's TX error path runs.
		 */
		dev->stats.tx_dropped++;
		kfree_skb(skb);
		return NETDEV_TX_OK;
	}

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

	case WBCAN_FAULT_BUS_OFF:
	case WBCAN_FAULT_ARB_LOST:
	case WBCAN_FAULT_STUFF_ERR:
		spin_lock_irqsave(&priv->lock, flags);
		priv->stat_tx++;
		spin_unlock_irqrestore(&priv->lock, flags);
		wbcan_emit_error(dev, fault);
		dev->stats.tx_errors++;
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
		dev->stats.tx_packets++;
		dev->stats.tx_bytes += len;
		kfree_skb(skb);
		return NETDEV_TX_OK;

	default:
		break;
	}

	/* Count frames accepted by the driver; a BUSY retry is not a frame. */
	spin_lock_irqsave(&priv->lock, flags);
	priv->stat_tx++;
	if (fault == WBCAN_FAULT_NONE &&
	    priv->can.state == CAN_STATE_ERROR_WARNING)
		priv->can.state = CAN_STATE_ERROR_ACTIVE;
	spin_unlock_irqrestore(&priv->lock, flags);

	dev->stats.tx_packets++;
	dev->stats.tx_bytes += len;
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
		dev->stats.rx_dropped++;
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
	} else {
		rx_skb->dev = dev;
		rx_skb->ip_summed = CHECKSUM_UNNECESSARY;
		rx_skb->pkt_type = PACKET_BROADCAST;
		dev->stats.rx_packets++;
		dev->stats.rx_bytes += len;

		spin_lock_irqsave(&priv->lock, flags);
		priv->stat_rx++;
		spin_unlock_irqrestore(&priv->lock, flags);

		netif_rx(rx_skb);
	}

	return NETDEV_TX_OK;
}

/* Called by the CAN core's restart timer, and by `ip link set can0 type can
 * restart`. FW19's bus-off recovery test drives this path.
 */
static int wbcan_set_mode(struct net_device *dev, enum can_mode mode)
{
	struct wbcan_priv *priv = netdev_priv(dev);
	unsigned long flags;

	switch (mode) {
	case CAN_MODE_START:
		spin_lock_irqsave(&priv->lock, flags);
		priv->can.state = CAN_STATE_ERROR_ACTIVE;
		/*
		 * Clear the armed fault on restart. Leaving it armed would
		 * make recovery tests flap for reasons the test did not ask
		 * for.
		 */
		priv->fault = WBCAN_FAULT_NONE;
		priv->fault_count = 0;
		spin_unlock_irqrestore(&priv->lock, flags);

		netif_wake_queue(dev);
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
	unsigned long flags;

	spin_lock_irqsave(&priv->lock, flags);
	seq_printf(s, "state         %s\n",
		   priv->can.state == CAN_STATE_ERROR_ACTIVE  ? "error-active"  :
		   priv->can.state == CAN_STATE_ERROR_WARNING ? "error-warning" :
		   priv->can.state == CAN_STATE_ERROR_PASSIVE ? "error-passive" :
		   priv->can.state == CAN_STATE_BUS_OFF       ? "bus-off"       :
		   priv->can.state == CAN_STATE_STOPPED       ? "stopped"       :
							"sleeping");
	seq_printf(s, "armed_fault   %s\n", wbcan_fault_names[priv->fault]);
	seq_printf(s, "shots_left    %u\n", priv->fault_count);
	seq_printf(s, "skip_first    %u\n", priv->fault_after);
	if (priv->match_any)
		seq_puts(s, "match_id      any\n");
	else
		seq_printf(s, "match_id      %c:%x\n",
			   priv->match_id & CAN_EFF_FLAG ? 'e' : 's',
			   priv->match_id & CAN_EFF_MASK);
	seq_printf(s, "tx_frames     %llu\n", priv->stat_tx);
	seq_printf(s, "rx_frames     %llu\n", priv->stat_rx);
	seq_printf(s, "candidates    %llu\n", priv->stat_seen);
	seq_printf(s, "injected      %llu\n", priv->stat_injected);
	seq_printf(s, "bus_errors    %u\n", priv->can.can_stats.bus_error);
	spin_unlock_irqrestore(&priv->lock, flags);

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
	priv->fault = WBCAN_FAULT_NONE;
	priv->match_any = true;

	wbcan_dev->netdev_ops = &wbcan_netdev_ops;
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
	priv->can.state = CAN_STATE_STOPPED;

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
