# 开发与部署说明

## 设计审阅

检测 YuNet、编码 SFace、CPU 推理、小图库余弦检索与资源约束相符，没有阻止第二次迭代的架构问题。补充了第二次迭代 `uploaded` 和第三次迭代 `ready` 的区别、SQLite 开发环境与 MySQL 部署环境、数据库会话与临时图片清理。

模型兼容性、可信 HTTPS 和 ECS CPU 推理已验证，结果见 [迭代三云端验收](iteration-three-cloud.md)。真实课堂照片的拒识阈值仍需校准，40 元预算中的现有资源费用以华为云账单核算。

## ECS 首次准备（服务器开机后执行）

1. 使用现有 SSH 配置连接服务器，确认系统、已有容器和端口。管理员一次性创建日常部署用户 `duscwalk`，部署文件归该用户所有。安装 Docker Compose 和用于 HTTPS 的宿主机 Nginx。不要覆盖服务器已有服务。
2. 在 `/home/duscwalk/apps/nju-attendance` 创建 `.env`，参考根目录 `.env.production.example`，生成强随机密钥与数据库密码，权限设为 600。数据库密码采用十六进制字符串。生产配置强制 MySQL、Redis、可信 HTTPS 和 Secure Cookie。
3. 配置可信 HTTPS 入口，反代本机 `127.0.0.1:8080`，参考 `deploy/nginx/https.example.conf`。根据域名/IP 证书可用性选定实际方案；不使用自签名证书冒充手机可用的可信 HTTPS。
4. 确认安全组允许实际 Web 端口，SSH 按管理来源限制，MySQL/Redis 保持内部访问。
5. 确认 GHCR 镜像可拉取。首次发布后可将两个包设为公开；若保持私有，仅在 ECS 使用 `read:packages` 凭证登录，不在部署命令中输出凭证。
6. 为 GitHub Actions 配置独立部署公钥及私钥、经过现有可信 SSH 连接核验的主机指纹；不要直接复用或上传本机个人 SSH 私钥。

## GitHub 配置

用户已于 2026-09-29 在 GitHub 网页完成 `production` 环境配置；[首次 Actions 部署](https://github.com/DuscWalk/Cloud-Computing/actions/runs/36561209961) 全部通过，ECS 版本与公网 readiness 已复核。本机仍仅配置 Git SSH，没有 GitHub API 登录凭证；后续修改仓库设置可继续通过网页完成。本地 SSH 手动发布不依赖 GitHub Secrets。

`production` Environment 使用以下配置（重建环境时参考）：

| 类型 | 名称 | 值 |
| --- | --- | --- |
| Variable | ECS_HOST | 120.46.147.216 |
| Variable | ECS_USER | duscwalk |
| Variable | ECS_PORT | SSH 端口，默认 22 |
| Secret | ECS_SSH_KEY | 独立部署密钥的私钥 |
| Secret | ECS_KNOWN_HOSTS | 核验后的 known_hosts 条目 |

应用密钥和数据库密码只保存在 ECS `.env`，无需传入 GitHub。镜像发布使用 GitHub 的短期 `GITHUB_TOKEN`。运行部署工作流前需开启 ECS，并填写已通过 main CI 的完整提交 SHA。

镜像发布分别缓存 API 和 Web 的构建层，减少后续小改动重新安装依赖和下载大层的开销。ECS 访问 GHCR 过慢时，可先在开发机拉取 CI 镜像，再通过 `docker image save | gzip | ssh ... docker image load` 传入；这只传文件，不在开发机启动模型。

建议对 main 设置 CI 必须通过的分支规则（backend/frontend/models/integration），并在 production Environment 限制 main 部署来源。可用性以当前 GitHub 仓库套餐为准。

## 发布与恢复

CI 成功发布镜像后，手动执行 Deploy ECS，填写完整 40 位 SHA。发布脚本使用文件锁，先拉取镜像并校验模型，再停止 API、Worker、dispatcher 和清理进程，备份数据库、执行迁移、更新服务并检查 readiness；通过后记录 `.deployed-revision`。迁移期间有短暂维护窗口，避免旧进程继续写入正在升级的表。迁移失败时保持写入进程停止，检查日志和备份后再决定恢复版本，不自动降级数据库。

失败时查看 `docker compose logs api migrate web`。回退到先前成功 SHA 前，检查数据库迁移与旧版本兼容性；不自动执行数据库降级。备份可能包含个人资料，应保持私有并制定保留期限，不能进入 Git。

## 第二次迭代证据

手机/桌面 Playwright 测试自动输出注册、私有照片和匿名上传截图，GitHub 保留 7 天。本地结果在 `frontend/test-results`，不会提交到公开仓库。

数据库证据使用 `python -m app.evidence` 输出无密码、会话令牌和原图的只读表格快照（生成 HTML 位于本地 artifacts），分别演示注册前后、登录、注销、照片上传的行数变化。公开提交前仍须人工核查姓名学号脱敏，课程正式手机照片由实际验收手机拍摄。

第三次迭代已实现模型下载和校验、Celery 识别 Worker、身份拒识、活动配置、签到写入和并发测试脚本，验证状态见 [迭代三说明](iteration-three.md)。当前 CI 输出真实模型流程的截图与 1/5/10 并发报告；数据库快照增加模型版本、特征维度、任务结果和签到记录，不输出特征向量或姓名学号。本机不启动模型或完整 Compose 栈；真实推理只在 GitHub CI / ECS 上验证。

## 公网 IP 部署（2026-09-29）

目标地址为 `https://120.46.147.216`，部署目录 `/home/duscwalk/apps/nju-attendance`，日常部署使用 `duscwalk`。Ubuntu 24.04 上安装 Docker、Compose 和宿主机 Nginx；原有 Hadoop 服务保留。宿主机防火墙放行 80/443，容器 Web 只绑定 `127.0.0.1:8080`，MySQL/Redis 不发布端口。

HTTPS 使用 Let's Encrypt 免费 IP 证书，无需购买域名。Certbot 5.8.0 安装在 `/opt/certbot`，申请使用 `--ip-address` 和 `--required-profile shortlived`。首次先安装 `deploy/nginx/ip-http.conf`，创建 `/var/www/acme`，再执行：

```bash
# 以下是需要管理员权限的一次性操作；正常发布仍以 duscwalk 执行。
/opt/certbot/bin/certbot certonly --webroot -w /var/www/acme \
  --ip-address 120.46.147.216 --required-profile shortlived \
  --cert-name nju-attendance-ip --non-interactive --agree-tos \
  --register-unsafely-without-email
```

成功后将站点配置替换为 `deploy/nginx/ip-https.conf`，执行 `nginx -t` 并 reload。安装 `deploy/systemd/attendance-certbot.*` 到 `/etc/systemd/system/`，执行 `systemctl daemon-reload`、`systemctl enable --now attendance-certbot.timer`。定时器在开机后和每天两次检查续期，成功后验证并 reload Nginx。IP 证书约 6 天有效；长期关机后可能需要等待开机续期完成再用手机访问。80 端口的 ACME 路径必须持续可达。EIP 改变时须更新两份 Nginx 配置并重新申请对应证书。

外层 Nginx 覆盖客户端传入的转发头；内部 Nginx 信任私有 Docker 网关并保留真实客户端 IP，避免所有公网用户共用一份限流计数。不要将内部 Web 端口改为直接暴露公网。

服务器无法直连 Docker Hub 时，从已拉取官方镜像的开发机传入基础镜像，不配置来源不明的镜像代理：

```bash
set -o pipefail
docker image save mysql:8.4 redis:7.4-alpine | gzip -1 | \
  ssh duscwalk@120.46.147.216 'gunzip | docker image load'
```

应用镜像使用 CI 发布的 GHCR 完整 SHA 标签。发布脚本通过健康检查后将镜像引用保存在服务器 `.env`，后续维护命令自动使用同一版本。服务器重启时 Docker 与容器按既有 restart 策略启动。

```bash
ssh duscwalk@120.46.147.216
cd ~/apps/nju-attendance
bash deploy/release.sh <通过CI的40位提交SHA>
docker compose ps
```
