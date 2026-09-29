<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { showConfirmDialog } from 'vant'
import { dateTime, photoStatus, type ApiClient, type EventItem, type Photo, type User } from './types'

const props = defineProps<{ request: ApiClient; run: (action: () => Promise<void>) => Promise<void>; busy: boolean }>()
const users = ref<User[]>([])
const events = ref<EventItem[]>([])
const overview = ref<{ worker_ready: boolean; pending_jobs: number; queue_capacity: number; records: number } | null>(null)
const error = ref('')
const info = ref('')
const galleryUser = ref<User | null>(null)
const gallery = ref<Photo[]>([])
const selectedEvent = ref<EventItem | null>(null)
const records = ref<{ id: string; name: string; student_id: string; checked_at: string }[]>([])
function localInput(date: Date) { return new Date(date.getTime() - date.getTimezoneOffset() * 60000).toISOString().slice(0, 16) }
const form = ref({ name: '', start: localInput(new Date(Date.now() - 300000)), end: localInput(new Date(Date.now() + 7200000)) })
async function load() {
  error.value = ''
  try {
    const [u, e, o] = await Promise.all([
      props.request<{ items: User[] }>('/api/admin/users'),
      props.request<{ items: EventItem[] }>('/api/admin/events'),
      props.request<NonNullable<typeof overview.value>>('/api/admin/overview'),
    ])
    users.value = u.items; events.value = e.items; overview.value = o
  } catch (e) { error.value = e instanceof Error ? e.message : '加载失败' }
}
async function createEvent() {
  await props.run(async () => {
    await props.request('/api/admin/events', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ name: form.value.name, starts_at: new Date(form.value.start).toISOString(), ends_at: new Date(form.value.end).toISOString() }) })
    form.value.name = ''; info.value = '活动已创建，可以复制链接邀请大家签到。'; await load()
  })
}
async function confirm(message: string) { try { await showConfirmDialog({ title: '确认操作', message }); return true } catch { return false } }
async function cancel(event: EventItem) {
  if (!await confirm(`取消“${event.name}”后，将停止接收和处理本次签到。已有记录保留。`)) return
  await props.run(async () => { await props.request(`/api/admin/events/${event.id}/cancel`, { method: 'POST' }); await load() })
}
function link(event: EventItem) { return `${location.origin}/?event=${event.id}` }
async function copyLink(event: EventItem) {
  try { await navigator.clipboard.writeText(link(event)); info.value = '签到链接已复制' }
  catch { info.value = '请选中下方链接手动复制' }
}
async function viewRecords(event: EventItem) {
  await props.run(async () => { records.value = (await props.request<{ items: typeof records.value }>(`/api/admin/events/${event.id}/records`)).items; selectedEvent.value = event })
}
async function toggle(user: User) {
  if (!await confirm(`${user.status === 'active' ? '停用' : '启用'} ${user.name} 的账号？停用后无法登录或签到。`)) return
  await props.run(async () => { await props.request(`/api/admin/users/${user.id}`, { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ status: user.status === 'active' ? 'disabled' : 'active' }) }); await load() })
}
async function removeUser(user: User) {
  if (!await confirm(`永久删除 ${user.name} 的账号、照片和签到记录？此操作无法撤销。`)) return
  await props.run(async () => { await props.request(`/api/admin/users/${user.id}`, { method: 'DELETE' }); galleryUser.value = null; selectedEvent.value = null; await load() })
}
async function showPhotos(user: User) {
  await props.run(async () => { gallery.value = (await props.request<{ items: Photo[] }>(`/api/admin/users/${user.id}/photos`)).items; galleryUser.value = user })
}
async function removePhoto(photo: Photo) {
  if (!await confirm('永久删除这张照片及其人脸特征？删除当前标准照后，该人员需要重新录入。')) return
  await props.run(async () => {
    await props.request(`/api/admin/photos/${photo.id}`, { method: 'DELETE' })
    gallery.value = gallery.value.filter(p => p.id !== photo.id); await load()
  })
}
onMounted(load)
</script>

<template>
  <section>
    <div v-if="error" class="notice error" role="alert">{{ error }}</div>
    <div v-if="info" class="notice success" role="status">{{ info }}</div>
    <div v-if="overview" class="summary-grid">
      <div><b>{{ overview.worker_ready ? '就绪' : '准备中' }}</b><small>识别服务</small></div>
      <div><b>{{ overview.pending_jobs }} / {{ overview.queue_capacity }}</b><small>待处理任务</small></div>
      <div><b>{{ overview.records }}</b><small>签到记录</small></div>
    </div>
    <button class="secondary" :disabled="busy" @click="load">刷新管理信息</button>
    <h2 class="section-title">创建签到活动</h2>
    <form @submit.prevent="createEvent">
      <label>活动名称<input v-model="form.name" maxlength="100" required></label>
      <div class="form-grid">
        <label>开始时间<input v-model="form.start" type="datetime-local" required></label>
        <label>结束时间<input v-model="form.end" type="datetime-local" required></label>
      </div>
      <button class="primary" :disabled="busy">创建活动</button>
    </form>
    <h2 class="section-title">活动与签到记录</h2>
    <p v-if="!events.length" class="sub">暂无活动，请先创建。</p>
    <article v-for="event in events" :key="event.id" class="event-card">
      <h3>{{ event.name }}</h3>
      <p class="sub">{{ dateTime(event.starts_at) }} — {{ dateTime(event.ends_at) }}</p>
      <p>{{ event.status === 'cancelled' ? '已取消' : new Date(event.ends_at).getTime() < Date.now() ? '已结束' : '已发布' }} · {{ event.count }} 人签到</p>
      <label class="small-label">签到链接<input :value="link(event)" readonly aria-label="签到链接"></label>
      <div class="button-row">
        <button :disabled="busy" @click="copyLink(event)">复制链接</button>
        <button :disabled="busy" @click="viewRecords(event)">查看记录</button>
        <button v-if="event.status !== 'cancelled'" class="danger-text" :disabled="busy" @click="cancel(event)">取消活动</button>
      </div>
    </article>
    <section v-if="selectedEvent" class="event-card">
      <h3>{{ selectedEvent.name }} · 签到名单</h3>
      <p v-if="!records.length" class="sub">暂无签到记录。</p>
      <div v-for="item in records" :key="item.id" class="record-row">
        <div><b>{{ item.name }}</b><small>{{ item.student_id }}</small></div><time>{{ dateTime(item.checked_at) }}</time>
      </div>
    </section>
    <h2 class="section-title">人员与照片库</h2>
    <article v-for="user in users" :key="user.id" class="event-card">
      <h3>{{ user.name }} <small>{{ user.role === 'admin' ? '管理员' : '用户' }}</small></h3>
      <p class="sub">{{ user.student_id }} · {{ user.username }}</p>
      <p>{{ user.status === 'disabled' ? '账号已停用' : user.enrolled ? '人脸已录入' : '尚未完成人脸录入' }}</p>
      <div class="button-row">
        <button :disabled="busy" @click="showPhotos(user)">查看照片</button>
        <button v-if="user.role !== 'admin'" :disabled="busy" @click="toggle(user)">{{ user.status === 'active' ? '停用' : '启用' }}</button>
        <button v-if="user.role !== 'admin'" class="danger-text" :disabled="busy" @click="removeUser(user)">删除账号</button>
      </div>
    </article>
    <section v-if="galleryUser" class="event-card">
      <h3>{{ galleryUser.name }} · 标准照片</h3>
      <p v-if="!gallery.length" class="sub">暂无照片。</p>
      <div v-for="photo in gallery" :key="photo.id" class="gallery-row">
        <img :src="`/api/admin/photos/${photo.id}`" alt="人员标准照片" class="thumbnail">
        <div><b>{{ photoStatus(photo.status) }}</b><small v-if="photo.reason">{{ photo.reason }}</small></div>
        <button class="danger-text" :disabled="busy" @click="removePhoto(photo)">删除</button>
      </div>
    </section>
  </section>
</template>
