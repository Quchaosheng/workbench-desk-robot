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
	u16			match_id;	/* 0xFFFF = any */
	u8			flip_byte;
	u8			flip_bit;

	/* Observability. A fault you cannot count is a fault you cannot
	 * assert on from a test. */
	u64			stat_tx;
	u64			stat_rx;
	u64			stat_injected;
	u64			stat_seen;
};

/* ------------------------------------------------------------------ helpers */

/* Decide whether this frame takes the fault, and consume one shot if so.
 * Called with the lock held.
 */
static bool wbcan_should_inject(struct wbcan_priv *priv, canid_t id)
{
	if (priv->fault == WBCAN_FAULT_NONE || priv->fault_count == 0)
		return false;

	if (priv->match_id != 0xFFFF && (id & CAN_EFF_MASK) != priv->match_id)
		return false;

	priv->stat_seen++;

	if (priv->fault_after > 0) {
		priv->fault_after--;
		return false;
	}

	priv->fault_count--;
	priv->stat_injected++;
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
	if (!skb)
		return;

	switch (fault) {
	case WBCAN_FAULT_BUS_OFF:
		/* Bus-off is terminal until the driver is restarted. The CAN
		 * core handles the restart timer if restart-ms is set, which
		 * is what FW19 exercises. */
		netif_stop_queue(dev);
		tx_state = CAN_STATE_BUS_OFF;
		rx_state = CAN_STATE_BUS_OFF;
		can_change_state(dev, cf, tx_state, rx_state);
		can_bus_off(dev);
		break;

	case WBCAN_FAULT_ARB_LOST:
		cf->can_id |= CAN_ERR_LOSTARB;
		/* Bit position that lost. 0 means unspecified, which is
		 * honest here: we are not modelling a real bit timeline. */
		cf->data[0] = 0;
		priv->can.can_stats.arbitration_lost++;
		break;

	case WBCAN_FAULT_STUFF_ERR:
		cf->can_id |= CAN_ERR_PROT;
		cf->data[2] = CAN_ERR_PROT_STUFF;
		/* Errors accumulate toward passive then bus-off, mirroring
		 * the real REC/TEC rules the firmware has to survive. */
		priv->can.can_stats.bus_error++;
		tx_state = CAN_STATE_ERROR_WARNING;
		can_change_state(dev, cf, tx_state, rx_state);
		break;

	default:
		cf->can_id |= CAN_ERR_CRTL;
		cf->data[1] = CAN_ERR_CRTL_UNSPEC;
		break;
	}

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
		/* A real controller does not quietly accept frames while
		 * bus-off. Report it so the firmware's TX error path runs. */
		dev->stats.tx_dropped++;
		kfree_skb(skb);
		return NETDEV_TX_OK;
	}

	if (wbcan_should_inject(priv, cf->can_id))
		fault = priv->fault;

	priv->stat_tx++;
	spin_unlock_irqrestore(&priv->lock, flags);

	switch (fault) {
	case WBCAN_FAULT_TX_FULL:
		/* Mailboxes full. Stopping the queue and returning BUSY is
		 * how a real driver applies backpressure; the stack will
		 * retry when we wake it. */
		netif_stop_queue(dev);
		wbcan_emit_error(dev, fault);
		/* Wake immediately: we are modelling a transient full
		 * condition, not a wedge. Without this the test hangs. */
		netif_wake_queue(dev);
		return NETDEV_TX_BUSY;

	case WBCAN_FAULT_BUS_OFF:
	case WBCAN_FAULT_ARB_LOST:
	case WBCAN_FAULT_STUFF_ERR:
		wbcan_emit_error(dev, fault);
		dev->stats.tx_errors++;
		kfree_skb(skb);
		return NETDEV_TX_OK;

	case WBCAN_FAULT_DROP_TX:
		/* Accepted, counted, never delivered. This is the nastiest
		 * failure for firmware: no error, no frame. */
		dev->stats.tx_packets++;
		dev->stats.tx_bytes += cf->len;
		kfree_skb(skb);
		return NETDEV_TX_OK;

	default:
		break;
	}

	dev->stats.tx_packets++;
	dev->stats.tx_bytes += cf->len;

	/* Deliver to local sockets. skb_clone because the RX path consumes it
	 * and the TX echo may still want the original. */
	rx_skb = skb_clone(skb, GFP_ATOMIC);
	if (!rx_skb) {
		kfree_skb(skb);
		return NETDEV_TX_OK;
	}

	if (fault == WBCAN_FAULT_BIT_FLIP) {
		struct can_frame *rcf = (struct can_frame *)rx_skb->data;
		u8 byte = priv->flip_byte;
		u8 bit = priv->flip_bit & 0x7;

		if (byte < rcf->len) {
			rcf->data[byte] ^= (1u << bit);
			netdev_dbg(dev, "flipped byte %u bit %u of id 0x%x\n",
				   byte, bit, rcf->can_id);
		}
	}

	if (fault == WBCAN_FAULT_DROP_RX) {
		kfree_skb(rx_skb);
	} else {
		rx_skb->dev = dev;
		rx_skb->ip_summed = CHECKSUM_UNNECESSARY;
		rx_skb->pkt_type = PACKET_BROADCAST;
		dev->stats.rx_packets++;
		dev->stats.rx_bytes += cf->len;

		spin_lock_irqsave(&priv->lock, flags);
		priv->stat_rx++;
		spin_unlock_irqrestore(&priv->lock, flags);

		netif_rx(rx_skb);
	}

	consume_skb(skb);
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
		/* Clear the armed fault on restart. Leaving it armed would
		 * make recovery tests flap for reasons the test did not ask
		 * for. */
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

static const struct net_device_ops wbcan_netdev_ops = {
	.ndo_open	= wbcan_open,
	.ndo_stop	= wbcan_stop,
	.ndo_start_xmit	= wbcan_start_xmit,
	.ndo_change_mtu	= can_change_mtu,
};

/* --------------------------------------------------------------- debugfs ABI
 *
 * echo "<mode> <count> [after] [id] [byte] [bit]" > /sys/kernel/debug/wbcan/<dev>/inject
 *
 *   arm 3 frames of drop-tx:            echo "drop-tx 3" > inject
 *   flip bit 2 of byte 0, 4th frame on: echo "bit-flip 1 3 ffff 0 2" > inject
 *   bus-off only for id 0x123:          echo "bus-off 1 0 123" > inject
 *
 * Text, not ioctl: a shell script in CI has to drive this, and a text ABI is
 * one line of bash instead of a helper binary.
 */

static ssize_t wbcan_inject_write(struct file *file, const char __user *ubuf,
				  size_t len, loff_t *ppos)
{
	struct wbcan_priv *priv = file->private_data;
	char buf[96], mode[24];
	u32 count = 1, after = 0, id = 0xFFFF, byte = 0, bit = 0;
	unsigned long flags;
	int i, matched, fault = -1;

	if (len == 0 || len >= sizeof(buf))
		return -EINVAL;
	if (copy_from_user(buf, ubuf, len))
		return -EFAULT;
	buf[len] = '\0';

	matched = sscanf(buf, "%23s %u %u %x %u %u",
			 mode, &count, &after, &id, &byte, &bit);
	if (matched < 1)
		return -EINVAL;

	for (i = 0; i < WBCAN_FAULT_MAX; i++) {
		if (wbcan_fault_names[i] && sysfs_streq(mode, wbcan_fault_names[i])) {
			fault = i;
			break;
		}
	}
	if (fault < 0) {
		pr_warn("unknown fault mode '%s'\n", mode);
		return -EINVAL;
	}

	if (bit > 7 || byte > 7)
		return -EINVAL;

	spin_lock_irqsave(&priv->lock, flags);
	priv->fault       = fault;
	priv->fault_count = (fault == WBCAN_FAULT_NONE) ? 0 : count;
	priv->fault_after = after;
	priv->match_id    = (u16)id;
	priv->flip_byte   = (u8)byte;
	priv->flip_bit    = (u8)bit;
	priv->stat_seen   = 0;
	spin_unlock_irqrestore(&priv->lock, flags);

	netdev_info(priv->dev, "armed %s count=%u after=%u id=0x%x\n",
		    wbcan_fault_names[fault], count, after, id);

	return len;
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
	seq_printf(s, "match_id      0x%x\n", priv->match_id);
	seq_printf(s, "tx_frames     %llu\n", priv->stat_tx);
	seq_printf(s, "rx_frames     %llu\n", priv->stat_rx);
	seq_printf(s, "candidates    %llu\n", priv->stat_seen);
	seq_printf(s, "injected      %llu\n", priv->stat_injected);
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

static int __init wbcan_init(void)
{
	struct wbcan_priv *priv;
	int err;

	/* echo_skb_max 0: we do our own loopback in start_xmit rather than
	 * using can_put_echo_skb, because the fault plane needs to decide
	 * whether the frame comes back at all. */
	wbcan_dev = alloc_candev(sizeof(struct wbcan_priv), 0);
	if (!wbcan_dev)
		return -ENOMEM;

	priv = netdev_priv(wbcan_dev);
	priv->dev = wbcan_dev;
	spin_lock_init(&priv->lock);
	priv->fault = WBCAN_FAULT_NONE;
	priv->match_id = 0xFFFF;

	wbcan_dev->netdev_ops = &wbcan_netdev_ops;
	wbcan_dev->flags |= IFF_ECHO;
	strscpy(wbcan_dev->name, "wbcan%d", IFNAMSIZ);

	/* No real bit timing: there is no wire. Advertising fixed bitrate
	 * keeps `ip link set up` from demanding timing parameters, and makes
	 * it obvious this device does not model the physical layer. That is
	 * FW18's job, on the board. */
	priv->can.bittiming.bitrate = 1000000;
	priv->can.ctrlmode_supported = CAN_CTRLMODE_LOOPBACK |
				       CAN_CTRLMODE_BERR_REPORTING;
	priv->can.do_set_mode = wbcan_set_mode;
	priv->can.state = CAN_STATE_STOPPED;

	err = register_candev(wbcan_dev);
	if (err) {
		free_candev(wbcan_dev);
		wbcan_dev = NULL;
		return err;
	}

	wbcan_dbg_root = debugfs_create_dir(KBUILD_MODNAME, NULL);
	priv->dbg_dir = debugfs_create_dir(wbcan_dev->name, wbcan_dbg_root);
	debugfs_create_file("inject", 0200, priv->dbg_dir, priv,
			    &wbcan_inject_fops);
	debugfs_create_file("status", 0444, priv->dbg_dir, priv,
			    &wbcan_status_fops);

	netdev_info(wbcan_dev, "registered; arm faults via debugfs %s/%s/inject\n",
		    KBUILD_MODNAME, wbcan_dev->name);
	return 0;
}

static void __exit wbcan_exit(void)
{
	if (!wbcan_dev)
		return;

	debugfs_remove_recursive(wbcan_dbg_root);
	unregister_candev(wbcan_dev);
	free_candev(wbcan_dev);
	wbcan_dev = NULL;
}

module_init(wbcan_init);
module_exit(wbcan_exit);

MODULE_LICENSE("GPL");
MODULE_DESCRIPTION("Virtual CAN device with programmable fault injection");
MODULE_ALIAS_RTNL_LINK("wbcan");
