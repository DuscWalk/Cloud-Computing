import { expect, test, type APIRequestContext } from '@playwright/test'
import fs from 'node:fs'
import { randomBytes } from 'node:crypto'
import os from 'node:os'
import { execFileSync } from 'node:child_process'

const known = new URL('../../backend/tests/fixtures/astronaut.png', import.meta.url).pathname
const unknown = new URL('../../backend/tests/fixtures/grace_hopper.jpg', import.meta.url).pathname
const blank = new URL('./fixture.png', import.meta.url).pathname
const active = (job: { status: string }) => ['queued', 'processing'].includes(job.status)

async function result(client: APIRequestContext, job: { id: string; token: string }) {
  const deadline = Date.now() + 60000
  while (Date.now() < deadline) {
    const response = await client.get(`/api/jobs/${job.id}`, { headers: { 'X-Job-Token': job.token } })
    expect(response.ok()).toBe(true)
    const value = await response.json()
    if (!active(value)) return value
    await new Promise(resolve => setTimeout(resolve, 250))
  }
  throw new Error('Recognition job timed out')
}

test('real models: register, anonymous recognition, reject unknown, records and administration', async ({ page, playwright, baseURL }, info) => {
  test.skip(!process.env.E2E_ADMIN_PASSWORD, 'Requires an isolated CI/ECS test deployment; no local model inference')
  test.setTimeout(180000)
  const password = randomBytes(24).toString('hex')
  const suffix = `${info.project.name}-${Date.now()}`
  const username = `u-${suffix}`.slice(-32)
  const eventName = `课程签到-${suffix}`
  const personName = `验收-${info.project.name}`
  const adminUsername = process.env.E2E_ADMIN_USERNAME || 'ci_admin'
  const adminPassword = process.env.E2E_ADMIN_PASSWORD!
  const admin = await playwright.request.newContext({ baseURL })
  const csrf = (await (await admin.get('/api/auth/csrf')).json()).csrf_token
  expect((await admin.post('/api/auth/login', { headers: { 'X-CSRF-Token': csrf }, data: { username: adminUsername, password: adminPassword } })).ok()).toBe(true)
  let userId = ''; let eventId = ''
  let releasePhotos: () => void = () => {}
  const photosGate = new Promise<void>(resolve => { releasePhotos = resolve })
  await page.route('**/api/me/photos', async route => {
    await photosGate
    await route.continue()
  }, { times: 1 })
  const errors: string[] = []
  page.on('pageerror', error => errors.push(error.message))
  try {
    await page.goto('/')
    expect(await page.evaluate(async () => (await document.fonts.load('16px vant-icon')).length)).toBeGreaterThan(0)
    await page.getByRole('button', { name: '登录', exact: true }).click()
    await page.getByLabel('账号', { exact: true }).fill(adminUsername)
    await page.getByLabel('密码', { exact: true }).fill(adminPassword)
    await page.getByRole('button', { name: '登录', exact: true }).click()
    // Reproduce a slow profile response: visible navigation must wait for login to finish.
    await expect(page.getByRole('button', { name: '管理活动与人员' })).toBeDisabled()
    releasePhotos()
    await page.getByRole('button', { name: '管理活动与人员' }).click()
    await page.getByLabel('活动名称').fill(eventName)
    const createdEvent = page.waitForResponse(r => r.url().endsWith('/api/admin/events') && r.request().method() === 'POST')
    await page.getByRole('button', { name: '创建活动', exact: true }).click()
    const eventResponse = await createdEvent
    expect(eventResponse.status()).toBe(201)
    eventId = (await eventResponse.json()).id
    await expect(page.getByText('活动已创建，可以复制链接邀请大家签到。')).toBeVisible()
    await page.getByRole('button', { name: '退出', exact: true }).click()
    await expect(page.getByText('已退出登录', { exact: true })).toBeVisible()
    await page.getByRole('button', { name: '注册账号', exact: true }).click()
    await page.getByLabel('姓名', { exact: true }).fill(personName)
    await page.getByLabel('学号/工号').fill(suffix)
    await page.getByLabel('账号', { exact: true }).fill(username)
    await page.getByLabel('密码', { exact: true }).fill(password)
    await page.getByRole('checkbox').check()
    await page.getByLabel('标准照片', { exact: true }).setInputFiles(known)
    await expect(page.getByAltText('待上传照片预览')).toBeVisible()
    await page.screenshot({ path: info.outputPath('01-register.png'), fullPage: true })
    const registered = page.waitForResponse(r => r.url().endsWith('/api/auth/register'))
    await page.getByRole('button', { name: '创建账号并上传' }).click()
    const registration = await registered
    expect(registration.status()).toBe(201)
    userId = (await registration.json()).user.id
    await expect(page.getByText('人脸录入成功，可以参加签到。', { exact: true })).toBeVisible({ timeout: 45000 })
    await page.getByLabel('密码', { exact: true }).fill(password)
    await page.getByRole('button', { name: '登录', exact: true }).click()
    await expect(page.getByText('已录入', { exact: true })).toBeVisible()
    await expect.poll(() => page.getByAltText('我的标准照片').evaluate((el: HTMLImageElement) => el.naturalWidth)).toBeGreaterThan(0)
    await page.screenshot({ path: info.outputPath('02-enrolled.png'), fullPage: true })
    await page.getByRole('button', { name: '退出', exact: true }).click()
    await expect(page.getByText('已退出登录', { exact: true })).toBeVisible()
    expect((await page.request.get('/api/me')).status()).toBe(401)
    await page.getByLabel('签到活动').selectOption(eventId)

    async function upload(file: string, text: string) {
      await page.getByLabel('签到照片', { exact: true }).setInputFiles(file)
      const accepted = page.waitForResponse(r => r.url().endsWith('/api/uploads'))
      await page.getByRole('button', { name: '开始签到', exact: true }).click()
      expect((await accepted).status()).toBe(202)
      await expect(page.getByText(text, { exact: true })).toBeVisible({ timeout: 45000 })
    }
    await upload(known, '签到成功。')
    await page.screenshot({ path: info.outputPath('03-checkin-success.png'), fullPage: true })
    await upload(known, '你已完成本次签到，无需重复提交。')
    await upload(unknown, '未识别到已录入人员，请先注册并完成人脸录入。')
    await page.screenshot({ path: info.outputPath('04-unknown-person.png'), fullPage: true })
    await upload(blank, '未检测到人脸，请正对镜头重新拍摄。')
    await page.screenshot({ path: info.outputPath('05-no-face.png'), fullPage: true })

    // Concurrent HTTP submissions use real queued CPU inference on the CI/ECS host.
    const anonymous = await playwright.request.newContext({ baseURL })
    try {
      const token = (await (await anonymous.get('/api/auth/csrf')).json()).csrf_token
      const report: object[] = []
      for (const concurrency of [1, 5, 10]) {
        const values = await Promise.all(Array.from({ length: concurrency }, async () => {
          const started = Date.now()
          const accepted = await anonymous.post('/api/uploads', {
            headers: { 'X-CSRF-Token': token, 'Idempotency-Key': randomBytes(16).toString('hex') },
            multipart: { event_id: eventId, photo: { name: 'photo.png', mimeType: 'image/png', buffer: fs.readFileSync(known) } },
          })
          expect(accepted.status()).toBe(202)
          const acceptedMs = Date.now() - started
          const done = await result(anonymous, await accepted.json())
          expect(done.result_code).toBe('already_checked_in')
          return { accepted_ms: acceptedMs, complete_ms: Date.now() - started, code: done.result_code }
        }))
        const sorted = values.map(v => v.complete_ms).sort((a, b) => a - b)
        report.push({ concurrency, samples: values, p95_ms: sorted[Math.ceil(sorted.length * 0.95) - 1] })
      }
      fs.writeFileSync(info.outputPath('concurrency.json'), JSON.stringify({
        deployment: baseURL,
        environment: process.env.E2E_ENVIRONMENT || 'GitHub CI',
        note: 'Client CPU describes the browser driver, not the model server. One batch per concurrency; not a sustained capacity estimate.',
        client_cpu: os.cpus()[0]?.model, client_cpus: os.cpus().length, results: report,
      }, null, 2))
    } finally { await anonymous.dispose() }
    const saved = await (await admin.get(`/api/admin/events/${eventId}/records`)).json()
    expect(saved.items).toHaveLength(1)
    expect(saved.items[0].name).toBe(personName)
    fs.writeFileSync(info.outputPath('verification-ids.json'), JSON.stringify({ event_id: eventId, user_id: userId, event_name: eventName }, null, 2))
    if (['compose', 'ecs'].includes(process.env.E2E_DATABASE_EVIDENCE || '')) {
      // Explicit opt-in: inspect the CI stack or remote ECS, never start local models.
      let html: string
      if (process.env.E2E_DATABASE_EVIDENCE === 'ecs') {
        const target = process.env.E2E_SSH_TARGET || 'duscwalk@120.46.147.216'
        if (!/^duscwalk@[a-zA-Z0-9.-]+$/.test(target)) throw new Error('Invalid ECS SSH target')
        const remote = 'cd ~/apps/nju-attendance && docker compose exec -T api '
        execFileSync('ssh', ['-o', 'BatchMode=yes', target, remote + 'python -m app.evidence --output /tmp/database-evidence.html'])
        html = execFileSync('ssh', ['-o', 'BatchMode=yes', target, remote + 'cat /tmp/database-evidence.html'], { encoding: 'utf8' })
      } else {
        const compose = ['compose', '-f', '../compose.yaml', 'exec', '-T', 'api']
        execFileSync('docker', [...compose, 'python', '-m', 'app.evidence', '--output', '/tmp/database-evidence.html'])
        html = execFileSync('docker', [...compose, 'cat', '/tmp/database-evidence.html'], { encoding: 'utf8' })
      }
      fs.writeFileSync(info.outputPath('database.html'), html)
      const databasePage = await page.context().newPage()
      await databasePage.setViewportSize({ width: 1600, height: 1000 })
      await databasePage.setContent(html)
      await databasePage.screenshot({ path: info.outputPath('07-server-database.png'), fullPage: true })
      await databasePage.close()
    }
    await page.getByRole('button', { name: '登录', exact: true }).click()
    await page.getByLabel('账号', { exact: true }).fill(username)
    await page.getByLabel('密码', { exact: true }).fill(password)
    await page.getByRole('button', { name: '登录', exact: true }).click()
    await page.getByRole('button', { name: '查看签到记录' }).click()
    await expect(page.getByText(eventName, { exact: true })).toBeVisible()
    await page.screenshot({ path: info.outputPath('06-personal-records.png'), fullPage: true })
    expect((await page.request.get('/api/admin/users')).status()).toBe(403)
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
    expect(errors).toEqual([])
  } finally {
    releasePhotos()
    if (userId) await admin.delete(`/api/admin/users/${userId}`, { headers: { 'X-CSRF-Token': csrf } })
    if (eventId) await admin.post(`/api/admin/events/${eventId}/cancel`, { headers: { 'X-CSRF-Token': csrf } })
    await admin.dispose()
  }
})
