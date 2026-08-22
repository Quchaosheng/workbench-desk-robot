# Linux 驱动架构

桌面机器人 Linux 驱动层的职责、生命周期和验收边界见仓库内的
`hardware/linux_drivers/README.md`。

这里保留面向系统审查的两条硬边界：

- Linux 驱动只负责标准内核子系统和硬件资源管理；语义动作仍由上层运行时产生，
  MCU 固件协议仍由固件模块维护。
- `kernel/wbcan` 是可重复的 SocketCAN 故障测试设备，不是目标板的物理 CAN 驱动，
  不能作为真实吞吐、延迟或 jitter 的证据。

后续驱动 PR 应先补齐目标控制器型号、寄存器/设备树资源和内核版本，再分别实现
CAN、UART/SPI、GPIO、DMA 和 IRQ 模块，并沿用本架构的错误回滚、数据所有权和
证据要求。
