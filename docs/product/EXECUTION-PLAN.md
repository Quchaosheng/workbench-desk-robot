# Workbench-1 九人核心执行计划书（含仿真工程师）

> 版本：v1.0  
> 日期：2026-08-04  
> 周期：2026-08-04 至 2026-08-31  
> 团队：9 名核心成员  
> 月底交付：可复现的仿真桌面机器人 GitHub v0.1

---

## 1. 月底要做成什么

在普通电脑上运行一条命令，启动一个固定桌面单臂仿真机器人。用户输入：

> 把红色模块放进托盘。

机器人必须展示以下闭环：

```text
摄像头识别红色模块和托盘
  -> WorldState 记录物体、位置、置信度和证据
  -> Agent 将语言转换为受约束 TaskGraph
  -> 机械臂抓取并放置
  -> Verifier 判断模块是否真的在托盘内
  -> 失败时重新观察、重试或请求确认
  -> 屏幕/姿态表达 thinking、uncertain、pleased
  -> Dashboard 回放任务、动作、错误和结果
```

正式演示必须出现一次故障：目标移动、路径阻挡、抓取失败或 MCU 超时均可。

### 本月不做

- 不做移动底盘 P0；
- 不做双活动臂；
- 不训练视觉或大模型；
- 不做真实机械、电机、电源和 PCB；
- 不做复杂 BCI；
- 不让大模型控制关节、速度、急停或任务完成判定；
- 不做第二套仿真器、第二套数据库或第二个运行时 Agent。

---

## 2. 九人组织与模块边界

| 编号 | 人员 | 唯一模块 | 只对什么结果负责 |
|---:|---|---|---|
| 1 | 你 / Product Owner | 产品、范围、验收、发布 | 做什么、何时冻结、是否发布 |
| 2 | Agent A | Agent Runtime | 语言到 TaskGraph、工具调用、恢复 |
| 3 | Agent B | 对话、情绪、Dashboard | 用户是否看懂状态和过程 |
| 4 | Agent C | 受控视觉与评测 | 是否正确观测已知目标、实验是否可信 |
| 5 | 世界模型工程师 | WorldState、验证、事件库 | 当前状态是否可追溯、任务是否真实完成 |
| 6 | Linux 工程师 | ROS/Gazebo、容器、CI、集成 | 全部模块是否能一键运行和复现 |
| 7 | MCU 工程师 | Virtual MCU、安全协议 | 超时、断连、stop 是否进入安全状态 |
| 8 | 运动控制工程师 | 仿真机械臂、抓取放置、安全动作 | 机器人是否安全、稳定地完成语义动作 |
| 9 | 仿真工程师 | Gazebo 世界、传感器、场景、故障注入、批量跑测 | 30 个场景是否可重复生成、重置和评测 |

**关键规则**：

- 每个人只拥有一个模块；
- Agent A、B、C 是三个开发负责人，不是机器人运行时的三个自由 Agent；
- 运行时只有一个 Agent Runtime；
- 世界模型工程师兼任最小 Backend：FastAPI + SQLite + Replay API；
- Agent C 只做 OpenCV + AprilTag/颜色识别，不做深度视觉训练；
- Linux 是 Integration Captain；你是唯一 Release Owner。
- 仿真工程师拥有 world、object、tray、camera、lighting、seed、reset、fault injection 和 scenario manifest；运动控制拥有 URDF、MoveIt、控制器和动作安全。

---

## 3. 系统怎么连接

```text
仿真工程师: Gazebo world / camera / seed / fault injection
                    |
                    v
Agent C: Camera -> Observation
                    |
                    v
世界模型: WorldState + VerificationResult + Event Store
                    |
                    v
Agent A: User Goal -> TaskGraph -> SemanticAction
                    |
                    v
运动控制: MoveIt / ActionResult -> Linux + Gazebo + Virtual MCU
                    |
                    v
世界模型: 写入事件、验证结果、任务指标
                    |
                    v
Agent B: Dashboard / Replay / Emotion
```

Agent A 只能发送 `observe`、`grasp`、`place`、`ask_confirm`、`express`、`stop` 等语义动作。运动控制、MCU 和验证器拥有最终安全权。

---

## 4. 四周计划

| 周次 | 日期 | 团队唯一目标 | 验收门 |
|---|---|---|---|
| W1 | 08/04-08/09 | 所有模块最小骨架可连接，仿真世界可重置 | 08/07：一条命令启动，机械臂能动，事件入库，场景可按 seed 重建 |
| W2 | 08/10-08/16 | 不用 LLM 跑通抓取、放置、验证和回放 | 08/14：固定脚本连续 10 次运行 |
| W3 | 08/17-08/23 | 自然语言、世界模型验证、恢复、情绪和 Dashboard 连通 | 08/21：完整 Agent Demo，随后功能冻结 |
| W4 | 08/24-08/31 | 90 次评测、修复、外测和发布 | 08/28：代码冻结；08/31：v0.1 发布 |

---

## 5. 每个人的任务

### 5.1 你：Product Owner

| 周次 | 必做任务 | 交付物 |
|---|---|---|
| W1 | 冻结唯一演示、P0、机器人资产、接口 Owner、评测口径；建立 8 个 Epic | 项目看板、责任表、验收表 |
| W2 | 做 5-8 次用户/实验室访谈；验收脚本闭环；砍掉阻塞功能 | 访谈记录、范围变更表 |
| W3 | 组织全链路 Demo、5 人状态理解测试、3 人冷启动 | 测试记录、功能冻结决定 |
| W4 | 组织 90 次实验、Release 审核、README、视频和复盘 | GitHub v0.1、Go/Pivot/Stop 报告 |

**月底验收**：8 个 Epic 都有唯一 Owner；完成 8-10 次访谈；3 名外部人员中至少 2 人在 60 分钟内启动成功；发布内容包含限制和失败案例。

### 5.2 Agent A：Agent Runtime

| 周次 | 必做任务 | 交付物 |
|---|---|---|
| W1 | 定义 `observe/grasp/place/ask_confirm/express/stop`；Mock Agent；行为树 | Tool Schema、Mock Demo、单元测试 |
| W2 | 固定 TaskGraph 跑通取放；实现 timeout/retry/cancel | 确定性回放、错误路径测试 |
| W3 | 接入本地模型优先的 ModelProvider；自然语言转 TaskGraph；读取验证结果恢复 | 断网 Demo、恢复事件链 |
| W4 | 跑 100 条合法/非法工具请求；冻结 prompt、模型和路由 | 合法率报告、拒绝样例、回归测试 |

**月底验收**：工具合法率 >= 95%；原始关节控制越权 = 0；固定任务无云 API 可运行；本地规划覆盖率目标 >= 70%；模型超时和低置信度都有降级逻辑。

### 5.3 Agent B：对话、情绪与 Dashboard

| 周次 | 必做任务 | 交付物 |
|---|---|---|
| W1 | 定义四种情绪和状态转移；完成 Dashboard 页面草图 | EmotionIntent、页面草图 |
| W2 | 显示任务状态、当前步骤、错误和时间线 | 状态页、时间线页 |
| W3 | 接入失败、确认、恢复、回放和表达动画 | 可运行 Dashboard、完整交互 Demo |
| W4 | 做用户理解测试，整理截图和资产许可证 | HRI 报告、发布截图 |

**月底验收**：`idle`、`thinking`、`uncertain`、`pleased` 可触发；5 人中 >= 80% 理解状态；Dashboard 不连接 ROS 控制 topic；语音失败时仍可使用屏幕/文本。

### 5.4 Agent C：受控视觉与评测

| 周次 | 必做任务 | 交付物 |
|---|---|---|
| W1 | 用 OpenCV + AprilTag/颜色识别建立视觉 baseline；冻结 20 条任务和 10 条危险请求 | Observation Schema、标定说明、黄金集 |
| W2 | 从 Gazebo 相机输出目标、位姿、置信度、时间戳 | Sensor Demo、字段测试 |
| W3 | 为仿真工程师提供遮挡、目标移动、低置信度和抓取失败的视觉验收规则；评测模板/本地模型 | 视觉失败样例、评测脚本 |
| W4 | 审核 90 次 A/B/C 的感知和 Agent 结果并出报告 | 原始数据、统计图、限制说明 |

**月底验收**：已知目标识别召回率 >= 90%；Observation 必填字段完整率 100%；危险请求策略层最终拦截率 100%；不使用 Oracle 计算 Sensor 成绩；不训练新模型。

### 5.5 世界模型工程师：WorldState、验证和事件库

| 周次 | 必做任务 | 交付物 |
|---|---|---|
| W1 | 定义 Event、WorldState、Belief、Prediction、VerificationResult；接 SQLite/FastAPI | Schema、事件表、重建测试 |
| W2 | 接 Observation 和 ActionResult；实现“模块在托盘内”验证与回放查询 | Verifier、Replay API、证据链 |
| W3 | 实现动作前预测、动作后验证和恢复建议 | VerificationResult、恢复事件 |
| W4 | 输出状态一致性、误判完成和任务指标 | 原始数据、世界模型报告 |

**月底验收**：同事件流 state hash 一致率 100%；WorldState 一致性 >= 90%；False Completion = 0；关键事件完整率 100%；每个验证结论都有 evidence refs。

### 5.6 Linux：ROS、Gazebo、CI 和集成

| 周次 | 必做任务 | 交付物 |
|---|---|---|
| W1 | 锁 Ubuntu 24.04、ROS 2 Jazzy、Gazebo Harmonic；建容器、bringup、Health、CI | `make sim`、环境锁文件 |
| W2 | 联通机械臂、相机、世界模型、Agent 和 Dashboard | Smoke Test、统一日志格式 |
| W3 | 支持本地模型 Runner、断网模式、进程守护和故障重启 | `make model-local`、断网记录 |
| W4 | Headless、发布镜像、外部冷启动和系统 SBOM | 镜像 digest、安装文档、复现记录 |

**月底验收**：一键启动到可用 < 120 秒；无 CUDA 硬依赖；所有服务有 Health；固定 Demo 无 API Key 可运行；2/3 外部人员 60 分钟内启动成功。

### 5.7 MCU：Virtual MCU 和安全协议

| 周次 | 必做任务 | 交付物 |
|---|---|---|
| W1 | 定义协议、Telemetry、FaultCode 和 Virtual MCU | 协议文档、模拟器、单元测试 |
| W2 | 实现状态机、重复包、超时、断连和 watchdog | 状态图、故障测试 |
| W3 | 与 Linux/运动联调 stop、超时和安全状态 | Virtual HIL Demo、运行日志 |
| W4 | 做协议回归、版本和安全说明 | 协议报告、发布 artifact |

**月底验收**：协议测试通过率 100%；20 个预定义 timeout/断连/stop 故障均进入安全状态；重复消息不产生重复动作；安全链不依赖云模型。

### 5.8 运动控制：仿真机械臂、抓取放置和安全动作

| 周次 | 必做任务 | 交付物 |
|---|---|---|
| W1 | 导入成熟单臂资产，完成 URDF、TF、控制器、限位和工作空间 | Gazebo/RViz Demo、关节测试 |
| W2 | 使用 MoveIt 2 跑通抓取、放置和 ActionResult | 10 次脚本运行、动作接口 |
| W3 | 支持抓取失败、目标移动、取消和重新执行 | 故障恢复 Demo、ActionResult 日志 |
| W4 | 参与 90 次评测，完成性能和安全报告 | P50/P95、失败分布、碰撞报告 |

**月底验收**：固定脚本取放成功率 >= 90%；碰撞/限位穿透 = 0；ActionResult 字段完整率 100%；任务时间 P95 < 120 秒；不通过放宽安全限制提高成功率。

### 5.9 仿真工程师：Gazebo 世界、场景和故障注入

| 周次 | 必做任务 | 交付物 |
|---|---|---|
| W1 | 冻结 `WorkbenchSim-v0`：桌面、托盘、红色模块、相机、光照、碰撞体、spawn/reset 和 seed 格式 | 世界文件、资产清单、场景 Schema、`make sim-reset` |
| W2 | 支持固定任务的 reset、对象摆放、相机传感器和 headless 批量运行 | 10 次 reset 记录、脚本任务场景 |
| W3 | 实现遮挡、目标移动、路径阻挡、抓取失败、服务/MCU 超时六类场景和故障注入 | 30 个 manifest、故障注入脚本、validator |
| W4 | 执行/协助执行 A/B/C 90 次批量运行，保留 seed、版本、日志和 rosbag 引用 | 运行清单、失败分类、可重跑命令 |

**月底验收**：

- 30 个冻结 manifest 的 schema 校验通过率 100%；
- 同一 seed 重建出的场景配置 hash 一致率 100%；
- 10 次连续 reset 成功率 100%；
- 六类故障均能按 manifest 注入，触发率 >= 95%；
- Scenario Factory 不读取 release holdout 的期望答案；
- 90 次运行均有 seed、commit、场景版本和日志引用；
- 不通过关闭碰撞、扩大限位或泄露 Oracle 来提高成绩。

---

## 6. 最终性能指标

| 类别 | 指标 | 月底目标 |
|---|---|---:|
| 抓取 | 固定脚本抓取放置成功率 | >= 90% |
| 总体 | 完整系统 VTCR | >= 80% |
| 恢复 | 失败后恢复成功率 | >= 70% |
| Agent | 语义工具调用合法率 | >= 95% |
| Agent | 本地规划覆盖率 | >= 70% |
| 感知 | 已知目标识别召回率 | >= 90% |
| 世界模型 | WorldState 一致性 | >= 90% |
| 安全 | False Completion | 0 |
| 安全 | 碰撞、限位、越权关节控制 | 0 |
| 数据 | 关键事件字段完整率 | 100% |
| 回放 | 固定任务回放成功率 | >= 95% |
| 仿真 | 30 个冻结场景 schema 校验通过率 | 100% |
| 仿真 | 场景 reset 成功率 | 100% |
| 仿真 | 故障注入触发率 | >= 95% |
| 交互 | 四状态理解率 | >= 80% |
| 性能 | 任务完成时间 | P95 < 120 秒 |
| 系统 | 一键启动到可用 | < 120 秒 |
| 开源 | 外部复现 | 3 人中至少 2 人在 60 分钟内完成 |

### 正式实验

| 版本 | 定义 |
|---|---|
| A | 固定脚本 + 普通状态机 |
| B | Agent，关闭 WorldState 验证和重新观察 |
| C | 完整系统：Agent + WorldState + 验证 + 恢复 + 表达 |

固定 30 个相同 seed 场景：正常 6、遮挡/低置信度 6、目标移动 6、路径阻挡 6、抓取失败 3、服务/MCU 超时 3。

每个版本跑相同 30 个场景，共 **90 次**。必须报告成功率、恢复率、误判完成、安全违规、人工介入、任务时间、P50/P95 和失败样例。

仿真工程师在运行前冻结 manifest、seed、超时和故障类型；Agent C 在运行后审核感知和 Agent 结果；世界模型工程师重算状态与指标；项目负责人最后批准结果。

---

## 7. 发布硬门槛

以下任一失败，不发布正式 `v0.1.0`：

- False Completion 不为 0；
- 出现碰撞、限位穿透或 Agent 越权控制；
- 固定脚本需要云 API 才能运行；
- 30 个场景、seed 或故障注入规则没有版本化；
- 关键事件不完整或任务无法回放；
- 90 次实验没有原始数据；
- README 未说明限制和失败案例；
- 外部人员无法按文档启动。

---

## 8. 你每天只需要盯住六件事

1. 今天是否有端到端运行结果，而不只是模块代码；
2. 当前唯一阻塞是谁在处理，多久解决；
3. 是否有人增加了未批准的功能或第二套技术；
4. 日志、指标、回放和失败样例是否真实保存；
5. 固定脚本是否仍能在断网条件下运行；
6. 同一失败是否已经变成回归测试。
7. 仿真场景是否能按相同 seed 重建，失败是否有对应 manifest 和日志。

本计划完成的标志不是“机器人动过一次”，而是另一名开发者能在另一台电脑启动它、重复任务、看到失败、重算指标，并确认机器人没有无证据地宣布成功。
