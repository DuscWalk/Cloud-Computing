import { expect, test } from '@playwright/test'
import fs from 'node:fs'
import { randomBytes } from 'node:crypto'

const image = () => fs.readFileSync(new URL('./fixture.png', import.meta.url))

test('register, log in, inspect private photo, log out, upload anonymously', async ({ page }, info) => {
  const errors: string[] = []
  page.on('pageerror', e => errors.push(e.message))
  const suffix = `${info.project.name}-${Date.now()}`
  const username = `u-${suffix}`.slice(-32)
  const password = randomBytes(24).toString('hex')
  await page.goto('/')
  // Vant embeds its icon font as a data URL; production CSP must allow that font.
  expect(await page.evaluate(async () => (await document.fonts.load('16px vant-icon')).length)).toBeGreaterThan(0)
  await page.getByRole('button', { name: '注册账号', exact: true }).click()
  await page.getByLabel('姓名', { exact: true }).fill('验收同学')
  await page.getByLabel('学号/工号').fill(suffix)
  await page.getByLabel('账号', { exact: true }).fill(username)
  await page.getByLabel('密码', { exact: true }).fill(password)
  await page.getByRole('checkbox').check()
  await page.locator('input[type=file]').setInputFiles({ name: 'standard.png', mimeType: 'image/png', buffer: image() })
  await expect(page.getByAltText('待上传照片预览')).toBeVisible()
  await page.screenshot({ path: info.outputPath('01-register.png'), fullPage: true })
  await page.getByRole('button', { name: '创建账号并上传' }).click()
  await expect(page.getByRole('status')).toContainText('账号已创建')
  await page.getByLabel('密码', { exact: true }).fill(password)
  await page.getByRole('button', { name: '登录', exact: true }).click()
  await expect(page.getByRole('heading', { name: '我的照片', exact: true }).first()).toBeVisible()
  await expect(page.getByText('已上传，待核验')).toBeVisible()
  await expect(page.getByAltText('我的标准照片')).toBeVisible()
  expect(await page.getByAltText('我的标准照片').evaluate((el: HTMLImageElement) => el.naturalWidth)).toBeGreaterThan(0)
  await page.screenshot({ path: info.outputPath('02-private-photo.png'), fullPage: true })
  await page.getByRole('button', { name: '查看签到记录' }).click()
  await expect(page.getByText('暂无记录。')).toBeVisible()
  await page.getByRole('button', { name: '退出', exact: true }).click()
  await expect(page.getByRole('status')).toContainText('已退出登录')
  expect((await page.request.get('/api/me')).status()).toBe(401)
  await page.locator('input[type=file]').setInputFiles({ name: 'capture.png', mimeType: 'image/png', buffer: image() })
  await page.getByRole('button', { name: '上传签到照片' }).click()
  await expect(page.getByRole('status')).toContainText('照片已保存')
  await expect(page.getByText('任务已创建')).toBeVisible()
  await page.getByRole('button', { name: '刷新状态' }).click()
  await expect(page.getByRole('status')).toContainText('尚未完成身份核验')
  await page.screenshot({ path: info.outputPath('03-anonymous-upload.png'), fullPage: true })
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
  expect(errors).toEqual([])
})
