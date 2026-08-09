# 分机部署

E13 的边界是把控制端的只读投影与仿真事件源分开。两台机器只需要互相访问一个 HTTP 地址；控制端不挂载仿真数据目录，也不获得机器人控制权限。

## 仿真机

```bash
export WORKBENCH_IMAGE=ghcr.io/quchaosheng/workbench-desk-robot:v0.3.0
docker compose -f deploy/multi-host/compose.sim.yaml up -d
curl --fail http://0.0.0.0:8090/readyz
```

将 `8090` 端口限制在控制机网段，按实际防火墙规则替换示例地址。

## 控制机

```bash
export WORKBENCH_IMAGE=ghcr.io/quchaosheng/workbench-desk-robot:v0.3.0
export WORKBENCH_EVENT_SOURCE_URL=http://SIM_HOST:8090
docker compose -f deploy/multi-host/compose.controller.yaml up -d
curl --fail http://127.0.0.1:8080/readyz
```

控制端的 `/readyz` 会检查仿真端；仿真端宕机、返回错误或事件源不合法时，控制端明确返回 `503 not_ready`。两个 Compose 项目没有共享卷，便于在不同主机运行。

## 同机烟测

```bash
docker compose -f deploy/multi-host/compose.sim.yaml up -d
$env:WORKBENCH_EVENT_SOURCE_URL = "http://host.docker.internal:8090"
docker compose -f deploy/multi-host/compose.controller.yaml up -d
curl --fail http://127.0.0.1:8080/readyz
```

同机测试只证明网络边界和故障传播；它不替代两台物理机器的网络延迟、丢包和时钟同步验收。
