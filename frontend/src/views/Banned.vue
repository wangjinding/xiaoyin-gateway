<template>
  <div class="page page-col">
    <!-- ── 手动封禁 ─────────────────────────────────────────── -->
    <div class="card">
      <div class="card-h">
        <Icon name="ban" :size="15" />
        <b>{{ t('banned.manualTitle') }}</b>
        <span class="sub">{{ t('banned.manualSub') }}</span>
      </div>

      <div class="ban-form">
        <el-input
          v-model="newIp" size="small" class="w-ip" clearable
          :placeholder="t('banned.ipPlaceholder')" @keyup.enter="doBan"
        />
        <el-select v-model="newDur" size="small" class="w-dur">
          <el-option
            v-for="o in DURATIONS" :key="o.k" :value="o.k"
            :label="t(`banned.dur.${o.k}`)"
          />
        </el-select>
        <el-input
          v-model="newNote" size="small" class="w-note" clearable
          :placeholder="t('banned.notePlaceholder')" @keyup.enter="doBan"
        />
        <el-button type="primary" size="small" :loading="banning" @click="doBan">
          <Icon name="ban" :size="13" /><span>{{ t('banned.doBan') }}</span>
        </el-button>
      </div>
      <div class="form-hint">
        <Icon name="bell" :size="12" />
        <span>{{ t('banned.manualHint') }}</span>
      </div>
    </div>

    <!-- ── 封禁列表 ─────────────────────────────────────────── -->
    <div class="card">
      <div class="card-h">
        <b>{{ t('banned.title') }}</b>
        <span class="sub">{{ t('banned.count', { n: items.length }) }}</span>
        <div class="pager">
          <el-button size="small" :loading="loading" @click="reload">
            <Icon name="refresh" :size="13" /><span>{{ t('common.refresh') }}</span>
          </el-button>
          <el-button size="small" type="danger" plain :disabled="!items.length" @click="clearAll">
            <Icon name="trash" :size="13" /><span>{{ t('banned.clearAll') }}</span>
          </el-button>
        </div>
      </div>

      <div class="warn-bar">
        <Icon name="ban" :size="14" />
        <span>{{ t('banned.rule', { n: limit, mins: banMinutes }) }}</span>
      </div>

      <div v-if="items.length" class="ban-list">
        <div v-for="b in items" :key="b.ip" class="ban-row">
          <span class="dot" :class="{ perm: b.permanent }" />
          <div class="ban-main">
            <div class="ban-top">
              <b class="code ban-ip">{{ b.ip }}</b>
              <el-tag v-if="b.permanent" size="small" type="danger" effect="plain">
                {{ t('banned.permanentTag') }}
              </el-tag>
              <el-tag v-if="b.note" size="small" type="warning" effect="plain">
                {{ b.note }}
              </el-tag>
            </div>
            <div class="ban-meta">
              <template v-if="b.permanent">
                <span>{{ t('banned.neverExpire') }}</span>
              </template>
              <template v-else>
                <span>{{ t('banned.remaining', { mins: b.remaining_minutes }) }}</span>
                <span class="sep">·</span>
                <span>{{ t('banned.until') }} {{ fmtTs(b.banned_until) }}</span>
              </template>
            </div>
          </div>
          <div class="ban-acts">
            <el-dropdown trigger="click" :disabled="b.permanent" @command="(k: string) => extend(b.ip, k)">
              <el-button size="small" :disabled="b.permanent">
                <Icon name="plus" :size="13" /><span>{{ t('banned.extend') }}</span>
              </el-button>
              <template #dropdown>
                <el-dropdown-menu>
                  <el-dropdown-item v-for="o in DURATIONS" :key="o.k" :command="o.k">
                    +{{ t(`banned.dur.${o.k}`) }}
                  </el-dropdown-item>
                  <el-dropdown-item command="forever" divided>
                    {{ t('banned.toPermanent') }}
                  </el-dropdown-item>
                </el-dropdown-menu>
              </template>
            </el-dropdown>
            <el-button size="small" @click="unban(b.ip)">
              <Icon name="check" :size="13" /><span>{{ t('banned.unban') }}</span>
            </el-button>
          </div>
        </div>
      </div>
      <el-empty v-else :description="t('banned.empty')" :image-size="72" />
    </div>

    <!-- ── 封禁历史 ─────────────────────────────────────────── -->
    <div class="card">
      <div class="card-h">
        <Icon name="log" :size="15" />
        <b>{{ t('banned.historyTitle') }}</b>
        <span class="sub">{{ t('banned.historySub') }}</span>
        <div class="pager">
          <el-select v-model="hisLimit" size="small" class="w-his" @change="loadHistory">
            <el-option :value="20" label="20" />
            <el-option :value="50" label="50" />
            <el-option :value="100" label="100" />
          </el-select>
          <el-button size="small" :loading="hisLoading" @click="loadHistory">
            <Icon name="refresh" :size="13" /><span>{{ t('common.refresh') }}</span>
          </el-button>
          <el-button size="small" type="danger" plain :disabled="!history.length" @click="clearHistory">
            <Icon name="trash" :size="13" /><span>{{ t('banned.hisClearAll') }}</span>
          </el-button>
        </div>
      </div>

      <el-table v-if="history.length" :data="history" size="small" class="his-table">
        <el-table-column :label="t('banned.hisTime')" width="150">
          <template #default="{ row }">{{ fmtTs(row.ts) }}</template>
        </el-table-column>
        <el-table-column :label="t('banned.hisAction')" width="110">
          <template #default="{ row }">
            <el-tag :type="ACTION_TAG[row.action] || 'info'" size="small" effect="plain">
              {{ t(`banned.act.${row.action}`) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column :label="t('banned.hisIp')" min-width="140">
          <template #default="{ row }"><span class="code">{{ row.ip }}</span></template>
        </el-table-column>
        <el-table-column :label="t('banned.hisDuration')" width="110">
          <template #default="{ row }">
            {{ row.permanent ? t('banned.permanentTag') : (row.seconds ? fmtDur(row.seconds) : '—') }}
          </template>
        </el-table-column>
        <el-table-column :label="t('banned.hisActor')" width="110">
          <template #default="{ row }">{{ row.actor || '—' }}</template>
        </el-table-column>
        <el-table-column :label="t('banned.hisNote')" min-width="140">
          <template #default="{ row }"><span class="muted-2">{{ row.note || '—' }}</span></template>
        </el-table-column>
        <el-table-column :label="t('banned.hisOps')" width="76" align="center">
          <template #default="{ row }">
            <el-button size="small" type="danger" text :title="t('common.delete')" @click="delHistory(row)">
              <Icon name="trash" :size="13" />
            </el-button>
          </template>
        </el-table-column>
      </el-table>
      <el-empty v-else :description="t('banned.historyEmpty')" :image-size="60" />
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { ElMessage, ElMessageBox } from 'element-plus'
import { api, errText } from '../api'
import Icon from '../components/Icon.vue'

const { t } = useI18n()
const items = ref<any[]>([])
const history = ref<any[]>([])
const loading = ref(false)
const banning = ref(false)
const hisLoading = ref(false)
const hisLimit = ref(50)
const limit = ref(60)
const banSeconds = ref(3600)
let timer: any = null

const newIp = ref('')
const newDur = ref('h1')
const newNote = ref('')

const banMinutes = computed(() => Math.max(1, Math.round(banSeconds.value / 60)))

/** 时长预设。forever 走 permanent 字段，其余按秒传。 */
const DURATIONS = [
  { k: 'm10', v: 600 },
  { k: 'm30', v: 1800 },
  { k: 'h1', v: 3600 },
  { k: 'h6', v: 21600 },
  { k: 'd1', v: 86400 },
  { k: 'd30', v: 2592000 },
  { k: 'forever', v: 0 },
] as { k: string; v: number }[]

const ACTION_TAG: Record<string, string> = {
  manual_ban: 'warning',
  auto_ban: 'info',
  extend: 'primary',
  unban: 'success',
  unban_all: 'danger',
}

function fmtTs(ts: number): string {
  if (!ts) return '—'
  const d = new Date(ts * 1000)
  const p = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`
}

function fmtDur(sec: number): string {
  if (sec >= 86400 && sec % 86400 === 0) return t('banned.unitDay', { n: sec / 86400 })
  if (sec >= 3600) return t('banned.unitHour', { n: Math.round(sec / 3600) })
  return t('banned.unitMin', { n: Math.round(sec / 60) })
}

function durPayload(k: string): any {
  if (k === 'forever') return { permanent: true }
  const d = DURATIONS.find((x) => x.k === k)
  return { seconds: d ? d.v : 3600 }
}

async function reload() {
  loading.value = true
  try {
    const j = await api('/admin/banned')
    items.value = j.items || []
    if (typeof j.auth_fail_limit_per_min === 'number') limit.value = j.auth_fail_limit_per_min
    if (typeof j.ban_seconds === 'number' && j.ban_seconds > 0) banSeconds.value = j.ban_seconds
  } catch (e: any) {
    ElMessage.error(errText(e))
  } finally {
    loading.value = false
  }
}

async function loadHistory() {
  hisLoading.value = true
  try {
    const j = await api(`/admin/banned/history?limit=${hisLimit.value}`)
    history.value = j.items || []
  } catch (e: any) {
    ElMessage.error(errText(e))
  } finally {
    hisLoading.value = false
  }
}

async function doBan() {
  const ip = newIp.value.trim()
  if (!ip) { ElMessage.warning(t('banned.ipRequired')); return }
  banning.value = true
  try {
    const j = await api('/admin/banned', {
      method: 'POST',
      body: JSON.stringify({ ip, note: newNote.value.trim(), ...durPayload(newDur.value) }),
    })
    ElMessage.success(
      j.permanent
        ? t('banned.bannedForever', { ip: j.ip })
        : t('banned.banned', { ip: j.ip, mins: Math.round(j.banned_seconds / 60) }),
    )
    newIp.value = ''
    newNote.value = ''
    await Promise.all([reload(), loadHistory()])
  } catch (e: any) {
    ElMessage.error(errText(e))
  } finally {
    banning.value = false
  }
}

async function extend(ip: string, k: string) {
  try {
    const j = await api(`/admin/banned/${encodeURIComponent(ip)}`, {
      method: 'PUT',
      body: JSON.stringify(durPayload(k)),
    })
    ElMessage.success(
      j.permanent ? t('banned.extendedForever', { ip }) : t('banned.extended', { ip, mins: Math.round(j.extended_seconds / 60) }),
    )
    await Promise.all([reload(), loadHistory()])
  } catch (e: any) {
    ElMessage.error(errText(e))
  }
}

async function unban(ip: string) {
  try {
    await api(`/admin/banned/${encodeURIComponent(ip)}`, { method: 'DELETE' })
    ElMessage.success(t('banned.unbanned', { ip }))
    await Promise.all([reload(), loadHistory()])
  } catch (e: any) {
    ElMessage.error(errText(e))
  }
}

async function delHistory(row: any) {
  try {
    await api(`/admin/banned/history/${encodeURIComponent(row.id)}`, { method: 'DELETE' })
    ElMessage.success(t('banned.hisDeleted'))
    await loadHistory()
  } catch (e: any) {
    ElMessage.error(errText(e))
  }
}

async function clearHistory() {
  try {
    await ElMessageBox.confirm(t('banned.hisClearConfirm'), t('banned.hisClearAll'), { type: 'warning' })
  } catch { return }
  try {
    const j = await api('/admin/banned/history', { method: 'DELETE' })
    ElMessage.success(t('banned.hisCleared', { n: j.cleared ?? 0 }))
    await loadHistory()
  } catch (e: any) {
    ElMessage.error(errText(e))
  }
}

async function clearAll() {
  try {
    await ElMessageBox.confirm(t('banned.clearConfirm'), t('banned.clearTitle'), { type: 'warning' })
  } catch { return }
  try {
    const j = await api('/admin/banned', { method: 'DELETE' })
    ElMessage.success(t('banned.cleared', { n: j.cleared ?? 0 }))
    await Promise.all([reload(), loadHistory()])
  } catch (e: any) {
    ElMessage.error(errText(e))
  }
}

onMounted(() => {
  reload()
  loadHistory()
  timer = setInterval(reload, 10000)
})
onUnmounted(() => { if (timer) clearInterval(timer) })
</script>

<style scoped>
/* 手动封禁表单：一行放下，窄屏自动换行 */
.ban-form { display: flex; align-items: center; gap: var(--gap-sm); flex-wrap: wrap; }
.w-ip { width: 220px; }
.w-dur { width: 130px; }
.w-note { width: 200px; }
.w-his { width: 84px; }
.form-hint {
  display: flex; align-items: center; gap: 6px;
  margin-top: var(--gap-sm); font-size: 11.5px; line-height: 1.6; color: var(--muted-2);
}
.form-hint .gw-icon { flex: none; }

/* 规则提示条 —— 与 ApiKeys 的 warn-bar 同一套观感（那边是 scoped，这里要自带） */
.warn-bar {
  display: flex; align-items: center; gap: 8px;
  background: var(--warn-soft); color: var(--warn);
  border-radius: var(--radius-s); padding: 9px 12px;
  font-size: 12px; line-height: 1.6; margin-bottom: var(--gap-sm);
}
.warn-bar .gw-icon { flex: none; }

.ban-list { display: flex; flex-direction: column; }
.ban-row {
  display: flex; align-items: center; gap: var(--gap-sm);
  padding: 11px 2px; border-bottom: 1px solid var(--line);
}
.ban-row:last-child { border-bottom: none; }
.ban-row .dot {
  flex: none; width: 7px; height: 7px; border-radius: 50%;
  background: var(--warn);
}
.ban-row .dot.perm { background: var(--err, #e5484d); }
.ban-main { flex: 1; min-width: 0; }
.ban-top { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.ban-ip { font-size: 13px; font-weight: 600; }
.ban-meta {
  margin-top: 3px; font-size: 11.5px; color: var(--muted-2);
  display: flex; align-items: center; gap: 6px; flex-wrap: wrap;
}
.ban-meta .sep { color: var(--line); }
.ban-acts { display: flex; align-items: center; gap: 6px; flex: none; }
.his-table { width: 100%; }

@media (max-width: 640px) {
  .w-ip, .w-note, .w-dur { width: 100%; }
  .ban-form :deep(.el-button) { width: 100%; }
  .ban-row { flex-wrap: wrap; }
  .ban-acts { width: 100%; justify-content: flex-end; }
}
</style>
