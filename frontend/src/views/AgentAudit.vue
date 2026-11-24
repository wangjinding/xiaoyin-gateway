<template>
  <div class="audit">
    <div class="head">
      <h2>{{ t('agentAudit.title') }}</h2>
      <div class="hint">{{ t('agentAudit.hint') }}</div>
    </div>

    <el-table :data="users" v-loading="loading" size="small" @row-click="openUser" row-key="name">
      <el-table-column prop="name" :label="t('agentAudit.user')" width="160" />
      <el-table-column prop="uid" label="uid" width="90" />
      <el-table-column prop="workspace" :label="t('agentAudit.workspace')" min-width="180" />
      <el-table-column prop="sessions" :label="t('agentAudit.sessions')" width="100" />
      <el-table-column prop="tokens" :label="t('agentAudit.tokens')" width="120" />
      <el-table-column :label="t('agentAudit.lastActive')" min-width="180">
        <template #default="{ row }">{{ fmt(row.lastActive) }}</template>
      </el-table-column>
      <el-table-column width="100">
        <template #default="{ row }">
          <el-button link type="primary" @click.stop="openUser(row)">{{ t('agentAudit.view') }}</el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-drawer v-model="drawer" :title="current ? `${current.name} · ${current.workspace}` : ''" size="60%">
      <div v-if="current" class="drawer-body">
        <el-table :data="sessions" size="small" @row-click="openSession" highlight-current-row>
          <el-table-column prop="title" :label="t('agentAudit.sessionTitle')" min-width="200" />
          <el-table-column prop="tokens" :label="t('agentAudit.tokens')" width="110" />
          <el-table-column :label="t('agentAudit.updated')" width="180">
            <template #default="{ row }">{{ fmt(row.updated) }}</template>
          </el-table-column>
        </el-table>

        <div v-if="events.length" class="timeline">
          <div v-for="(e, i) in events" :key="i" class="evt" :class="e.type">
            <div class="tag">{{ e.type }}</div>
            <div class="content">
              <template v-if="e.type === 'tool'">
                <div class="tool-name">{{ e.name }}</div>
                <pre>{{ pretty(e.content) }}</pre>
              </template>
              <template v-else>{{ e.content }}</template>
            </div>
            <div class="time">{{ fmt(e.ts) }}</div>
          </div>
        </div>
        <el-empty v-else-if="currentSession" :description="t('agentAudit.noEvents')" />
      </div>
    </el-drawer>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { dshEntry } from '../lib/agents'

const { t } = useI18n()

interface UserRow { name: string; uid: number; workspace: string; sessions: number; tokens: number; lastActive: string | null }
interface SessionRow { id: string; title: string; tokens: number; updated: string }
interface EventRow { type: string; content?: string; name?: string; ts?: string }

const users = ref<UserRow[]>([])
const sessions = ref<SessionRow[]>([])
const events = ref<EventRow[]>([])
const loading = ref(true)
const drawer = ref(false)
const current = ref<UserRow | null>(null)
const currentSession = ref<SessionRow | null>(null)
let token = ''

function fmt(v?: string | null) {
  if (!v) return '—'
  return new Date(v).toLocaleString('zh-CN', { hour12: false })
}

function pretty(s?: string) {
  try {
    return JSON.stringify(JSON.parse(s || '{}'), null, 2)
  } catch {
    return s || ''
  }
}

async function api(path: string) {
  const res = await fetch(path, { headers: { Authorization: `Bearer ${token}` } })
  if (!res.ok) throw new Error(`${res.status}`)
  return res.json()
}

async function load() {
  loading.value = true
  try {
    const entry = await dshEntry()
    token = new URL(entry.url, location.origin).searchParams.get('token') || ''
    const j = await api('/agent/api/admin/users')
    users.value = j.users || []
  } catch {
    users.value = []
  } finally {
    loading.value = false
  }
}

async function openUser(row: UserRow) {
  current.value = row
  currentSession.value = null
  events.value = []
  drawer.value = true
  try {
    const j = await api(`/agent/api/admin/users/${row.name}/sessions`)
    sessions.value = j.sessions || []
  } catch {
    sessions.value = []
  }
}

async function openSession(row: SessionRow) {
  if (!current.value) return
  currentSession.value = row
  try {
    const j = await api(`/agent/api/admin/sessions/${current.value.name}/${row.id}/events`)
    events.value = j.events || []
  } catch {
    events.value = []
  }
}

onMounted(load)
</script>

<style scoped>
.audit { padding: 20px; }
.head { margin-bottom: 14px; }
.head h2 { margin: 0 0 4px; font-size: 18px; }
.hint { color: var(--el-text-color-secondary); font-size: 13px; }
.drawer-body { display: flex; flex-direction: column; gap: 16px; }
.timeline { display: flex; flex-direction: column; gap: 8px; max-height: 52vh; overflow: auto; }
.evt { display: grid; grid-template-columns: 70px 1fr 150px; gap: 10px; padding: 8px 10px; border-radius: 8px; background: var(--el-fill-color-light); }
.evt.user .tag { color: #1f6feb; }
.evt.assistant .tag { color: #16a34a; }
.evt.tool .tag { color: #b45309; }
.tag { font-size: 12px; font-weight: 600; }
.content { white-space: pre-wrap; word-break: break-word; font-size: 13px; }
.content pre { margin: 4px 0 0; font-size: 12px; max-height: 180px; overflow: auto; }
.tool-name { font-family: ui-monospace, Menlo, monospace; font-size: 12px; color: #b45309; }
.time { font-size: 12px; color: var(--el-text-color-secondary); text-align: right; }
</style>
