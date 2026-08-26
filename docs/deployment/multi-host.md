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
export WORKBENCH_EVENT_SOURCE_URL=http://10.20.30.40:8090
export WORKBENCH_EVENT_SOURCE_ALLOWLIST=10.20.30.40/32
docker compose -f deploy/multi-host/compose.controller.yaml up -d
curl --fail http://127.0.0.1:8080/readyz
```

控制机必须同时设置 `WORKBENCH_EVENT_SOURCE_URL` 和 `WORKBENCH_EVENT_SOURCE_ALLOWLIST`。后者是以逗号分隔的字面 IP 地址或 CIDR 网段列表，例如 `10.20.30.40/32,10.20.31.0/24`；allow-list 条目不能使用主机名。若事件源 URL 使用主机名，则它解析出的每个地址都必须落在这些网段内。缺失、空白或格式错误的 allow-list 会保持非回环事件源为未就绪状态。

示例中的 `10.20.30.40` 应替换为仿真机的实际地址。URL 和 allow-list 都是非敏感部署配置；不要在 URL 中放入用户名、密码、令牌或其他凭据。

控制端的 `/readyz` 会检查仿真端；仿真端宕机、返回错误或事件源不合法时，控制端明确返回 `503 not_ready`。两个 Compose 项目没有共享卷，便于在不同主机运行。

## 同机烟测

```bash
docker compose -f deploy/multi-host/compose.sim.yaml up -d
$env:WORKBENCH_EVENT_SOURCE_URL = "http://host.docker.internal:8090"
$env:WORKBENCH_EVENT_SOURCE_ALLOWLIST = "192.168.65.0/24"
docker compose -f deploy/multi-host/compose.controller.yaml up -d
curl --fail http://127.0.0.1:8080/readyz
```

同机示例面向 Docker Desktop；运行前应确认 `host.docker.internal` 解析到的字面 IP，并把 `192.168.65.0/24` 替换成覆盖该地址的最小 IP 或 CIDR。这个烟测只证明网络边界和故障传播；它不替代两台物理机器的网络延迟、丢包和时钟同步验收。
