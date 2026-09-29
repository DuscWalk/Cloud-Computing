# 南京大学云计算课程：人脸签到

架构及模型见 [设计文档](docs/design.md)。第二次迭代提供真实的注册、登录、退出登录、标准照片管理及匿名拍照上传；人脸检测、编码、检索和签到写入在第三次迭代实现。

## 本地开发

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

浏览器测试需要 API 和前端正在运行，会创建测试用户；运行前请使用独立测试数据库。更改数据库结构应生成并检查 Alembic 迁移，不能通过启动 API 自动建表。

## MySQL / Redis 集成环境

```bash
cp .env.example .env
# 修改三个密码字段为随机值；数据库密码使用十六进制避免 URL 转义问题。
docker compose up --build -d --wait
# 浏览器打开 http://localhost:8080
E2E_BASE_URL=http://localhost:8080 npm --prefix frontend run test:e2e
docker compose exec api python -m app.cleanup
docker compose down
```

默认只监听本机，MySQL、Redis 和 API 不发布公网端口。Compose 自动执行迁移；照片、数据库和 Redis 使用持久卷。`down` 保留卷，禁止为重启服务使用 `down -v`。

## CI/CD

GitHub Actions 在推送 main 或 PR 时检查 Python、TypeScript、迁移及 MySQL/Redis 下的手机/桌面浏览器完整流程。main 的 CI 全部通过后发布按完整提交 SHA 标记的 API/Web 镜像到 GHCR。

`Deploy ECS` 工作流手动执行，验证该 SHA 的 main CI 成功后再部署；服务器关闭时不会自动尝试部署。ECS 初始化、公网 IP HTTPS、证书续期及 GitHub secrets/variables 见 [部署说明](docs/development.md)。Actions 远程部署仍需配置 Environment Secrets，本地 SSH 可直接执行发布脚本。

## 当前接口

- 注册：`POST /api/auth/register`，multipart 基本信息与照片。
- 登录/退出：`POST /api/auth/login`、`POST /api/auth/logout`。
- 本人：`GET /api/me`、`GET/POST /api/me/photos`、`DELETE /api/me/photos/{id}`。
- 私有图片：`GET /api/photos/{id}`，仅本人可访问。
- 匿名上传：`POST /api/uploads`，返回状态 `uploaded`，不代表签到成功。
- 任务查询：`GET /api/jobs/{id}`，匿名需要 `X-Job-Token`。
- 本人记录：`GET /api/me/attendance`，第三次迭代前通常为空。

所有写请求先获取 `/api/auth/csrf` 返回的令牌，通过 `X-CSRF-Token` 提交，浏览器同时携带 HttpOnly CSRF Cookie。密码使用 Argon2id，登录会话可撤销且只保存令牌哈希。照片剥离 EXIF 等元数据并转换为 JPEG，匿名图片及任务 24 小时后由清理进程删除。
