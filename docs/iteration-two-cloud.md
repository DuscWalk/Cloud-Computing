# 迭代二云端验证记录

验证时间：2026-09-29，华为云 ECS，Ubuntu 24.04，4 核 / 16 GB，无 GPU。

访问地址：**https://120.46.147.216**。HTTP 自动跳转 HTTPS；证书由 Let's Encrypt 签发，包含该 IP 的 SAN，浏览器无需跳过证书检查。此阶段不部署人脸模型，不返回签到成功。

## 部署与测试结果

- 首次业务验收镜像版本：`83e33e2b9d2d536d6bfb2ad986ec7ca911cc1dab`。该版本 [CI](https://github.com/DuscWalk/Cloud-Computing/actions/runs/36557467302) 的 backend、frontend、integration、publish 全部成功。后续修复内嵌图标字体的 CSP 配置，并增加字体加载检查；当前部署版本以服务器 `.deployed-revision` 为准。
- 使用独立部署密钥，以 `duscwalk` 执行发布脚本，完成 MySQL 备份、Alembic 迁移及 readiness 检查。API、Web、MySQL、Redis 健康，临时照片清理进程运行。
- 从开发机经公网 HTTPS 运行 Chromium 的 Pixel 7 模拟尺寸流程：注册并上传、登录、私有照片显示、查看空签到记录、退出、匿名上传和任务状态查询全部通过。额外检查了桌面页面。
- 登录 Cookie 的 Secure、HttpOnly 属性已验证。退出后 `/api/me` 返回 401。
- 伪造 `X-Forwarded-For` 和 `X-Real-IP` 的请求被外层代理覆盖，API 记录真实公网客户端地址；限流不会把所有用户合并到 Docker 网关地址。
- `certbot renew --dry-run --run-deploy-hooks` 通过；开机及每日两次的续期定时器已启用。未通过重启 ECS 测试，以免打断现有 Hadoop 服务。
- 修复了发布探针使用 `localhost` 时优先连接 IPv6、导致误报失败的问题；显式访问 `127.0.0.1` 后发布成功。

## 数据库变化

以下计数来自 ECS 内真实 MySQL，由只读证据工具生成，不包含密码或会话令牌：

| 阶段 | users | face_templates | recognition_jobs | user_sessions | attendance_records |
| --- | ---: | ---: | ---: | ---: | ---: |
| 操作前 | 0 | 0 | 0 | 0 | 0 |
| 注册并上传标准照片 | 1 | 1 | 1 | 0 | 0 |
| 登录 | 1 | 1 | 1 | 1 | 0 |
| 退出登录 | 1 | 1 | 1 | 0 | 0 |
| 匿名上传 | 1 | 2 | 2 | 0 | 0 |

采证后仅按本次脚本记录的精确 ID 清理生成的测试用户、两张图片和任务，恢复 10 人注册容量；截图保留。测试使用生成的示意图片和随机密码，不构成人脸识别测试。

## 本地证据文件

文件在项目目录 `artifacts/cloud/`，不提交到公开 Git 仓库：

- `01-registration.png`：注册表单及标准照片预览。
- `02-private-photo.png`：登录后查看私有照片。
- `03-records.png`：迭代二空签到记录。
- `04-anonymous-upload.png`：匿名上传反馈。
- `05-desktop.png`：桌面页面。
- `00-before-db.png`、`01-registered-db.png`、`02-logged-in-db.png`、`03-logged-out-db.png`、`04-anonymous-upload-db.png`：各阶段数据库快照，另有同名 HTML。

上述手机页面来自浏览器模拟尺寸，正式提交前仍需使用实际手机拍摄照片、注册和上传并补充截图。未录入人员拒识、真正签到成功和签到记录写入属于迭代三。

## 尚未启用的设施

GitHub Actions 的 CI 和镜像发布已运行；手动 SSH 发布已成功。Actions 的 `Deploy ECS` 尚缺 `production` Environment 的 Variables/Secrets，本机只有 Git SSH 认证，没有 GitHub API 登录凭证，因此尚未写入这些设置。

独立 Actions 密钥已生成在开发机 `/home/duscwalk/.ssh/nju_attendance_actions`，其公钥已安装并通过 SSH 验证，禁用端口转发和 PTY。私钥不进入仓库，也不要直接发送到聊天中。经既有 SSH 信任链核验的主机公钥保存在本地 `artifacts/cloud/known_hosts`。GitHub 所需字段见 [部署说明](development.md#github-配置)。

本轮复用现有 ECS 和磁盘，没有开通 RDS、OBS、FRS、负载均衡或购买域名。现有 ECS/EIP 运行和带宽仍按账号套餐计费；本轮未读取华为云账单，不能据此确认总支出。
