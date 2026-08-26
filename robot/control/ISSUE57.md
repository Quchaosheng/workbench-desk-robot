# Issue #57：确定性轨迹安全预检（Motion 私有实施计划）

> 仅供 Motion Owner 和本地开发使用，不是 GitHub Issue、PR 描述或公开承诺。
> 本文对应官方 `#57 feat(motion): add deterministic trajectory safety preflight`。

## 1. 状态与开工门

- #57 官方 Issue 仍为 `open`，没有已合入的 #57 实现。
- PR #149 已合入并关闭 #116；它替代了已关闭、未合入的 PR #117。
- 本 checkout 已同步远端最新 `main` `1044c843`（包含 PR #149 merge `d283bb9`），并将独立分支 `feat/57-deterministic-preflight` rebase 到该提交。原 `feat/motion-57-trajectory-preflight` worktree 的 `da7c97c` 是旧 #117 内容，不能继续使用。
- #57 代码只允许写 `robot/control/**`，不修改 `interfaces/**`、`libs/contracts/**`、`services/**` 或 `firmware/**`。实现前须通过 [`docs/task_packets/motion-057-trajectory-preflight.json`](../docs/task_packets/motion-057-trajectory-preflight.json)；阈值、reason code 和 accepted-snapshot 边界已在 Packet 中冻结。

完成定义：ROS-free 预检内核、稳定拒绝码、不可变通过快照、确定性 canonical bytes/SHA-256 和全套纯 Python 测试均完成；不包含任何控制器下发或物理执行声明。

## 2. 目标与非目标

### 目标

对每条待执行关节轨迹执行同一套 fail-closed 检查：

1. 关节集合和顺序必须与 `config/arm.yaml` 完全一致。
2. 拒绝非有限/非法数组、非法或非单调时间、超过总时长、位置/速度/effort 越限和起始状态跳变。
3. 返回可冻结的机器 reason code；人类消息不能成为契约。
4. 通过后复制为不可变 normalized snapshot，并生成跨输入表示一致的 canonical bytes 与 SHA-256。
5. 记录 policy、effective limits 和 context hash，说明“在哪套规则下通过”。

### 非目标

- 不导入 ROS，不调用 MoveIt、`ros2_control`、action server 或 controller。
- 不实现 #52 的 SemanticAction/GRASP/PLACE/STOP adapter、EvidenceSink、ActionResult 或执行期监控。
- 不做 JTC spline 峰值、连续碰撞证明、运行时越限监测、安全停车或真机验证。
- 不通过排序、补点、裁剪、clamp 或修复来让非法输入通过。

后续边界：#52 必须把 `AcceptedTrajectory` 作为唯一可执行输入；C3b 再做 bounded-resolution sampled collision gate。运行时 fresh-state/scene 的 TOCTOU 重检属于下游执行集成，不伪装成 #57 已完成。

## 3. 以 #149 为基线的缺口清单

同步 #149 后逐项核对，不能把旧 #117 当作权威：

- 已有/应保留：厂商 UR5e hard limits、hardware override 只能收紧、重复/缺失/未知/partial joint 拒绝、NaN/Inf 和数组检查、位置/速度/effort 检查、时间单调性、t=0 当前状态锚点、平均 segment velocity、`Violation | None`、无 mutation/clamp/dispatch。
- #57 补齐：同集合错序拒绝；最大总时长；独立最大 start-state delta；冻结 `ReasonCode`；immutable accepted snapshot；canonical bytes/SHA-256；policy/effective-limits/context hash；每个关节和时间边界的系统测试。
- `phase2_probe` 当前用 `asdict(Violation)`；必须保持六字段 evidence 形状：`kind/message/joint/value/bound/point_index`。
- 不引入 Hypothesis 作为默认依赖；优先使用 pytest 参数化、固定生成器和每关节循环。只有证明现有测试无法覆盖时，才单独评审新依赖。

## 4. 冻结的 API 与数据模型

保留旧接口，新增唯一正式入口：

```python
def check_trajectory(
    traj, current_joint_positions, limits=None, *,
    limit_epsilon=DEFAULT_LIMIT_EPSILON,
) -> Violation | None

def preflight_trajectory(
    traj, current_joint_positions, *,
    context: PreflightContext,
) -> AcceptedTrajectory | Violation
```

`preflight_trajectory` 是唯一实现；`check_trajectory` 只是兼容 wrapper。wrapper 必须保留签名、参数位置、`None`/`Violation` 返回约定和 `asdict` 六字段。传入 `limits` 时其 mapping 插入顺序提供旧 API 的 expected order；不传时从 `arm.yaml` 读取。wrapper 的 `limit_epsilon` 继续权威；时长和 start delta 来自已验证 policy。新入口只使用不可变 `PreflightContext`。

建议的 frozen 类型：

```python
class ReasonCode(StrEnum): ...


@dataclass(frozen=True)
class PreflightPolicy:
    version: str
    limit_epsilon: float
    max_duration_s: float
    max_start_state_delta_rad: float


@dataclass(frozen=True)
class PreflightContext:
    expected_joint_names: tuple[str, ...]
    effective_limits: tuple[tuple[str, JointLimit], ...]
    policy: PreflightPolicy
    effective_limits_sha256: str
    context_sha256: str


@dataclass(frozen=True)
class Violation:  # kind 仍是真实字段
    kind: ReasonCode
    message: str
    joint: str | None = None
    value: float | None = None
    bound: float | None = None
    point_index: int | None = None
```

`NormalizedPoint`、`NormalizedTrajectory`、`AcceptedTrajectory` 也必须深度不可变（tuple 和标量，不把 dict 藏在 frozen dataclass 里）。`AcceptedTrajectory` 用 `init=False`，只由模块私有 factory 创建，包含 snapshot、canonical bytes、`trajectory_sha256`、`policy_version`、`effective_limits_sha256`、`context_sha256`。新代码可有只读 `Violation.code` alias，但不得新增顶层 dataclass 字段，避免破坏 `phase2_probe` schema。

## 5. Policy、limits 与 context

新增 `config/trajectory_preflight.yaml`，初始值先作为 Motion Owner 决策冻结：

```yaml
trajectory_preflight:
  version: "1"
  limit_epsilon: 1.0e-6
  max_duration_s: 30.0
  max_start_state_delta_rad: 0.05
```

- epsilon 只向内收紧 hard limit；duration/start delta 不留代码魔数。
- policy 缺字段、未知字段、bool、NaN/Inf、非正 duration/delta 或负 epsilon，均在 readiness/context 构建时 fail closed。
- `build_preflight_context(...)` 可显式注入 policy、expected joints、hard limits、override limits；显式参数完整替换对应文件来源，不跨来源偷偷补值。
- expected joints 与 effective limits 集合必须完全相等；effective limits 按 expected tuple 排序后存储。
- 配置失败抛 `PreflightConfigurationError`，只允许 `invalid_policy`/`invalid_limits`，不伪装成普通轨迹 `Violation`。
- `effective_limits_sha256` 对关节顺序、min/max position、max velocity、max effort 做 canonical hash；`context_sha256` 覆盖 schema version、policy、expected tuple 和 limits hash。context 在一次 readiness 生命周期内不可变。

## 6. Reason code 与固定校验顺序

以下旧码含义不能改名或复用：`joint_names`、`current_state`、`points`、`array_length`、`non_finite`、`time`、`current_position`、`position`、`velocity`、`effort`、`initial_position`、`segment_velocity`。

新增码：`joint_order_mismatch`、`timestamp_malformed`、`duration_exceeded`、`start_state_discontinuity`。配置错误码 `invalid_policy`、`invalid_limits` 独立存在。

已构建合法 context 后，首个错误顺序固定为：

1. joint names：空、重复、集合不符、同集合错序。
2. current state：集合、可解析/有限性、当前位置限位。
3. points 和所有数组长度。
4. 数值有限性；时间形态解析。
5. 整数纳秒时间：负值、严格递增、总时长上限。
6. 每点 position/velocity/effort 限位。
7. start-state discontinuity。
8. current→first 与 point→point 平均速度。
9. canonicalization/hash。

同一输入多次运行必须得到相同 code 和结构字段；message 可读但不参与机器判定。

## 7. 时间、起点与 canonicalization 规则

- ROS-like/mapping duration 必须有整数且非 bool 的 `sec`、`nanosec`；`-2^31 <= sec <= 2^31-1`、`0 <= nanosec < 1e9`。
- scalar 秒数接受非 bool int/float；有限且用 `Decimal(str(value))` 转整数纳秒，亚纳秒值返回 `timestamp_malformed`；`-0.0` 归一化为 0 ns。
- 缺失/形态错误为 `timestamp_malformed`；可表示但负或非递增仍使用兼容码 `time`。
- 所有比较、snapshot 和 hash 只用整数纳秒；末点超过 policy 上限返回 `duration_exceeded`。
- 首点 t=0 仅作 current-state anchor，位置必须在 epsilon 内相等，不计零时长运动段；首点 t>0 仍检查 start delta 和平均速度。
- 通过后输出 UTF-8 紧凑、排序键 JSON；时间为整数 ns；可选空数组统一为 `[]`；有限浮点统一用 `float.hex()` 字符串。`trajectory_sha256` 为 `sha256:<lowercase-hex>`。
- plain mapping 与 ROS-like 等价对象必须逐字节同 hash；任意关节、点、时间或可选数组变化必须改变 hash。policy/context hash 单独记录，不混入 trajectory hash。

## 8. 文件与测试计划

预计只改 `robot/control/**`（实现前以 Task Packet 冻结）：

| 文件 | 计划 |
|---|---|
| `workbench_motion/joint_limits.py` | context/policy、reason codes、统一 preflight、精确时间、duration/start delta、snapshot/canonical hash；保留 wrapper |
| `workbench_motion/config/trajectory_preflight.yaml` | 版本化 policy（安装路径需验证） |
| `workbench_motion/phase2_probe.py` | 显式序列化六个旧字段 |
| `workbench_motion/test/test_joint_limits.py` | #149 回归和兼容性 |
| `workbench_motion/test/test_trajectory_preflight.py` | #57 边界、属性、hash、immutability |
| `README.md` | 纯逻辑 gate 与下游边界 |

测试必须覆盖：

- `arm.yaml` 每个关节的 position/velocity 上下界、epsilon 内外边界；任意非 identity permutation。
- duration 等于/超过上限；重复、逆序、负、亚纳秒、sec/nanosec 越界、bool、NaN/Inf。
- start delta 等于/超过阈值；t=0 anchor；平均 segment velocity。
- 输入成功/失败均不变；accepted 后修改原输入不影响 snapshot/bytes/hash；snapshot tuple/frozen 不可写。
- mapping/ROS-like canonicalization 一致；重复运行字节一致；任一内容变化 hash 改变。
- `asdict(Violation)` 和 `validator_violation` JSON 精确六键，legacy kind 字符串不漂移。
- policy/limits 错误为稳定 configuration error，不产生 trajectory violation。

不依赖 ROS、Gazebo、网络或新增 property-testing 插件。

## 9. 实施顺序、证据与命令

1. 在干净分支同步 #149，运行现有 Motion 测试并记录 commit。
2. 建/审核 Task Packet，冻结 policy、reason code、context/accepted 边界。
3. 先实现 context/policy 和 normalized parser，再迁移现有 validator 为单一内核。
4. 加入 duration/start delta、canonicalizer/hash 和 probe schema 兼容。
5. 先跑 Motion 单测，再跑根仓库 required checks；失败即修复或停止，不以文档替代结果。

建议证据命令：

```bash
make task-check PACKET=docs/task_packets/motion-057-trajectory-preflight.json
uv run --directory robot/control pytest -q
make test
make contract
make scenario-check
make context-check
```

证据至少包含：Task Packet 校验输出、测试摘要、reason-code/边界/hash 结果、policy 文件和有效 limits/context hash、commit 与 `git_dirty`。本 Issue 不启动 ROS/Gazebo，也不提交物理成功证据。

## 10. 下游交接与停止条件

交给 #52 的接口要求：执行 port 只接受 `AcceptedTrajectory`；发送前从其 snapshot materialize，并校验 trajectory/context hash 与当前 readiness context。原始可变轨迹不得越过该边界。#52 负责 runtime state/scene TOCTOU 重检、零下发和 ActionResult；#59 负责拒绝到 failed dispatch 的编排证明；C3b 负责 sampled collision gate。上述不算 #57 完成项。

立即停止并重新评审的情况：

- #149 基线发生不兼容变化，或发现必须并存第二套 validator/limit/tolerance/hash 语义。
- 需要修改 interfaces、contracts、services、firmware，或接入 ROS/controller/dispatcher。
- 无法从 `arm.yaml` 和受控 vendor 配置得到关节/limits；不得写硬编码备用值。
- Motion Owner 尚未批准阈值、reason code 或 accepted-snapshot 执行边界。
- 任何实现尝试重排、补点、clamp、repair、重新读取可变原输入或产生执行副作用。

只有上述门和命令证据全部满足，才可把 #57 标为实现完成；在此之前状态仍是 plan/implementation in progress。
