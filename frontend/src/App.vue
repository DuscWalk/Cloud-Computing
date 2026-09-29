<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { showConfirmDialog, Icon as VanIcon } from 'vant'
import AdminPanel from './AdminPanel.vue'
import { dateTime, pending, photoStatus, type Attendance, type EventItem, type Job, type Photo, type User } from './types'

type Page = 'home' | 'register' | 'login' | 'profile' | 'records' | 'admin'
const csrf = ref('')
const me = ref<User | null>(null)
const mode = ref<Page>('home')
const busy = ref(false)
const preparing = ref(false)
const initialized = ref(false)
const message = ref('')
const error = ref('')
const job = ref<Job | null>(null)
const photos = ref<Photo[]>([])
const records = ref<Attendance[]>([])
const events = ref<EventItem[]>([])
const selectedEvent = ref(new URLSearchParams(location.search).get('event') || '')
const form = ref({ name: '', student_id: '', username: '', password: '', consent: false })
const loginForm = ref({ username: '', password: '' })
const photo = ref<File | null>(null)
const preview = ref('')
const requestKey = ref('')
const loggedIn = computed(() => Boolean(me.value))
const activeEvent = computed(() => events.value.find(e => e.id === selectedEvent.value))
const canCheckin = computed(() => activeEvent.value?.phase === 'open' && !pending(job.value))
const titles = { home: '手机人脸签到', register: '注册并录入人脸', login: '登录', profile: '我的照片', records: '签到记录', admin: '签到管理' }
let timer: ReturnType<typeof setTimeout> | undefined
let generation = 0
let selection = 0
let pollAttempts = 0

async function api<T>(path: string, options: RequestInit = {}): Promise<T> {
  const headers = new Headers(options.headers)
  if (csrf.value && options.method && options.method !== 'GET') headers.set('X-CSRF-Token', csrf.value)
  const response = await fetch(path, { credentials: 'same-origin', ...options, headers })
  const data = response.status === 204 ? null : await response.json().catch(() => ({}))
  if (!response.ok) throw new Error(typeof data?.detail === 'string' ? data.detail : '请求失败，请稍后重试')
  return data as T
}
function clearPhoto() {
  selection++
  if (preview.value) URL.revokeObjectURL(preview.value)
  preview.value = ''; photo.value = null; requestKey.value = ''; preparing.value = false
}
function changeEvent() { requestKey.value = crypto.randomUUID() }
async function selectPhoto(event: Event) {
  clearPhoto(); error.value = ''; message.value = ''
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]; input.value = ''
  if (!file) return
  if (!['image/jpeg', 'image/png', 'image/webp'].includes(file.type)) { error.value = '请选择 JPEG、PNG 或 WebP 照片'; return }
  if (file.size > 20 * 1024 * 1024) { error.value = '原照片不能超过 20 MB'; return }
  const ticket = selection
  preparing.value = true
  let bitmap: ImageBitmap | undefined
  try {
    bitmap = await createImageBitmap(file)
    if (bitmap.width * bitmap.height > 50000000) throw new Error('照片分辨率过大，请调整相机设置')
    const scale = Math.min(1, 1280 / Math.max(bitmap.width, bitmap.height))
    const canvas = document.createElement('canvas')
    canvas.width = Math.round(bitmap.width * scale); canvas.height = Math.round(bitmap.height * scale)
    canvas.getContext('2d')!.drawImage(bitmap, 0, 0, canvas.width, canvas.height)
    const blob = await new Promise<Blob>((resolve, reject) => canvas.toBlob(b => b ? resolve(b) : reject(new Error('照片处理失败')), 'image/jpeg', 0.9))
    if (ticket !== selection) return
    if (blob.size > 5 * 1024 * 1024) throw new Error('照片压缩后仍超过 5 MB，请降低分辨率')
    photo.value = new File([blob], 'photo.jpg', { type: 'image/jpeg' })
    preview.value = URL.createObjectURL(blob); requestKey.value = crypto.randomUUID()
  } catch (e) { if (ticket === selection) error.value = e instanceof Error ? e.message : '无法读取照片，请重新拍摄' }
  finally { bitmap?.close(); if (ticket === selection) preparing.value = false }
}
function formData(fields: Record<string, string | boolean>, file: File | null) {
  const body = new FormData()
  Object.entries(fields).forEach(([key, value]) => body.append(key, String(value)))
  if (file) body.append('photo', file)
  return body
}
async function perform(action: () => Promise<void>) {
  if (busy.value || preparing.value || !initialized.value) return
  busy.value = true; error.value = ''; message.value = ''
  try {
    csrf.value = (await api<{ csrf_token: string }>('/api/auth/csrf')).csrf_token
    await action()
  } catch (e) { error.value = e instanceof Error ? e.message : '连接失败，请稍后重试' }
  finally { busy.value = false }
}
function rememberJob() {
  try { if (job.value) sessionStorage.setItem('attendance-job', JSON.stringify(job.value)); else sessionStorage.removeItem('attendance-job') } catch { /* Storage can be disabled in private browsers. */ }
}
function stopPolling() { clearTimeout(timer); generation++ }
function startJob(value: Job) {
  stopPolling(); job.value = value; pollAttempts = 0; rememberJob()
  if (pending(value)) timer = setTimeout(() => pollJob(generation), 900)
}
async function pollJob(ticket: number) {
  if (!job.value || ticket !== generation) return
  const current = job.value
  try {
    const data = await api<Job>(`/api/jobs/${current.id}`, { headers: current.token ? { 'X-Job-Token': current.token } : {} })
    if (ticket !== generation) return
    job.value = { ...data, token: current.token }; rememberJob()
    if (!pending(data)) { if (mode.value === 'profile' && me.value) await loadPhotos(false); return }
  } catch (e) {
    if (ticket !== generation) return
    error.value = '结果查询暂时中断，可点击“刷新结果”重试。'
  }
  pollAttempts++
  if (pollAttempts < 60 && ticket === generation) timer = setTimeout(() => pollJob(ticket), Math.min(5000, 1000 + pollAttempts * 250))
}
function refreshJob() { clearTimeout(timer); pollAttempts = 0; void pollJob(generation) }
function register() { return perform(async () => {
  const data = await api<{ job: Job }>('/api/auth/register', { method: 'POST', body: formData(form.value, photo.value) })
  startJob(data.job); message.value = '账号已创建，正在核验标准照片。请登录查看照片。'
  loginForm.value.username = form.value.username; form.value.password = ''; form.value.consent = false
  clearPhoto(); mode.value = 'login'
}) }
function login() { return perform(async () => {
  me.value = (await api<{ user: User }>('/api/auth/login', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(loginForm.value) })).user
  if (job.value?.kind === 'capture' && !pending(job.value)) { stopPolling(); job.value = null; rememberJob() }
  loginForm.value.password = ''; message.value = '登录成功'; mode.value = 'profile'; clearPhoto(); await loadPhotos()
}) }
function logout() { return perform(async () => {
  await api('/api/auth/logout', { method: 'POST' }); me.value = null; photos.value = []; records.value = []
  stopPolling(); job.value = null; rememberJob(); clearPhoto(); mode.value = 'home'; message.value = '已退出登录'; await loadEvents()
}) }
function uploadStandard() { return perform(async () => {
  const data = await api<{ job: Job }>('/api/me/photos', { method: 'POST', body: formData({}, photo.value) })
  startJob(data.job); clearPhoto(); await loadPhotos(false)
}) }
function reindex(item: Photo) { return perform(async () => {
  const data = await api<{ job: Job }>(`/api/me/photos/${item.id}/reindex`, { method: 'POST' }); startJob(data.job); await loadPhotos(false)
}) }
function anonymousCheckin() { return perform(async () => {
  if (!selectedEvent.value) throw new Error('请选择签到活动')
  if (!requestKey.value) requestKey.value = crypto.randomUUID()
  const data = await api<Job>('/api/uploads', { method: 'POST', headers: { 'Idempotency-Key': requestKey.value }, body: formData({ event_id: selectedEvent.value }, photo.value) })
  startJob(data); clearPhoto()
}) }
async function deletePhoto(id: string) {
  try { await showConfirmDialog({ title: '删除照片', message: '照片及其人脸特征将被删除，无法继续用于签到。' }) } catch { return }
  await perform(async () => {
    await api(`/api/me/photos/${id}`, { method: 'DELETE' }); await loadPhotos(false)
    if (job.value?.kind === 'enrollment') { stopPolling(); job.value = null; rememberJob() }
    message.value = '照片已删除'
  })
}
async function loadPhotos(resume = true) {
  if (!me.value) return
  photos.value = (await api<{ items: Photo[] }>('/api/me/photos')).items
  const inProgress = photos.value.map(p => p.job).find(j => j && pending(j))
  if (resume && inProgress && (!job.value || job.value.id !== inProgress.id)) startJob(inProgress)
}
async function loadEvents() {
  events.value = (await api<{ items: EventItem[] }>('/api/events')).items
  if (selectedEvent.value && !events.value.some(e => e.id === selectedEvent.value)) {
    try { events.value.unshift(await api<EventItem>(`/api/events/${encodeURIComponent(selectedEvent.value)}`)) }
    catch { error.value = '链接中的活动不存在，请选择其他活动'; selectedEvent.value = '' }
  }
  if (!selectedEvent.value) selectedEvent.value = events.value.find(e => e.phase === 'open')?.id || events.value[0]?.id || ''
}
async function go(next: Page) {
  if (busy.value) return
  error.value = ''; message.value = ''; clearPhoto(); mode.value = next
  try {
    if (next === 'profile') await loadPhotos()
    if (next === 'records') records.value = (await api<{ items: Attendance[] }>('/api/me/attendance')).items
    if (next === 'home') await loadEvents()
  } catch (e) { error.value = e instanceof Error ? e.message : '加载失败' }
}
onMounted(async () => {
  try {
    csrf.value = (await api<{ csrf_token: string }>('/api/auth/csrf')).csrf_token
    const response = await fetch('/api/me', { credentials: 'same-origin' })
    if (response.ok) me.value = await response.json()
    else if (response.status !== 401) throw new Error('服务暂时不可用，请刷新重试')
    await loadEvents(); initialized.value = true
    try { const saved = sessionStorage.getItem('attendance-job'); if (saved) { const value = JSON.parse(saved); if (value.id && value.status && pending(value)) startJob(value) } } catch { /* Ignore obsolete tab state. */ }
  } catch (e) { error.value = e instanceof Error ? e.message : '服务暂时不可用，请刷新重试' }
})
onUnmounted(() => { clearPhoto(); stopPolling() })
</script>

<template>
  <main class="shell">
    <header>
      <div><span class="eyebrow">NJU · CLOUD ATTENDANCE</span><h1>{{ titles[mode] }}</h1></div>
      <button v-if="loggedIn" class="ghost" :disabled="busy" @click="logout"><van-icon aria-hidden="true" name="sign" /> 退出</button>
    </header>
    <div v-if="message" class="notice success" role="status">{{ message }}</div>
    <div v-if="error" class="notice error" role="alert">{{ error }}</div>
    <section v-if="job" class="job-result" :class="pending(job) ? 'waiting' : job.status === 'succeeded' ? 'success' : 'error'" role="status" aria-live="polite">
      <b>{{ job.kind === 'enrollment' ? '人脸录入' : '签到结果' }}</b><p>{{ job.message }}</p>
      <p v-if="job.result">{{ job.result.name }} · {{ job.result.event_name }}<br>{{ dateTime(job.result.checked_at) }}</p>
      <button v-if="pending(job)" class="link" @click="refreshJob"><van-icon aria-hidden="true" name="replay" /> 刷新结果</button>
    </section>

    <section v-if="mode === 'home'" class="hero">
      <div class="camera-mark"><van-icon aria-hidden="true" name="photograph" /></div>
      <h2>拍照签到</h2><p>无需登录。请正对镜头，确保只有本人入镜。</p>
      <label>签到活动<select v-model="selectedEvent" @change="changeEvent">
        <option disabled value="">{{ events.length ? '请选择活动' : '暂无活动，请联系管理员' }}</option>
        <option v-for="event in events" :key="event.id" :value="event.id">{{ event.name }}{{ event.phase !== 'open' ? `（${event.phase === 'upcoming' ? '未开始' : event.phase === 'cancelled' ? '已取消' : '已结束'}）` : '' }}</option>
      </select></label>
      <p v-if="activeEvent" class="sub">{{ dateTime(activeEvent.starts_at) }} — {{ dateTime(activeEvent.ends_at) }}</p>
      <button class="link compact" :disabled="busy" @click="perform(loadEvents)">刷新活动</button>
      <label class="upload"><input type="file" accept="image/jpeg,image/png,image/webp" capture="user" aria-label="签到照片" @change="selectPhoto"><span><van-icon aria-hidden="true" name="photograph" /> {{ preparing ? '正在整理照片…' : photo ? '照片已选择，可重新拍摄' : '拍照或选择照片' }}</span></label>
      <img v-if="preview" class="preview" :src="preview" alt="待上传照片预览">
      <button class="primary" :disabled="busy || preparing || !initialized || !photo || !canCheckin" @click="anonymousCheckin"><van-icon aria-hidden="true" name="passed" /> {{ busy ? '提交中…' : pending(job) ? '正在处理…' : '开始签到' }}</button>
      <p class="privacy">照片仅用于本次身份核验，临时签到照片 24 小时后清理。</p>
      <div class="actions">
        <button @click="go('register')"><van-icon aria-hidden="true" name="add-o" /> 注册账号</button>
        <button v-if="!loggedIn" @click="go('login')"><van-icon aria-hidden="true" name="user-o" /> 登录</button>
        <button v-else @click="go('profile')"><van-icon aria-hidden="true" name="user-o" /> 个人中心</button>
      </div>
      <button v-if="me?.role === 'admin'" class="secondary" @click="go('admin')">管理活动与人员</button>
    </section>

    <form v-else-if="mode === 'register'" @submit.prevent="register">
      <p class="sub">填写基本信息，并上传一张清晰的本人正面单人照片。</p>
      <label>姓名<input v-model="form.name" maxlength="40" autocomplete="name" required></label>
      <label>学号/工号<input v-model="form.student_id" maxlength="32" pattern="[A-Za-z0-9_-]+" autocomplete="off" required></label>
      <label>账号<input v-model="form.username" minlength="3" maxlength="32" pattern="[A-Za-z0-9_-]+" autocomplete="username" required></label>
      <label>密码<input v-model="form.password" type="password" minlength="8" maxlength="128" placeholder="至少 8 位" autocomplete="new-password" required></label>
      <label class="upload"><input type="file" accept="image/jpeg,image/png,image/webp" capture="user" aria-label="标准照片" @change="selectPhoto"><span><van-icon aria-hidden="true" name="photograph" /> {{ preparing ? '正在整理照片…' : photo ? '照片已选择' : '上传标准照片' }}</span></label>
      <img v-if="preview" class="preview" :src="preview" alt="待上传照片预览">
      <label class="check"><input v-model="form.consent" type="checkbox" required>我同意照片与人脸特征用于本课程签到；标准照片保留至本人删除，临时签到照片保留 24 小时。</label>
      <button class="primary" :disabled="busy || preparing || !initialized || !photo || !form.consent">{{ busy ? '提交中…' : '创建账号并上传' }}</button>
      <button type="button" class="link" @click="go('home')">返回签到</button>
    </form>

    <form v-else-if="mode === 'login'" @submit.prevent="login">
      <label>账号<input v-model="loginForm.username" maxlength="32" autocomplete="username" required></label>
      <label>密码<input v-model="loginForm.password" type="password" maxlength="128" autocomplete="current-password" required></label>
      <button class="primary" :disabled="busy || !initialized">{{ busy ? '登录中…' : '登录' }}</button>
      <button type="button" class="link" @click="go('register')">注册账号</button>
      <button type="button" class="link" @click="go('home')">返回签到</button>
    </form>

    <section v-else-if="mode === 'profile'">
      <div class="profile"><div class="avatar">{{ me?.name?.slice(0, 1) }}</div><div><h2>{{ me?.name }}</h2><p>{{ me?.student_id }} · {{ me?.username }}</p></div></div>
      <h3>我的照片</h3><p class="sub">仅“已录入”的照片参与签到。换照核验成功后，原标准照自动停用。</p>
      <p v-if="!photos.length" class="sub">暂无照片，请上传标准照完成人脸录入。</p>
      <article v-for="item in photos" :key="item.id" class="photo-item">
        <div class="row"><img class="thumbnail" :src="`/api/photos/${item.id}`" alt="我的标准照片"><span>标准照片<br><small>{{ dateTime(item.created_at) }}</small></span><b :class="item.status">{{ photoStatus(item.status) }}</b><button class="delete" :disabled="busy" aria-label="删除照片" @click="deletePhoto(item.id)"><van-icon aria-hidden="true" name="delete-o" /></button></div>
        <p v-if="item.reason" class="photo-reason">{{ item.reason }}</p>
        <button v-if="['uploaded', 'rejected'].includes(item.status)" class="link compact" :disabled="busy" @click="reindex(item)">重新核验</button>
      </article>
      <label class="upload"><input type="file" accept="image/jpeg,image/png,image/webp" capture="user" aria-label="新标准照片" @change="selectPhoto"><span><van-icon aria-hidden="true" name="photograph" /> {{ preparing ? '正在整理照片…' : photo ? '照片已选择' : '上传新标准照' }}</span></label>
      <img v-if="preview" class="preview" :src="preview" alt="待上传照片预览">
      <button class="primary" :disabled="busy || preparing || !initialized || !photo || pending(job)" @click="uploadStandard">上传并核验</button>
      <button class="secondary" @click="go('records')">查看签到记录</button>
      <button v-if="me?.role === 'admin'" class="secondary" @click="go('admin')">管理活动与人员</button>
      <button class="link" @click="go('home')">返回签到</button>
    </section>

    <section v-else-if="mode === 'records'">
      <p v-if="!records.length" class="sub">暂无记录。</p>
      <article v-for="item in records" :key="item.id" class="record-row"><div><b>{{ item.event_name }}</b><small>签到成功</small></div><time>{{ dateTime(item.checked_at) }}</time></article>
      <button class="secondary" @click="go('records')">刷新记录</button><button class="link" @click="go('profile')">返回我的照片</button>
    </section>

    <section v-else-if="mode === 'admin' && me?.role === 'admin'"><AdminPanel :request="api" :run="perform" :busy="busy" /><button class="link" @click="go('profile')">返回个人中心</button></section>
  </main>
</template>
