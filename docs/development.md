# 开发与部署说明

## 设计审阅

检测 YuNet、编码 SFace、CPU 推理、小图库余弦检索与资源约束相符，没有阻止第二次迭代的架构问题。补充了第二次迭代 `uploaded` 和第三次迭代 `ready` 的区别、SQLite 开发环境与 MySQL 部署环境、数据库会话与临时图片清理。

尚需第三次迭代验证模型兼容性、实际拒识阈值和 CPU 性能；HTTPS 及 40 元预算中的现有资源费用在部署前核实，不声称已验证。

## ECS 首次准备（服务器开机后执行）

1. 使用现有 SSH 配置连接服务器，确认系统、已有容器和端口。管理员一次性创建日常部署用户 `duscwalk`，部署文件归该用户所有。安装 Docker Compose 和用于 HTTPS 的宿主机 Nginx。不要覆盖服务器已有服务。
2. 在 `/home/duscwalk/apps/nju-attendance` 创建 `.env`，参考根目录 `.env.production.example`，生成强随机密钥与数据库密码，权限设为 600。数据库密码采用十六进制字符串。生产配置强制 MySQL、Redis、可信 HTTPS 和 Secure Cookie。
3. 配置可信 HTTPS 入口，反代本机 `127.0.0.1:8080`，参考 `deploy/nginx/https.example.conf`。根据域名/IP 证书可用性选定实际方案；不使用自签名证书冒充手机可用的可信 HTTPS。
4. 确认安全组允许实际 Web 端口，SSH 按管理来源限制，MySQL/Redis 保持内部访问。
5. 确认 GHCR 镜像可拉取。首次发布后可将两个包设为公开；若保持私有，仅在 ECS 使用 `read:packages` 凭证登录，不在部署命令中输出凭证。
6. 为 GitHub Actions 配置独立部署公钥及私钥、经过现有可信 SSH 连接核验的主机指纹；不要直接复用或上传本机个人 SSH 私钥。

## GitHub 配置

创建 `production` Environment，并配置：

| 类型 | 名称 | 值 |
| --- | --- | --- |
| Variable | ECS_HOST | 实际 EIP 或主机名 |
| Variable | ECS_USER | duscwalk |
| Variable | ECS_PORT | SSH 端口，默认 22 |
| Secret | ECS_SSH_KEY | 独立部署密钥的私钥 |
| Secret | ECS_KNOWN_HOSTS | 核验后的 known_hosts 条目 |

应用密钥和数据库密码只保存在 ECS `.env`，无需传入 GitHub。镜像发布使用 GitHub 的短期 `GITHUB_TOKEN`。工作流文件可以先提交；以上主机配置未完成前，CD 不具备实际上线条件。

建议对 main 设置 CI 必须通过的分支规则（backend/frontend/integration），并在 production Environment 限制 main 部署来源。可用性以当前 GitHub 仓库套餐为准。

## 发布与恢复

CI 成功发布镜像后，手动执行 Deploy ECS，填写完整 40 位 SHA。发布脚本使用文件锁、拉取镜像、备份现有数据库、执行迁移、更新服务并检查 readiness；通过后记录 `.deployed-revision`。首次部署无旧数据库时跳过备份。

失败时查看 `docker compose logs api migrate web`。回退到先前成功 SHA 前，检查数据库迁移与旧版本兼容性；不自动执行数据库降级。备份可能包含个人资料，应保持私有并制定保留期限，不能进入 Git。

## 第二次迭代证据

手机/桌面 Playwright 测试自动输出注册、私有照片和匿名上传截图，GitHub 保留 7 天。本地结果在 `frontend/test-results`，不会提交到公开仓库。

数据库证据使用 `python -m app.evidence` 输出无密码、会话令牌和原图的只读表格快照（生成 HTML 位于本地 artifacts），分别演示注册前后、登录、注销、照片上传的行数变化。公开提交前仍须人工核查姓名学号脱敏，课程正式手机照片由实际验收手机拍摄。

第三次迭代尚未完成：模型下载和校验、Celery 识别 Worker、身份拒识、活动配置、签到写入和压测。第二次迭代不会返回虚假的识别成功。
