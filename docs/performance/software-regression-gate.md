# 软件性能回归门禁

LINUX-APP11 使用同一环境中的基线报告和当前报告进行比较。门禁同时检查绝对预算
和相对退化，任何一项超限都返回非零退出码。它只接受本地软件报告，不接受或推断
真实硬件性能。

## 采集基线和当前报告

在同一主机、Python 版本和 Compose cache 模式下分别采集基线与当前结果：

```bash
python tools/scripts/benchmark_startup.py --output runs/performance/baseline/startup.json
python tools/scripts/benchmark_resources.py \
  --project workbench-startup-benchmark \
  --output runs/performance/baseline/resources.json
python tools/scripts/demo_scripted.py \
  --iterations 30 \
  --telemetry runs/performance/baseline/simulation.jsonl
python tools/scripts/analyze_telemetry.py \
  runs/performance/baseline/simulation.jsonl \
  --output runs/performance/baseline/telemetry.json
```

在代码变更后用相同命令写入 `runs/performance/current/`。资源和 telemetry 报告
至少需要 5 个样本；正式比较建议保留现有的 30 次 telemetry 运行。

## 执行门禁

```bash
python tools/scripts/performance_regression.py \
  --policy docs/performance/software-regression-policy-v1.json \
  --baseline-startup runs/performance/baseline/startup.json \
  --current-startup runs/performance/current/startup.json \
  --baseline-resources runs/performance/baseline/resources.json \
  --current-resources runs/performance/current/resources.json \
  --baseline-telemetry runs/performance/baseline/telemetry.json \
  --current-telemetry runs/performance/current/telemetry.json \
  --output runs/performance/regression.json
```

输出中的每项检查包含基线值、当前值、绝对上限和允许的相对退化上限。以下情况
会失败关闭：

- 报告缺失、schema 版本错误或包含 `NaN`/`Infinity`；
- 基线与当前的操作系统、Python 版本或启动 cache 模式不一致；
- 样本数量不足或 P50/P95/max 顺序错误；
- telemetry 含有 `hardware` 来源；
- 当前值超过绝对预算或相对退化上限。

策略中的 2 GiB 和 2 CPU 是任务书的软件容器预算，启动和流水线阈值是开发环境
门禁。结果始终标记为 `local_software`，并明确保留
`target_hardware_measurement: NOT_EXECUTED`。目标板、真实 ROS/Gazebo 和物理机器人
必须重新建立各自的可比基线，不能沿用本门禁作为发布证据。
