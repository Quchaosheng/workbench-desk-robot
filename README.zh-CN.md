# workbench-1

一个会验证任务完成的桌面机械臂,而不是假设完成了。

[English](README.md) · [简体中文](README.zh-CN.md)

---

## 核心贡献（系统与内核工程）

这个项目把系统集成、运行时架构和任务验证放在同一条可复现链路中，核心工程工作包括：

**事件存储与回放**
- 仅追加事件日志，可从检查点进行确定性回放
- 按明确契约校验带版本的事件 schema
- 根据事件流重建状态，不依赖外部快照才能得到正确结果

**契约驱动架构**
- 由 `interfaces/json_schema/` 中的 11 个 JSON schema 定义模块边界
- 在入口处拒绝不符合契约的请求，默认失败关闭
- 通过对应的 Pydantic 模型和契约检查防止生产端与消费端漂移

**证据优先验证**
- 用 `confirmed`、`refuted`、`insufficient_evidence` 三值逻辑代替布尔成功
- 验证结果携带结构化证据引用，而不只是通过/失败标志
- 同一 seed 产生同一场景和事件序列，支持确定性评测

**系统可靠性**
- 控制端与仿真端分机部署，包含 readiness 探针和对端可用性检查
- 结构化日志、健康端点、SBOM 工作流和带哈希绑定的硬件证据
- 可复现的启动 P50/P95、CPU/RAM 分析和容器冒烟测试

**面向硬件的基础设施**
- Linux `wbcan` SocketCAN 内核模块，包含构建、checkpatch 和特权故障测试路径
- 面向 host、QEMU 和 CH32V307 HAL 的 RISC-V 安全 MCU 分层脚手架
- 覆盖采购、制造、质量、合规和现场验证的失败关闭式硬件发布门禁

**尚未包含：** Gazebo 世界、MoveIt 抓取放置、真实相机（OpenCV + AprilTag）和 Gazebo 实测评测结果仍待完成。仓库中的 fixture 是脚本化链路测试，不是真机证据。

**权限边界：** 模型只能路由到受限语义动作；关节控制、速度和急停都留在模型无法触达的受信代码中。

---

## 问题

告诉机器人把模块放进托盘。它动了,报告成功,模块在地上。

函数返回 OK,机器人以为成功了。但任务失败了。

多数演示分不清这两件事。这个试图分清。

---

## 它做什么

当前可运行路径是确定性的脚本化桌面运行时。红块任务保留为冻结回归基线;v0.2 评测还覆盖三件齐套、多工件检验、清障恢复和证据优先的快递入库分拣。你给一个边界明确的自然语言目标,它:

- 观察场景中的每个必需实体
- 把目标路由为受限语义计划(`observe`、`grasp`、`place`)
- 通过脚本化运行时执行语义动作（MoveIt 集成仍待完成）
- **事后检查**:全部目标条件是否满足,齐套托盘里是否没有多余零件?
- 如果拿不准(相机跟丢、置信度低、证据过期),说"我无法确认"而不是瞎猜
- 对可恢复故障重新观测并重试,同时在回放中保留首次失败

模型选目标,但发不出关节位置或速度。这个边界是代码强制的,不是提示词。

---

## 现在到哪了

**能用:**
- 契约定义(11 个 JSON schema)
- 事件库 + 回放
- 五类任务的模板规划器(不需要模型)
- 放置、精确齐套、检验置信度、工作区清障以及到件清单对账快递路由的专用验证器
- 多实体只读看板、按序回放、恢复历史与证据查看
- 断网容器、健康端点、统一 JSON 日志、镜像/SBOM 工作流
- localhost-only Ollama Runner: 模型只做五类任务路由,语义动作由受信模板生成
- 启动、阶段 P50/P95、CPU/RAM 和真机日志哈希校验工具
- 控制端/仿真端分机 Compose 拓扑,远端不可达时 readiness 失败
- Linux `wbcan` SocketCAN 内核模块源码及 CI 构建/checkpatch 检查；运行时故障测试需要特权 Linux 主机
- RISC-V 安全 MCU 的 host/QEMU/开发板 HAL 脚手架，CI 会保留明确的未完成状态
- 可审计的硬件工程包和失败关闭式发布报告；当前报告因缺少外部证据仍为 `RELEASE_BLOCKED`
- MkDocs 操作手册，覆盖安装、日常操作、维护、故障排查和 90 分钟演示
- 12 个冻结 v0.1 基线与 24 个扩展 v0.2 场景,含 seed 确定性检查
- 五类共 50 条黄金任务请求,另有 26 条必须失败关闭的危险请求
- CI 跑 lint、契约、评测 fixture、断网 demo 与容器 smoke test

**还没做:**
- Gazebo 世界
- MoveIt 抓取放置
- 真实相机(OpenCV + AprilTag)
- Gazebo 真实评测结果(仓库内运行数据明确标为脚本化 fixture)
- 实物制造、供应商报价、实验室认证和现场验证证据

真实相机、Gazebo 和真实硬件仍需外部设备；仓库内不会把模拟日志伪装成真机证据。

---

## 跑起来

Ubuntu 24.04 或 WSL2,Python 3.12,不需要显卡。

```bash
git clone https://github.com/Quchaosheng/workbench-desk-robot.git
cd workbench-desk-robot
make bootstrap
make demo-scripted
make performance-test
```

`demo-scripted` 跑完整条链(观测 → 规划 → 验证 → 回放),纯 Python,不启动仿真器。反馈快。

其他命令:

```bash
make test             # 单元 + 契约测试
make lint             # ruff 检查
make check            # 核心 Python 检查和离线演示
make docs             # 严格模式构建 MkDocs
```

Gazebo 集成就位之后:

```bash
make sim              # 启动世界 + 机械臂 + 相机
make demo             # 完整运行,固定脚本
```

任务看板不需要网络或 GPU:

```bash
make dashboard
# 打开 http://127.0.0.1:8080
```

容器启动:

```bash
docker compose up --build
curl http://127.0.0.1:8080/healthz
```

本地模型需要先 provision 一次模型卷，然后运行时只连 internal Docker 网络：

```bash
docker compose --profile model-bootstrap run --rm model-bootstrap
docker compose --profile model up -d
docker compose run --rm dashboard python tools/scripts/local_runner.py \
  --provider ollama --endpoint http://model:11434 --allow-host model \
  --goal "处理 intake 区已经到达的快递"
```

阶段性能和分机部署见 [`docs/performance/README.md`](docs/performance/README.md) 与
[`docs/deployment/multi-host.md`](docs/deployment/multi-host.md)。
操作员和维护人员文档从 [`docs/user-guide/index.md`](docs/user-guide/index.md) 开始。
硬件发布状态可通过以下命令重新生成：

```bash
python hardware/release/tools/check_release_readiness.py
```

报告校验成功只表示仓库内证据自洽，不代表外部阻断项已经解除，也不代表实物硬件可以发布。

看板 API 只读。所有 HTTP 写方法都返回 `405`;这个服务里没有 ROS、运动、MCU 或急停发布器。

---

## 三个重要的事

**1. 动作结果把"发出"和"确认"拆开**

多数代码把写成功当成动作成功。这里它们是分开的:

```python
ActionResult(
    dispatch_state="sent",  # 帧离开了主机
    device_state="unconfirmed",  # 设备还没回复
    outcome="timeout",
)
```

**2. 验证是三值的,不是布尔**

```python
status = "confirmed"  # 目标达成,这是证据
status = "refuted"  # 目标确实没达成
status = "insufficient_evidence"  # 判断不了,这是缺的东西
```

布尔值会迫使系统在不知道的时候猜。三个状态让它能说"我不知道"。

**3. 模型永远动不了电机**

它从六个动作里挑:`observe`、`grasp`、`place`、`ask_confirm`、`express`、`stop`。

关节角、速度、急停在结构上就不在它能碰的范围。如果它返回列表外的东西,请求直接失败。

---

## 怎么扩展

单模块演示只是回归下限,不是能力上限。当前脚本评测已经在同一组契约后覆盖精确三件齐套、纯证据检验和有序清障恢复。

**加任务:**写一个新验证器。系统问"断言 X 成立吗?" —— 它不关心 X 是"模块在托盘里"还是"线缆就位"还是"六颗螺丝都在"。

**加传感器:**任何能产出 `observation.schema.json` 的都是传感器。力传感器、深度相机、条码枪 —— 世界模型不关心是哪种。

**换机械臂:**Motion 消费 `semantic_action`,产出 `action_result`。把 Panda 换成 UR5e 或真臂,上面的东西一行不改。

**加规划器:**模板规划器和 LLM 规划器已经在 `ModelProvider` 后面了。搜索式或学习式规划器是第三个实现。

规则:新能力以"已有契约后面的新实现"形式出现。如果你要改 schema,先讨论。

---

## 路线图

v0.1 故意做得小,是为了先把验证层证明对,再往上叠东西。v0.2 扩大离线评测范围,但不会把脚本证据冒充成仿真器或真机证据。

- **v0.1** — 冻结的一条臂、一个任务回归基线
- **v0.2** — 五类任务与更细的失败处理(脚本链路已实现,Gazebo 待接入)
- **v0.3** — 真实硬件,契约不变
- **更远** — 移动底盘(验证器能推广到导航目标)、多臂

两条永远不变:
- 模型永远不控制关节/速度/急停/完成判定
- 声称成功必须带证据

---

## 指标

v0.1 要达到的数字。标 **0** 的是发布阻断项。

| 安全 | 目标 |
|---|---|
| 误判完成(报告完成但实际没完成) | **0** |
| 碰撞 / 关节限位穿透 | **0** |
| 模型发出原始关节控制 | **0** |

| 任务 | 目标 |
|---|---|
| 抓取成功率(脚本化,无故障) | ≥ 90% |
| 已验证任务完成率 | ≥ 80% |
| 首次失败后恢复成功率 | ≥ 70% |
| 任务耗时 P95 | < 120 秒 |
| 评测任务族 | ≥ 5 类 |
| 复杂任务占比 | ≥ 50% |
| 目标条件覆盖率 | 100% |

| 证据 | 目标 |
|---|---|
| 同一事件日志 → 同一状态 | 100% |
| 验证结论携带证据引用 | 100% |
| 同一 seed → 同一场景配置 | 100% |

| 系统 | 目标 |
|---|---|
| clone 到跑起 demo(无模型) | < 90 秒 |
| clone 到跑起 demo(全栈) | < 180 秒 |
| 是否需要显卡 | 不需要 |

---

## 这个项目证明了什么、没证明什么

纯仿真。把边界说清楚本身就是重点的一部分。

| 这里证明了 | 这里没证明 |
|---|---|
| 软件契约、事件完整性、回放 | CAN 电气层、总线时序 |
| 状态机转移 | 物理执行器动力学 |
| 验证逻辑、证据链 | 传感器噪声、光照漂移 |
| Gazebo 里的抓取成功率 | 真实夹爪上的抓取成功率 |

软件安全停止 ≠ 硬件急停。Gazebo 的数字不能不经重新验证就迁移到真机。

脚本化评测 fixture 也不能证明 Gazebo 性能。它只验证事件顺序、证据覆盖、回放和报告链路,并始终标记为 `release_eligible: false`。见[已记录的 fixture 失败案例](docs/evaluation/failure-cases.md)和[容器运行手册](docs/deployment/container.md)。

快递处理明确限定为桌面入库区内已经放置的包裹:系统先扫描整批,只有标签已核验且外观完好的包裹进入取件架;外观异常件先于单纯标签异常件进入隔离区。容量预检会在任何搬运动作前拒绝放不下的整批任务,避免执行到一半才溢出。当前设备没有移动底盘、电梯或快递柜访问能力,因此“下楼/去快递柜取件”会失败关闭,不会伪造已取件证据。

---

## 参与进来

从这里开始:

1. 读 `AGENTS.md`(工作规则,很短)
2. 读你要动的边界的 schema(`interfaces/json_schema/`)
3. 开个 issue,说你要做哪个模块、满足哪个契约
4. 一个 PR 一个模块

完整流程见 `CONTRIBUTING.md`,架构见 `docs/architecture/system.md`。

六条规则:
- `interfaces/` 是模块边界的唯一真相来源
- 规划器只发语义动作,永不发关节位置
- 世界模型决定状态是什么意思、任务算不算完成
- 场景/seed/故障在评测前冻结
- 成功声明需要事件和可复现证据
- AI 工具不合并、不发布、不改安全配置、不判定完成

"做完"的意思:已合并且 CI 绿、有能抓住回归的测试、有别人能跑的命令、有证据引用。

本项目采用 AI 辅助开发。契约、不变量和合并决定由人拥有。如果你贡献一个模块,你应该能解释其中任意一个文件。

---

## 许可证

Apache-2.0 —— 见 [LICENSE](LICENSE) 与 [NOTICE](NOTICE)。  
第三方资产许可证见 [THIRD_PARTY_REVIEW.md](THIRD_PARTY_REVIEW.md)。
