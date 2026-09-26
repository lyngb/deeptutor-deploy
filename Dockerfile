# ============================================================
# DeepTutor (HKUDS) —— 在官方镜像上只加一层「启动前写配置」
# ============================================================
# 官方镜像 ghcr.io/hkuds/deeptutor:latest 已经自带：
#   * lark-oapi（requirements.txt → requirements/partners.txt）→ 飞书通道开箱可用
#   * supervisord 同时拉起 backend(uvicorn :8001) 与 frontend(node :3782)
#   * 非 root 用户 deeptutor(uid 1000)
#
# 这里只做一件事：把 seed.py 塞进镜像，并在官方 entrypoint 之前跑一次，
# 把 model_catalog.json / (可选) auth.json 写进数据卷。
# 这样就不需要额外的 init 容器 / depends_on 条件 —— Coolify 只需跑一个服务。
# ============================================================
FROM ghcr.io/hkuds/deeptutor:latest

# 不切 root：官方镜像里 /app/data 属于 deeptutor(uid 1000)，新建的命名卷会继承
# 该属主，因此以默认用户运行即可写入，无需 chown（切 root 反而会让卷属主错乱）。
COPY seed/seed.py /seed/seed.py
COPY seed/entrypoint.sh /usr/local/bin/deeptutor-seed-entrypoint.sh

# 保持默认用户；entrypoint 包一层
ENTRYPOINT ["/bin/bash", "/usr/local/bin/deeptutor-seed-entrypoint.sh"]
