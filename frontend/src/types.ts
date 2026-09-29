export type ApiClient = <T>(path: string, options?: RequestInit) => Promise<T>
export interface User { id: string; name: string; student_id: string; username: string; role: string; status: string; enrolled?: boolean }
export interface Job {
  id: string; token?: string; kind: string; status: string; message: string; result_code?: string
  result?: { name: string; event_name: string; checked_at: string }
}
export interface Photo { id: string; status: string; created_at: string; reason?: string; job?: Job }
export interface Attendance { id: string; event_id: string; event_name: string; checked_at: string }
export interface EventItem { id: string; name: string; status: string; starts_at: string; ends_at: string; phase?: string; count?: number }
export const pending = (job: Job | null) => Boolean(job && ['queued', 'processing'].includes(job.status))
export const photoStatus = (status: string) => ({ pending: '正在核验', ready: '已录入', rejected: '未通过', superseded: '已被替换', uploaded: '需要重新核验' }[status] || status)
export const dateTime = (value: string) => new Date(value).toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai', hour12: false })
