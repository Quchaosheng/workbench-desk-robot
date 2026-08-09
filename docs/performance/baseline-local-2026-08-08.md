# 本机性能基线（2026-08-08）

## 环境

- Windows 11 / Docker Desktop Linux VM
- Docker Engine `29.6.2`、Compose `v5.3.1`
- x86_64、32 vCPU、约 7.6 GiB Docker 内存
- 镜像运行时：Ubuntu 24.04、Python 3.12、无 CUDA

## 启动阶段

由 `tools/scripts/benchmark_startup.py` 生成，分别使用独立 Compose project 和端口：

| 模式 | 构建 | 启动到 `/healthz` | 启动到 `/readyz` | clone-to-ready | 目标 |
|---|---:|---:|---:|---:|---:|
| 标准缓存 | 6.62s | 0.93s | 0.96s | 7.58s | <120s |
| `--no-cache` | 100.05s | 0.52s | 0.55s | 100.60s | <120s |

这是单机默认 dashboard/full-stack（不含 Gazebo）的可复现范围；它不是三位外部参与者的冷启动结果。

## 仿真阶段时延

`demo_scripted.py --iterations 30` 的 `source=simulation` 日志由同一分析器汇总：

| 阶段 | P50 | P95 |
|---|---:|---:|
| planning | 0.070ms | 0.094ms |
| dispatch | 0.002ms | 0.003ms |
| event_store | 8.197ms | 10.132ms |
| state_reduction | 0.059ms | 0.078ms |
| verification | 0.419ms | 0.568ms |
| end_to_end | 8.897ms | 10.835ms |

这些是软件/脚本流水线阶段，不是物理抓取或真实相机延迟。

## 资源基线

dashboard 容器 5 次、间隔 0.5s 的 `docker stats`：CPU P95 `2.12%`，内存最大 `14.0 MiB`（`14,701,036` bytes）。采样接口是 `/api/runs`，容器名称和原始样本保存在被忽略的 `runs/performance/resources.json`。

## 本地模型

Ollama `qwen2.5:0.5b`（397MB）在 CPU 上完成一次受限路由约 `1.3–2.7s`。模型只返回五类任务路由，确定性 builder 才生成 `TaskGraph`；`model-runtime` 网络为 Docker `internal`。模型权重许可仍需在正式发布前由负责人审核。
