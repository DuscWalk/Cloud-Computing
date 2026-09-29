<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { showConfirmDialog, Icon as VanIcon } from 'vant'

type Page = 'home' | 'register' | 'login' | 'profile' | 'records'
interface User { id: string; name: string; student_id: string; username: string; role: string }
interface Job { id: string; token?: string; status: string; message: string }
interface Photo { id: string; status: string; purpose: string; created_at: string }
interface Attendance { id: string; event_id: string; checked_at: string }
const csrf = ref('')
const me = ref<User | null>(null)
const mode = ref<Page>('home')
const busy = ref(false)
const initialized = ref(false)
const message = ref('')
const error = ref('')
const job = ref<Job | null>(null)
const photos = ref<Photo[]>([])
const records = ref<Attendance[]>([])
const form = ref({ name: '', student_id: '', username: '', password: '', consent: false })
const loginForm = ref({ username: '', password: '' })
const photo = ref<File | null>(null)
const preview = ref('')
const loggedIn = computed(() => Boolean(me.value))
const titles = { home: '手机人脸签到', register: '注册并上传照片', login: '登录', profile: '我的照片', records: '签到记录' }

async function api<T>(path: string, options: RequestInit = {}): Promise<T> {
  const headers = new Headers(options.headers)
  if (csrf.value && options.method && options.method !== 'GET') headers.set('X-CSRF-Token', csrf.value)
  const response = await fetch(path, { credentials: 'same-origin', ...options, headers })
  const data = response.status === 204 ? null : await response.json().catch(() => ({}))
  if (!response.ok) throw new Error(typeof data?.detail === 'string' ? data.detail : '请求失败，请稍后重试')
  return data as T
}
function clearPhoto() {
  if (preview.value) URL.revokeObjectURL(preview.value)
  preview.value = ''; photo.value = null
}
function selectPhoto(event: Event) {
  clearPhoto(); error.value = ''
  const file = (event.target as HTMLInputElement).files?.[0]
  if (!file) return
  if (!['image/jpeg', 'image/png', 'image/webp'].includes(file.type)) { error.value = '请选择 JPEG、PNG 或 WebP 照片'; return }
  if (file.size > 5 * 1024 * 1024) { error.value = '照片不能超过 5 MB'; return }
  photo.value = file; preview.value = URL.createObjectURL(file)
}
function formData(fields: Record<string, string | boolean>, file: File | null) {
  const body = new FormData()
  Object.entries(fields).forEach(([key, value]) => body.append(key, String(value)))
  if (file) body.append('photo', file)
  return body
}
async function perform(action: () => Promise<void>) {
  if (busy.value || !initialized.value) return
  busy.value = true; error.value = ''; message.value = ''
  try {
    csrf.value = (await api<{ csrf_token: string }>('/api/auth/csrf')).csrf_token
    await action()
  } catch (e) { error.value = e instanceof Error ? e.message : '连接失败，请稍后重试' }
  finally { busy.value = false }
}
function register() { return perform(async () => {
  const data = await api<{ job: Job }>('/api/auth/register', { method: 'POST', body: formData(form.value, photo.value) })
  job.value = data.job; message.value = '账号已创建，照片已保存。请登录查看照片状态。'
  loginForm.value.username = form.value.username; form.value.password = ''; form.value.consent = false
  clearPhoto(); mode.value = 'login'
}) }
function login() { return perform(async () => {
  me.value = (await api<{ user: User }>('/api/auth/login', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(loginForm.value) })).user
  loginForm.value.password = ''; message.value = '登录成功'; mode.value = 'profile'; clearPhoto(); await loadPhotos()
}) }
function logout() { return perform(async () => {
  await api('/api/auth/logout', { method: 'POST' }); me.value = null; photos.value = []; records.value = []
  job.value = null; clearPhoto(); mode.value = 'home'; message.value = '已退出登录'
}) }
function uploadStandard() { return perform(async () => {
  const data = await api<{ job: Job }>('/api/me/photos', { method: 'POST', body: formData({}, photo.value) })
  job.value = data.job; message.value = data.job.message; clearPhoto(); await loadPhotos()
}) }
function anonymousCheckin() { return perform(async () => {
  const data = await api<Job>('/api/uploads', { method: 'POST', body: formData({}, photo.value) })
  job.value = data; message.value = data.message; clearPhoto()
}) }
async function deletePhoto(id: string) {
  try { await showConfirmDialog({ title: '删除照片', message: '删除后该照片将无法用于身份核验。' }) }
  catch { return }
  await perform(async () => { await api(`/api/me/photos/${id}`, { method: 'DELETE' }); await loadPhotos(); message.value = '照片已删除' })
}
async function refreshJob() {
  if (!job.value?.token) return
  await perform(async () => {
    const data = await api<Job>(`/api/jobs/${job.value!.id}`, { headers: { 'X-Job-Token': job.value!.token! } })
    job.value = { ...data, token: job.value!.token }; message.value = data.message
  })
}
async function loadPhotos() { if (loggedIn.value) photos.value = (await api<{ items: Photo[] }>('/api/me/photos')).items }
async function loadRecords() { if (loggedIn.value) records.value = (await api<{ items: Attendance[] }>('/api/me/attendance')).items }
async function go(next: Page) {
  if (busy.value) return
  error.value = ''; message.value = ''; clearPhoto(); mode.value = next
  try { if (next === 'profile') await loadPhotos(); if (next === 'records') await loadRecords() }
  catch (e) { error.value = e instanceof Error ? e.message : '加载失败' }
}
onMounted(async () => {
  try {
    csrf.value = (await api<{ csrf_token: string }>('/api/auth/csrf')).csrf_token
    const response = await fetch('/api/me', { credentials: 'same-origin' })
    if (response.ok) me.value = await response.json()
    else if (response.status !== 401) throw new Error('服务暂时不可用，请刷新重试')
    initialized.value = true
  } catch (e) { error.value = e instanceof Error ? e.message : '服务暂时不可用，请刷新重试' }
})
onUnmounted(clearPhoto)
</script>

<template>
  <main class="shell">
    <header>
      <div><span class="eyebrow">NJU · CLOUD ATTENDANCE</span><h1>{{ titles[mode] }}</h1></div>
      <button v-if="loggedIn" class="ghost" :disabled="busy" @click="logout"><van-icon aria-hidden="true" name="sign" /> 退出</button>
    </header>
    <div v-if="message" class="notice success" role="status">{{ message }}</div>
    <div v-if="error" class="notice error" role="alert">{{ error }}</div>

    <section v-if="mode === 'home'" class="hero">
      <div class="camera-mark"><van-icon aria-hidden="true" name="photograph" /></div>
      <h2>拍照上传</h2>
      <p>身份核验尚未开放</p>
      <label class="upload">
        <input type="file" accept="image/jpeg,image/png,image/webp" capture="user" aria-label="签到照片" @change="selectPhoto">
        <span><van-icon aria-hidden="true" name="photograph" /> {{ photo ? photo.name : '拍照或选择照片' }}</span>
      </label>
      <img v-if="preview" class="preview" :src="preview" alt="待上传照片预览">
      <button class="primary" :disabled="busy || !initialized || !photo" @click="anonymousCheckin">
        <van-icon aria-hidden="true" name="upgrade" /> {{ busy ? '上传中…' : '上传签到照片' }}
      </button>
      <div class="actions">
        <button @click="go('register')"><van-icon aria-hidden="true" name="add-o" /> 注册账号</button>
        <button v-if="!loggedIn" @click="go('login')"><van-icon aria-hidden="true" name="user-o" /> 登录</button>
        <button v-else @click="go('profile')"><van-icon aria-hidden="true" name="user-o" /> 个人中心</button>
      </div>
      <div v-if="job" class="job">
        <b>任务已创建</b><small>ID：{{ job.id }}</small><small>{{ job.message }}</small>
        <button class="link" :disabled="busy" @click="refreshJob"><van-icon aria-hidden="true" name="replay" /> 刷新状态</button>
      </div>
    </section>

    <form v-else-if="mode === 'register'" @submit.prevent="register">
      <label>姓名<input v-model="form.name" maxlength="40" autocomplete="name" required></label>
      <label>学号/工号<input v-model="form.student_id" maxlength="32" pattern="[A-Za-z0-9_-]+" autocomplete="off" required></label>
      <label>账号<input v-model="form.username" minlength="3" maxlength="32" pattern="[A-Za-z0-9_-]+" autocomplete="username" required></label>
      <label>密码<input v-model="form.password" type="password" minlength="8" maxlength="128" placeholder="至少 8 位" autocomplete="new-password" required></label>
      <label class="upload">
        <input type="file" accept="image/jpeg,image/png,image/webp" capture="user" aria-label="标准照片" @change="selectPhoto">
        <span><van-icon aria-hidden="true" name="photograph" /> {{ photo ? photo.name : '上传标准照片' }}</span>
      </label>
      <img v-if="preview" class="preview" :src="preview" alt="待上传照片预览">
      <label class="check"><input v-model="form.consent" type="checkbox" required>我同意照片用于身份核验；标准照片保留至本人删除，临时签到照片保留 24 小时。</label>
      <button class="primary" :disabled="busy || !initialized || !photo || !form.consent">
        <van-icon aria-hidden="true" name="add-o" /> {{ busy ? '提交中…' : '创建账号并上传' }}
      </button>
      <button type="button" class="link" @click="go('home')"><van-icon aria-hidden="true" name="arrow-left" /> 返回签到</button>
    </form>

    <form v-else-if="mode === 'login'" @submit.prevent="login">
      <label>账号<input v-model="loginForm.username" maxlength="32" autocomplete="username" required></label>
      <label>密码<input v-model="loginForm.password" type="password" maxlength="128" autocomplete="current-password" required></label>
      <button class="primary" :disabled="busy || !initialized">{{ busy ? '登录中…' : '登录' }}</button>
      <button type="button" class="link" @click="go('register')">注册账号</button>
      <button type="button" class="link" @click="go('home')"><van-icon aria-hidden="true" name="arrow-left" /> 返回签到</button>
    </form>

    <section v-else-if="mode === 'profile'">
      <div class="profile">
        <div class="avatar">{{ me?.name?.slice(0, 1) }}</div>
        <div><h2>{{ me?.name }}</h2><p>{{ me?.student_id }} · {{ me?.username }}</p></div>
      </div>
      <h3>我的照片</h3>
      <p v-if="!photos.length" class="sub">暂无照片</p>
      <div v-for="item in photos" :key="item.id" class="row">
        <img class="thumbnail" :src="`/api/photos/${item.id}`" alt="我的标准照片">
        <span>标准照片<br><small>{{ new Date(item.created_at).toLocaleString('zh-CN') }}</small></span>
        <b :class="item.status">{{ item.status === 'uploaded' ? '已上传，待核验' : item.status }}</b>
        <button class="delete" :disabled="busy" aria-label="删除照片" title="删除照片" @click="deletePhoto(item.id)"><van-icon aria-hidden="true" name="delete-o" /></button>
      </div>
      <label class="upload">
        <input type="file" accept="image/jpeg,image/png,image/webp" capture="user" aria-label="新标准照片" @change="selectPhoto">
        <span><van-icon aria-hidden="true" name="photograph" /> {{ photo ? photo.name : '上传新照片' }}</span>
      </label>
      <img v-if="preview" class="preview" :src="preview" alt="待上传照片预览">
      <button class="primary" :disabled="busy || !initialized || !photo" @click="uploadStandard"><van-icon aria-hidden="true" name="upgrade" /> 上传照片</button>
      <button class="secondary" @click="go('records')"><van-icon aria-hidden="true" name="records-o" /> 查看签到记录</button>
      <button class="link" @click="go('home')"><van-icon aria-hidden="true" name="arrow-left" /> 返回签到</button>
    </section>

    <section v-else-if="mode === 'records'">
      <p v-if="!records.length" class="sub">暂无记录。</p>
      <div v-for="item in records" :key="item.id">
        <span>{{ item.event_id }}</span><b>{{ new Date(item.checked_at).toLocaleString('zh-CN') }}</b>
      </div>
      <button class="link" @click="go('profile')"><van-icon aria-hidden="true" name="arrow-left" /> 返回我的照片</button>
    </section>
  </main>
</template>
