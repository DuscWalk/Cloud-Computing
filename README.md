# 南京大学云计算课程：人脸签到

架构及模型见 [设计文档](docs/design.md)。第三次迭代实现 YuNet 检测、SFace 编码、匿名身份检索、拒识、幂等签到和记录查询，以及管理员活动/人员/照片管理。实现与验收进度见 [迭代三说明](docs/iteration-three.md)。

云端体验：**https://120.46.147.216**（ECS 开机时可用）。已完成迭代三部署和真实模型验收：注册录入后，无需登录即可选择活动并拍照签到。公网验证结果、并发实测和截图位置见 [迭代三云端验收记录](docs/iteration-three-cloud.md)。

## 本地开发

**当前开发约束：本机不运行人脸模型。** 本机可编辑代码、构建前端和运行默认单元测试；真实推理、完整容器环境和模型端到端测试仅在 GitHub CI 或 ECS 运行。下面 `make dev-api` 不会加载模型，Worker 未就绪时上传接口会返回 503。

需要 Python 3.12（最低 3.10）、uv 0.12.17、Node.js 22、npm 和 Git。

```bash
make install
make dev-api
# 另开终端
make dev-web
```

打开 http://localhost:5173。API 文档：http://localhost:8000/api/docs。开发数据库位于 `backend/data/attendance.db`，照片在 `backend/data/photos`；它们以及上传截图不会进入 Git。

```bash
make check
make test
cd frontend
npx playwright install chromium
npm run test:e2e
```

浏览器测试默认跳过；需显式设置远程 `E2E_BASE_URL`、`E2E_ADMIN_USERNAME` 和 `E2E_ADMIN_PASSWORD` 才执行。密码只通过私有文件或进程环境传入。测试会创建并删除专用测试用户；本机只运行浏览器，不启动模型。更改数据库结构应生成并检查 Alembic 迁移，不能通过启动 API 自动建表。

## MySQL / Redis 集成环境

以下完整环境会启动模型 Worker，应在 **ECS/CI** 执行，不在当前开发电脑执行。

```bash
cp .env.example .env
# 修改三个密码字段为随机值；数据库密码使用十六进制避免 URL 转义问题。
docker compose up --build -d --wait
# 浏览器打开 http://localhost:8080
E2E_BASE_URL=http://localhost:8080 npm --prefix frontend run test:e2e
docker compose exec api python -m app.cleanup
docker compose down
```

默认只监听本机，MySQL、Redis 和 API 不发布公网端口。Compose 自动执行迁移并下载校验固定模型；照片、模型、数据库和 Redis 使用持久卷。`down` 保留卷，禁止为重启服务使用 `down -v`。

## CI/CD

GitHub Actions 在推送 main 或 PR 时检查 Python、TypeScript、迁移、真实神经网络，以及 MySQL/Redis/Celery 下的手机/桌面完整签到流程和 1/5/10 并发提交。main 的 CI 全部通过后发布按完整提交 SHA 标记的 API/Web 镜像到 GHCR。

`Deploy ECS` 工作流手动执行，验证该 SHA 的 main CI 成功后再部署；服务器关闭时不会自动尝试部署。`production` 环境已配置，并于 2026-09-29 [完成首次 Actions 远程部署](https://github.com/DuscWalk/Cloud-Computing/actions/runs/36561209961)。ECS 初始化、公网 IP HTTPS、证书续期及 GitHub secrets/variables 见 [部署说明](docs/development.md)。本地 SSH 也可直接执行发布脚本。

## 当前接口

- 注册：`POST /api/auth/register`，multipart 基本信息与照片。
- 登录/退出：`POST /api/auth/login`、`POST /api/auth/logout`。
- 本人：`GET /api/me`、`GET/POST /api/me/photos`、`DELETE /api/me/photos/{id}`。
- 私有图片：`GET /api/photos/{id}`，仅本人可访问。
- 匿名签到：`POST /api/uploads`，提交照片、`event_id` 和 `Idempotency-Key`，返回 202；轮询任务获取真实结果。
- 任务查询：`GET /api/jobs/{id}`，匿名需要 `X-Job-Token`。
- 本人记录：`GET /api/me/attendance`。
- 活动：`GET /api/events`、`GET /api/events/{id}`；管理员管理接口见 `/api/docs` 的 `/api/admin/*`。

所有写请求先获取 `/api/auth/csrf` 返回的令牌，通过 `X-CSRF-Token` 提交，浏览器同时携带 HttpOnly CSRF Cookie。密码使用 Argon2id，登录会话可撤销且只保存令牌哈希。照片剥离 EXIF 等元数据并转换为 JPEG，匿名图片及任务 24 小时后由清理进程删除。
