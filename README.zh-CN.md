# Workbench-1

**以证据为先的桌面机器人工作台:任务完成必须被验证,而不是被假设。**

[English](README.md) · [简体中文](README.zh-CN.md)

[![License](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE)
[![ROS 2](https://img.shields.io/badge/ROS_2-Jazzy-22314E?logo=ros&logoColor=white)](https://docs.ros.org/en/jazzy/)
[![Gazebo](https://img.shields.io/badge/Gazebo-Harmonic-FB7A00)](https://gazebosim.org/)
[![Python](https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white)](https://www.python.org/)

仿真环境中的单臂桌面机器人。你用自然语言输入目标;系统观测、规划受约束的动作、执行,
然后**检查目标是否真的达成**。证据缺失或相互冲突时,它报告不确定,而不是宣布成功。

```text
"把红色模块放进托盘。"

相机     ->  Observation      物体、位姿、置信度、证据引用
        ->  WorldState       事实 + 信念,事件溯源
        ->  TaskGraph        受约束;模型无法发出关节指令
        ->  抓取 / 放置       MoveIt 2 + Virtual MCU 安全层
        ->  Verifier         "模块真的在托盘里吗?" —— 附证据
        ->  失败时            重新观测、重试、或请求确认
        ->  表达              idle / thinking / uncertain / pleased
        ->  Dashboard        回放任务、动作、错误和结果
```

演示必须包含一次注入的故障。只跑通顺利路径的运行不算通过。

---

## 为什么做这个

多数机器人演示在最后一条指令返回 OK 时就报告成功。这和任务真的完成不是一回事。
本项目把**"指令已发出"到"目标已达成"之间的缺口**当作真正的工程问题。

- **返回 ACK 不等于执行成功。** MCU 层把"报文已写出"和"设备已确认"建模为两个独立状态。
- **动作完成不等于任务成功。** Verifier 独立地把世界状态与目标比对,并给出可指向的证据。
- **证据不足是一个合法答案。** 系统可以报告"无法确认"并重新观测,而不是输出一个看似
  合理的假结论。
- **语言模型永远不持有执行权。** 它只能从白名单化的受类型约束语义动作中选择。关节值、
  速度、急停和完成判定在结构上就不在它的可达范围内。

---

## 当前状态

### 已实现

| 能力 | 路径 |
|---|---|
| 受类型约束的 Python 契约 + 已提交的 JSON Schema | `interfaces/`、`libs/contracts/` |
| 确定性 WorldState reducer(事件溯源) | `services/world_model/` |
| 带证据引用的托盘容纳验证器 | `services/world_model/` |
| SQLite 事件库 + 回放查询 | `services/backend/` |
| 受约束的模板 TaskGraph 规划器 | `services/agent_runtime/` |
| Virtual MCU 安全状态机 | `firmware/virtual_mcu/` |
| 场景 manifest schema + 校验器 | `sim/scenarios/`、`tools/scripts/` |
| 契约测试 + 纯 Python 端到端 dry run | `tests/`、`tools/scripts/` |

### 尚未实现

以下是集成面。底座**故意不伪造**它们 —— 每一项都是真实的模块边界,且契约已经冻结。

| 能力 | 必须满足的契约 |
|---|---|
| Gazebo 世界、资产、相机、光照、spawn/reset | `scenario.schema.json` |
| MoveIt 2 抓取 / 放置 | `semantic_action.schema.json` → `action_result.schema.json` |
| 真实相机的 Observation(OpenCV + AprilTag/颜色) | `observation.schema.json` |
| 自然语言 → TaskGraph,本地模型优先 | `task_graph.schema.json` |
| 故障注入 | `scenario.schema.json` |
| Dashboard + 情绪表达 | `world_event.schema.json`、`emotion_intent.schema.json` |

### 明确不做

- 不做移动底盘,不做第二条活动臂
- 不训练视觉或大模型 —— 感知是针对已知目标的经典 CV
- 不做真实机械、电机、电源和 PCB
- **模型永远不控制关节、速度、急停或完成判定**
- 不做第二套仿真器、第二套数据库、第二个运行时 Agent

---

## 目标指标

以下是系统要达到的数值。标 **0** 的是不可放宽的发布门槛。

### 安全与正确性

| 指标 | 目标 |
|---|---|
| 误判完成 —— 宣布完成但实际未完成 | **0** |
| 碰撞 / 关节限位穿透 | **0** |
| 模型发出原始关节控制(越权) | **0** |
| 危险请求在策略层的拦截率 | 100% |
| 关键事件字段完整率 | 100% |

### 任务性能

| 指标 | 目标 |
|---|---|
| 固定脚本抓取放置成功率 | ≥ 90% |
| 已验证任务完成率(VTCR) | ≥ 80% |
| 失败后恢复成功率 | ≥ 70% |
| 任务完成时间 P95 | < 120 秒 |

### Agent 与感知

| 指标 | 目标 |
|---|---|
| 语义工具调用合法率 | ≥ 95% |
| 本地(离线)规划覆盖率 | ≥ 50% |
| 已知目标识别召回率 | ≥ 90% |
| Observation 必填字段完整率 | 100% |

### 世界模型与证据

| 指标 | 目标 |
|---|---|
| 相同事件流的 state hash 一致率 | 100% |
| WorldState 一致性 | ≥ 90% |
| 固定任务回放成功率 | ≥ 95% |
| 验证结论携带证据引用的比例 | 100% |

### 仿真与可复现性

| 指标 | 目标 |
|---|---|
| 冻结场景 schema 校验通过率 | 100% |
| 相同 seed 下场景配置 hash 一致率 | 100% |
| 场景 reset 成功率(连续 10 次) | 100% |
| 故障注入触发率 | ≥ 95% |

### 系统

| 指标 | 目标 |
|---|---|
| 一键启动到可用 —— 无模型链路 | < 90 秒 |
| 一键启动到可用 —— 含本地模型全栈 | < 180 秒 |
| CUDA 硬依赖 | 无 |
| 外部复现 | 3 人中 ≥ 2 人在 60 分钟内启动成功 |

---

## 快速开始

Ubuntu 24.04 或 WSL2,Python 3.12。

```bash
make bootstrap        # 安装开发依赖
make test             # 单元测试 + 契约测试
make contract         # 用示例校验 JSON Schema
make scenario-check   # 校验冻结的场景 manifest
make demo-scripted    # 纯 Python 契约 dry run,不含物理仿真
```

`make demo-scripted` 是**契约 dry run,不是物理仿真**。它在不启动 ROS 2 和 Gazebo 的
前提下,端到端验证事件 / 验证 / 回放这条链路 —— 所以你可以在没装完整仿真栈的机器上
开发任何一个模块。

Gazebo 层就位后的仿真入口:

```bash
make sim              # 启动 Gazebo 世界 + 机械臂 + 相机
make sim-reset SEED=… # 按 seed 重置场景
make demo             # 脚本化端到端,不需要模型
make demo-llm         # 含本地模型的全栈
```

---

## 接口契约

11 个 schema 定义了全部模块边界。它们是**冻结**的:修改任何一个都需要批准并通知所有
下游消费者,因为已经有别的模块按它写好了。

| Schema | 生产方 | 消费方 |
|---|---|---|
| `world_event` | 所有模块 | Dashboard |
| `observation` | 感知 | 世界模型 |
| `action_result` | 运动控制 | 世界模型 |
| `semantic_action` | Agent Runtime | 运动控制 |
| `world_state` | 世界模型 | Agent Runtime、Dashboard |
| `verification_result` | 世界模型 | Agent Runtime、Dashboard |
| `task_graph` | Agent Runtime | 运动控制 |
| `mcu_protocol` | Virtual MCU | 运动控制 |
| `emotion_intent` | Dashboard | Dashboard |
| `scenario` | 场景工厂 | 世界模型、bringup |
| `pose` | 共享 | 全部 |

Schema 位于 `interfaces/json_schema/`,每个在 `interfaces/examples/` 有一份合法示例。
`make contract` 会用示例校验每个 schema。

冻结一个 schema 之前,每个字段都要回答四个问题:

1. 这个字段缺失时,消费方是拒绝、降级、还是补默认值?
2. 谁有权写它?多个写入方就是冲突源。
3. 它的时间基准是什么 —— monotonic、墙钟、还是无?
4. 它会不会被评测真值污染?Oracle 字段必须和运行时字段物理分开。

在你按这些契约写代码之前,有三个设计决定值得先知道:

- **`action_result` 把 `dispatch_state` 和 `device_state` 拆开。** "报文已写出"在类型层面
  就无法被读成"设备已确认",这个区分由类型强制,不靠约定。
- **`verification_result.status` 是三值的** —— `confirmed` / `refuted` /
  `insufficient_evidence`。没有布尔的"完成"字段,因为"我无法确认"必须是可表达的。
- **`mcu_protocol` 拆分了 command id 区间。** 命令用 ≤ 32767,停止用 ≥ 32768,所以停止
  确认永远不可能被匹配到某条业务命令上。

---

## 目录结构

```
apps/dashboard/            回放、状态与表达显示
firmware/virtual_mcu/      协议编解码、安全状态机
interfaces/
  json_schema/             11 个冻结契约
  examples/                每个 schema 一份合法示例
libs/contracts/            受类型约束的 Python 模型
robot/
  bringup/                 launch 文件、健康检查
  description/             URDF、TF、关节限位
  control/                 控制器、安全限位
services/
  agent_runtime/           规划器、工具注册表、模型 provider
  backend/                 FastAPI + SQLite + 回放 API
  perception/              OpenCV / AprilTag 观测
  world_model/             reducer、验证器、故障注入
sim/scenarios/             冻结的 manifest + seed
tests/
  unit/                    分模块行为测试
  contract/                schema 一致性测试
tools/scripts/             校验器、dry run、task packet 检查
docs/
  architecture/            系统结构
  decisions/               架构决策记录(ADR)
```

---

## 验证边界

纯仿真项目。结果支持什么、不支持什么:

| 已验证 | 未验证 |
|---|---|
| 软件契约、事件完整性、回放 | 真实 CAN 电气层、总线仲裁时序 |
| 状态机与安全态转移 | 物理执行器动力学、电机负载 |
| 任务验证逻辑与证据链 | 传感器噪声、光照变化、标定漂移 |
| **Gazebo 物理下**的抓取放置成功率 | 真实硬件上的抓取成功率 |
| 故障注入与恢复路径 | 硬件急停、安全认证 |

软件安全停止不等于硬件急停。`vcan` 的 ACK 是应用层应答,不是数据链路层确认。Gazebo 里的
抓取成功率不经重新验证不能迁移到物理夹爪。

---

## 参与开发

写代码前读 [`AGENTS.md`](AGENTS.md),改接口前读
[`docs/architecture/system.md`](docs/architecture/system.md)。完整流程见
[`CONTRIBUTING.md`](CONTRIBUTING.md)。

不可绕过的规则:

1. `interfaces/` 是跨模块契约的唯一真相来源。
2. Agent Runtime 只发出语义动作 —— 永不发出关节位置或速度。
3. 世界模型是状态语义与完成验证的唯一拥有者。
4. 场景 manifest、seed 和故障类型在正式评测前冻结。
5. 任何成功、安全或指标声明都必须有事件和确定性证据。
6. AI 工具不做合并、不做发布、不改安全配置、不判定物理完成。

一次一个 Issue、一个有界模块。改生产方或消费方之前先读对应 schema。每个确定性行为变更
都要新增或更新一个测试。没有命令、测试结果和证据引用之前,不宣布任务完成。

本项目采用 AI 辅助开发。契约、不变量、验证策略和全部合并决定由人拥有。任何贡献模块的人
都应该能解释其中任意一个文件:为什么这样写、当时的替代方案是什么、为什么放弃它。

---

## 许可证

Apache-2.0。见 [LICENSE](LICENSE) 与 [NOTICE](NOTICE)。
第三方资产许可证记录在 [THIRD_PARTY_REVIEW.md](THIRD_PARTY_REVIEW.md)。
