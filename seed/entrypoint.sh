#!/usr/bin/env bash
# ============================================================
# DeepTutor 启动包装：先写配置，再把控制权交回官方 entrypoint
# ============================================================
# 官方 entrypoint 是 /app/entrypoint.sh（它负责从 data/user/settings/*.json
# 导出环境变量、修正卷权限，最后 exec supervisord）。
# 我们在它之前跑一次 seed.py —— 必须是「先写配置、后启动」，否则应用会先读到空设置。
#
# seed 失败不阻断启动（宁可起来后在 Web 设置里补，也不要整个服务起不来）。
set -u

echo "[dt-entrypoint] === 写入运行时配置 ==="
if [ -f /seed/seed.py ]; then
  python /seed/seed.py || echo "[dt-entrypoint] !! seed 失败，继续启动（可在 Web 设置里手工配置）"
else
  echo "[dt-entrypoint] !! 找不到 /seed/seed.py，跳过"
fi

echo "[dt-entrypoint] === 移交给官方 entrypoint ==="
exec /app/entrypoint.sh "$@"
