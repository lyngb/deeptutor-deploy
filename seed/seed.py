#!/usr/bin/env python3
"""DeepTutor 一次性配置初始化。

在 `deeptutor` 主容器启动**之前**运行一次（compose 里的 `init` 服务），
把运行时配置直接写进共享数据卷 —— 这样就不必依赖 Web UI 手工点选。

写入：
  <data>/user/settings/model_catalog.json   LLM 供应商档案（DeepSeek，OpenAI 兼容）
  <data>/user/settings/auth.json            登录开关（仅当 DEEPTUTOR_AUTH_ENABLED 为真）

设计要点：
* **幂等**：文件已存在时默认不覆盖，避免每次重新部署把 UI 里改过的设置冲掉。
  需要强制重写时设 ``DEEPTUTOR_SEED_FORCE=1``。
* 只依赖标准库 + ``bcrypt``（镜像自带），**不 import deeptutor 自身的模块** —— 那些模块
  在 import 期就会解析路径/读环境，绕开 entrypoint 单独跑容易踩坑。
* `ModelCatalogService.load()` 会把已有文件与内置默认值**合并**，所以这里只写真需要的
  ``services.llm``，其余服务（embedding/search/tts/...）留空壳由应用自己补。
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

DATA_DIR = Path(os.environ.get("DEEPTUTOR_DATA_DIR", "/app/data"))
SETTINGS_DIR = DATA_DIR / "user" / "settings"
WORKSPACE_DIR = Path(os.environ.get("DEEPTUTOR_WORKSPACE_ROOT", "/workspace"))

TRUTHY = {"1", "true", "yes", "on"}


def env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def is_true(name: str) -> bool:
    return env(name).lower() in TRUTHY


FORCE = is_true("DEEPTUTOR_SEED_FORCE")


def log(message: str) -> None:
    print(f"[seed] {message}", flush=True)


def write_json(path: Path, payload: dict) -> None:
    """原子写入，避免应用读到半截文件。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.replace(path)
    log(f"已写入 {path}")


def seed_model_catalog() -> bool:
    path = SETTINGS_DIR / "model_catalog.json"
    if path.exists() and not FORCE:
        log(f"已存在，跳过：{path.name}（要重写请设 DEEPTUTOR_SEED_FORCE=1）")
        return True

    api_key = env("DEEPSEEK_API_KEY")
    if not api_key:
        log("!! 未提供 DEEPSEEK_API_KEY，跳过模型档案 —— 部署后需在 Web 设置里手工配置")
        return False

    base_url = env("DEEPSEEK_BASE_URL", "https://api.deepseek.com").rstrip("/")
    model_name = env("DEEPSEEK_MODEL", "deepseek-chat")
    profile_id = "deepseek-main"
    model_id = "deepseek-main-chat"

    # 字段名取自 deeptutor/services/config/model_catalog.py 的 _normalize_profile
    # 与 deeptutor/services/provider_registry.py 的 deepseek 预设
    # （binding=openai_compat, default_api_base=https://api.deepseek.com）。
    payload = {
        "version": 1,
        "connections": [],
        "services": {
            "llm": {
                "active_profile_id": profile_id,
                "active_model_id": model_id,
                "profiles": [
                    {
                        "id": profile_id,
                        "name": "DeepSeek",
                        "provider": "deepseek",
                        "binding": "openai_compat",
                        "api_format": "chat_completions",
                        "wire_api": "chat_completions",
                        "base_url": base_url,
                        "api_key": api_key,
                        "api_version": "",
                        "extra_headers": {},
                        "models": [
                            {
                                "id": model_id,
                                "name": model_name,
                                "model": model_name,
                            }
                        ],
                    }
                ],
            }
        },
    }
    write_json(path, payload)
    log(f"模型档案：provider=deepseek  base_url={base_url}  model={model_name}")
    return True


def seed_auth() -> None:
    path = SETTINGS_DIR / "auth.json"
    if not is_true("DEEPTUTOR_AUTH_ENABLED"):
        log("DEEPTUTOR_AUTH_ENABLED 未开启，保持登录关闭（auth.json 不动）")
        return

    username = env("DEEPTUTOR_ADMIN_USER", "admin") or "admin"
    password = env("DEEPTUTOR_ADMIN_PASSWORD")
    if not password:
        log("!! 开启了登录但没给 DEEPTUTOR_ADMIN_PASSWORD，跳过 auth.json")
        return

    # 注意：应用自己的 entrypoint 在首次启动时就会写出一个默认 auth.json
    # （enabled=false）。所以这里不能「文件存在就跳过」，而要按**目标状态**判断：
    # 已经 enabled=true 且已有密码哈希时才算已就绪，否则补写。
    if path.exists() and not FORCE:
        try:
            current = json.loads(path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            current = {}
        if current.get("enabled") and current.get("password_hash"):
            log(f"登录已处于启用状态，跳过：{path.name}（要重置请设 DEEPTUTOR_SEED_FORCE=1）")
            return

    try:
        import bcrypt
    except Exception as exc:  # noqa: BLE001
        log(f"!! 无法 import bcrypt（{exc}），跳过 auth.json")
        return

    # 字段与 deeptutor/services/config/runtime_settings.py 的
    # DEFAULT_AUTH_SETTINGS / _normalize_auth 对齐。
    # cookie_secure 默认 false：当前是 http 的 sslip.io 域名，设为 true 浏览器不会回传
    # 登录 cookie，会直接登不进去。等切到 https 自定义域名后把它设为 true。
    payload = {
        "version": 1,
        "enabled": True,
        "username": username,
        "password_hash": bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode(),
        "token_expire_hours": 168,
        "cookie_secure": is_true("DEEPTUTOR_AUTH_COOKIE_SECURE"),
        "private_login_hosts": [],
    }
    write_json(path, payload)
    log(f"登录已启用：username={username} cookie_secure={payload['cookie_secure']}")


def target_ids() -> tuple[int, int]:
    try:
        return int(env("PUID", "1000") or "1000"), int(env("PGID", "1000") or "1000")
    except ValueError:
        return 1000, 1000


def chown_tree(base: Path, uid: int, gid: int) -> int:
    changed = 0
    for root, dirs, files in os.walk(base):
        for name in [root, *dirs, *files]:
            path = Path(name) if name is root else Path(root) / name
            try:
                os.chown(path, uid, gid)
                changed += 1
            except OSError:
                pass
    return changed


def fix_ownership() -> None:
    """把数据卷与内容工作区交还给应用运行用户。

    Docker 新建的命名卷属主是 root:root，而 DeepTutor 以 uid 1000 运行：

    * `/app/data` 不可写 → entrypoint 会直接报错退出；
    * `/workspace` 不可写 → 飞书里会收到
      "The turn failed: The workspace outputs folder is not writable."

    因此两个都要在启动前 chown 给 PUID/PGID（默认 1000:1000）。
    """
    if os.geteuid() != 0:
        log("非 root 运行，跳过 chown")
        return
    uid, gid = target_ids()

    changed = chown_tree(DATA_DIR, uid, gid)
    log(f"数据目录：{changed} 个路径 -> {uid}:{gid}")

    try:
        (WORKSPACE_DIR / "outputs").mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        log(f"!! 无法创建工作区 outputs：{exc}")
        return
    changed = chown_tree(WORKSPACE_DIR, uid, gid)
    log(f"工作区 {WORKSPACE_DIR}：{changed} 个路径 -> {uid}:{gid}")


def main() -> int:
    log(f"数据目录 {DATA_DIR} / 设置目录 {SETTINGS_DIR}")

    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        log(f"!! 无法创建数据目录：{exc}")
        return 1

    if not os.access(DATA_DIR, os.W_OK):
        log(f"!! 数据目录不可写：{DATA_DIR}")
        return 1

    SETTINGS_DIR.mkdir(parents=True, exist_ok=True)

    seed_model_catalog()
    seed_auth()
    fix_ownership()

    log("完成")
    return 0


if __name__ == "__main__":
    sys.exit(main())
