# opencode CLI —— 容器镜像
#
# 单二进制镜像：基础镜像只提供 glibc 与动态加载器，opencode 自带全部逻辑。
# opencode 的真实 DT_NEEDED 只有 libc.so.6 / ld-linux / libpthread / libdl / libm
# （ALSA、Pulse、libsecret、glib 是 dlopen 可选依赖，缺失只让音频/密钥环优雅降级），
# 所以 ubuntu:24.04 基础镜像足够，无需安装任何额外软件包。
#
# 用法（在有外网的机器上构建）：
#     docker build -t opencode:1.18.32 .
#
# 用法（目标机器无外网 —— 本仓库的实际情况）：
#     在别处构建好，导出后导入：
#         docker save opencode:1.18.32 -o opencode.tar
#         docker load -i opencode.tar
#     或直接用 tools/opencode-bundle/build_container.py 生成可 load 的 tar
#     （该脚本不需要本机安装 Docker）。

FROM ubuntu:24.04

LABEL org.opencontainers.image.title="opencode" \
      org.opencontainers.image.version="1.18.32" \
      org.opencontainers.image.description="opencode coding-agent CLI (single-binary image)" \
      org.opencontainers.image.base.name="ubuntu:24.04"

# CLI 本体（185 MB，静态链接所有业务逻辑，只动态依赖 glibc）
COPY opencode /usr/local/bin/opencode
RUN chmod 0755 /usr/local/bin/opencode

# 工作目录：挂载你的项目到这里
WORKDIR /workspace

# 冒烟测试：构建期就确认二进制能跑（失败则构建失败）
RUN /usr/local/bin/opencode --version

# 默认行为
ENTRYPOINT ["/usr/local/bin/opencode"]
CMD ["--help"]
