# UART/SPI 软件契约

这是 LINUX3 的软件提案和 fake transport 测试边界，不是已经冻结的生产硬件 ABI。
它不决定真实 UART 波特率、SPI 时钟、设备树节点、DMA 通道、IRQ 号或 pinmux；这些
参数需要 PCB、MCU 和 Linux Owner 共同确认后才能实现物理驱动。

## 帧格式

每个传输使用一个有界二进制帧：

| 字段 | 大小 | 编码 |
|---|---:|---|
| magic | 2 | ASCII `WB` |
| version | 1 | `0x01` |
| transport | 1 | UART=`1`，SPI=`2` |
| sequence | 2 | big-endian，无符号 |
| payload length | 2 | big-endian，最大 256 |
| payload | 0-256 | 不可变字节串 |
| CRC | 2 | CRC-16/CCITT-FALSE，覆盖 header + payload |

最小帧长为 10 字节，最大帧长为 266 字节。接收方在校验 magic、版本、传输类型、
长度和 CRC 之前不得把 payload 交给上层。

## 序号、重试和队列

- 序号为 16 位；接收方使用模 65536 的半范围规则判断新帧。
- 重复、过期或半范围歧义的序号直接拒绝，不更新接收状态。
- 重试复用同一序号和同一帧字节，不得因重试产生新的逻辑消息。
- fake transport 的队列容量有上限；队列满返回 backpressure，不能静默丢弃。
- `UartSpiSession` 最多允许 3 次重试；关闭的传输、写入异常和超时都显式失败。
- partial write/read 由 session 重组；只有完整 CRC 校验通过的帧才会返回。

## 生产接入前的待确认项

1. UART/SPI 控制器和 Linux 内核版本；
2. 设备树/ACPI 节点、设备名、pinmux、CS 和电平转换；
3. MCU 端帧语义、ACK 关联、超时和错误码；
4. 是否启用 DMA、IRQ 触发方式和缓存一致性要求；
5. 队列容量、实时预算和目标硬件原始收发证据。

当前 fake transport 只能验证编码、边界、所有权、重试、背压和错误恢复。它不能证明
物理信号完整性、UART/SPI 线速、DMA 吞吐、IRQ jitter 或 MCU 行为。
