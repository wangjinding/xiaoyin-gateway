// 智能体 —— 接口封装（只服务内嵌的完整 DSH）
//
// 智能体这一层只有三件事：登记、权限、入口。
// 执行与界面都在内嵌的 DeepSeek Harness（/agent/）里，网关不参与。

import { getToken } from '../api'

export interface AgentItem {
  slug: string
  display_name: string
  description: string
  params: Record<string, any>
  access: { roles: string[]; users: string[] }
  access_scope: string
  status: 'draft' | 'published' | 'retired'
  created_at: string
  updated_at: string
}

export interface AgentListResp {
  agents: AgentItem[]
  max_agents: number
  active: number
  dsh: { ready: boolean; port: number }
}

export interface DshEntry {
  url: string
  ready: boolean
  port: number
}

function authHeaders(): Record<string, string> {
  return { Authorization: `Bearer ${getToken()}` }
}

async function req<T>(path: string, init: RequestInit = {}): Promise<T> {
  const r = await fetch(path, {
    ...init,
    headers: { 'Content-Type': 'application/json', ...authHeaders(), ...(init.headers || {}) },
  })
  const body = await r.json().catch(() => null)
  if (!r.ok) {
    const msg = body?.error?.message || body?.detail || `HTTP ${r.status}`
    throw new Error(typeof msg === 'string' ? msg : JSON.stringify(msg))
  }
  return body as T
}

export const listAgents = () => req<AgentListResp>('/agents')

export const createAgent = (body: Record<string, any>) =>
  req<AgentItem>('/agents', { method: 'POST', body: JSON.stringify(body) })

export const updateAgent = (slug: string, patch: Record<string, any>) =>
  req<AgentItem>(`/agents/${slug}`, { method: 'PUT', body: JSON.stringify(patch) })

export const retireAgent = (slug: string) =>
  req<AgentItem>(`/agents/${slug}`, { method: 'DELETE' })

export const restoreAgent = (slug: string) =>
  req<AgentItem>(`/agents/${slug}/restore`, { method: 'POST' })

/** 完整 DSH 的访问地址（带运行时 token，只有后端读得到）。 */
export const dshEntry = () => req<DshEntry>('/agents/dsh/entry')
