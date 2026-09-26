# DeepTutor 部署包（港大 HKUDS）

让飞书自建应用 **`003-DeepTutor`**（App ID `cli_aaec033c25b89ce9`）真正跑起来。

上游项目：[HKUDS/DeepTutor](https://github.com/HKUDS/DeepTutor)（Apache-2.0）· 官方镜像 `ghcr.io/hkuds/deeptutor:latest`

---

## 为什么是这个方案

DeepTutor **原生自带飞书通道**（`deeptutor/partners/channels/feishu.py`，基于 `lark-oapi` 的 **WebSocket 长连接**），
而且镜像的 `requirements.txt` 已经包含 `requirements/partners.txt`，**lark-oapi 开箱即用**。

所以：

- ❌ 不需要自己写飞书桥
- ❌ 不需要公网回调地址 / 入站端口（长连接是出站）
- ✅ 只需要把容器跑起来 + 建一个 Partner 并在它的 Channels 里填飞书凭证

## 架构

```
飞书 App (003-DeepTutor)
   │  ① WebSocket 长连接（出站，无需公网 IP）
   ▼
VPS 148.230.88.192 (Ubuntu 24.04 + Coolify)
   └─ docker compose stack: deeptutor
        ├─ init        一次性写入 model_catalog.json / (可选) auth.json，跑完即退
        ├─ redis       上游要求的会话协调 sidecar（仅内网）
        └─ deeptutor   supervisord 同时拉起
                        ├─ backend  uvicorn :8001   （API）
                        └─ frontend node    :3782   （Next.js，唯一对外端口）
```

对外**只暴露 3782**。容器内的 Next 代理会把 `/api/*`、`/ws/*` 转发给同容器后端 8001，
因此不需要配置 API base；**也不要把 8001 暴露到公网** —— 未启用登录时 `/api/partners/*` 会解析成本地管理员。

## Coolify 里要配的环境变量

| 变量 | 必填 | 说明 |
| :--- | :--- | :--- |
| `DEEPSEEK_API_KEY` | ✅ | 模型 key（`${VAR:?}` 已标记为必填） |
| `DEEPSEEK_BASE_URL` | | 默认 `https://api.deepseek.com` |
| `DEEPSEEK_MODEL` | | 默认 `deepseek-chat` |
| `DEEPTUTOR_ADMIN_USER` | | 登录用户名（默认 `admin`） |
| `DEEPTUTOR_ADMIN_PASSWORD` | | 开启登录时必须给 |
| `DEEPTUTOR_AUTH_ENABLED` | | `true` 才会写 `auth.json` 启用登录 |
| `DEEPTUTOR_SEED_FORCE` | | `1` = 强制重写上面的配置文件 |
| `SERVICE_FQDN_DEEPTUTOR_3782` | | Coolify 自动生成/覆盖，即对外域名 |
| `TZ` | | 默认 `Asia/Shanghai` |

> 配置不在环境变量里！DeepTutor 的运行时设置全部在数据卷的 `data/user/settings/*.json`，
> entrypoint 每次启动会**主动 unset** `BACKEND_PORT` / `AUTH_ENABLED` / `NEXT_PUBLIC_API_BASE` 等，
> 再从 JSON 重新导出。所以端口、登录、API base 都得改 JSON（本包的 `init` 容器就是在做这件事）。

## 部署后怎么接飞书

1. 浏览器打开 Coolify 分配的域名，确认 UI 出得来（`/health/ready` 应为 200）。
2. 建 Partner（也可用 API）：

   ```bash
   curl -X POST "$DOMAIN/api/partners" -H 'Content-Type: application/json' -d '{
     "name": "DeepTutor",
     "channels": {
       "feishu": {
         "enabled": true,
         "app_id": "cli_aaec033c25b89ce9",
         "app_secret": "<003 的 App Secret>",
         "domain": "feishu",
         "group_policy": "mention"
       }
     },
     "start": true
   }'
   ```

3. 校验通道状态：

   ```bash
   curl "$DOMAIN/api/partners/deeptutor/channels/status"
   ```

4. 飞书里给 `003-DeepTutor` 发一句话 —— 应能收到回复。

> **飞书后台必须确认**：`003-DeepTutor` → 事件与回调 → 订阅方式选 **“使用长连接接收事件”**（不是 webhook）。
> 只有 `im.message.receive_v1` 一个事件是必需的。同一个飞书 App 同时只能有一条长连接在工作。

## 数据与备份

全部状态在命名卷 `deeptutor-data`（`/app/data`）：设置、登录密钥、伙伴配置、知识库、记忆。
升级镜像不丢数据；备份请整体备份这个卷。

## 已知取舍

- 未启用 `sandbox-runner` sidecar，模型生成的代码走容器内受限 subprocess
  （`system.json` 的 `sandbox_allow_subprocess`，默认 true）。要更强隔离需自建
  `Dockerfile.runner` 镜像并设 `DEEPTUTOR_SANDBOX_RUNNER_URL`。
- 不提 `pocketbase`：它是可选的单用户认证/存储 sidecar，本部署用 JSON 单用户登录即可。
