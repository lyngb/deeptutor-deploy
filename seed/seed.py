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
    if path.exists() and not FORCE:
        log(f"已存在，跳过：{path.name}（要重写请设 DEEPTUTOR_SEED_FORCE=1）")
        return

    username = env("DEEPTUTOR_ADMIN_USER", "admin") or "admin"
    password = env("DEEPTUTOR_ADMIN_PASSWORD")
    if not password:
        log("!! 开启了登录但没给 DEEPTUTOR_ADMIN_PASSWORD，跳过 auth.json")
        return

    try:
        import bcrypt
    except Exception as exc:  # noqa: BLE001
        log(f"!! 无法 import bcrypt（{exc}），跳过 auth.json")
        return

    # 字段与 deeptutor/services/config/runtime_settings.py 的
    # DEFAULT_AUTH_SETTINGS / _normalize_auth 对齐。
    payload = {
        "version": 1,
        "enabled": True,
        "username": username,
        "password_hash": bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode(),
        "token_expire_hours": 168,
        "cookie_secure": True,
        "private_login_hosts": [],
    }
    write_json(path, payload)
    log(f"登录已启用：username={username}（密码为 Coolify 里的 DEEPTUTOR_ADMIN_PASSWORD）")


def main() -> int:
    log(f"数据目录 {DATA_DIR} / 设置目录 {SETTINGS_DIR}")
    if not DATA_DIR.exists():
        log(f"!! 数据目录不存在：{DATA_DIR}（卷没挂上？）")
        return 1
    if not os.access(DATA_DIR, os.W_OK):
        log(f"!! 数据目录不可写：{DATA_DIR}（卷权限问题，检查 PUID/PGID）")
        return 1

    SETTINGS_DIR.mkdir(parents=True, exist_ok=True)

    catalog_ok = seed_model_catalog()
    seed_auth()

    log("完成")
    # 模型档案写失败不算致命 —— 让主容器起来，用户可以在 UI 里补
    return 0 if catalog_ok else 0


if __name__ == "__main__":
    sys.exit(main())
