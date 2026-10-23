<template>
  <div class="calllogs">
    <!-- 筛选行 -->
    <div class="filters">
      <el-date-picker
        v-model="range" type="daterange" size="small" class="w-range"
        value-format="YYYY-MM-DD" :start-placeholder="t('calllogs.startDate')"
        :end-placeholder="t('calllogs.endDate')" :clearable="true"
      />
      <el-input v-model="account" size="small" class="w140" clearable
        :placeholder="t('calllogs.account')" @keyup.enter="reload" />
      <el-input v-model="model" size="small" class="w170" clearable
        :placeholder="t('calllogs.model')" @keyup.enter="reload" />
      <el-select v-model="okSel" size="small" class="w120" clearable :placeholder="t('calllogs.result')">
        <el-option value="1" :label="t('calllogs.onlyOk')" />
        <el-option value="0" :label="t('calllogs.onlyFail')" />
      </el-select>
      <el-input v-model="kw" size="small" class="w200" clearable
        :placeholder="t('calllogs.keyword')" @keyup.enter="reload" />
      <el-date-picker v-model="month" type="month" size="small" class="w140"
        value-format="YYYY-MM" :placeholder="t('calllogs.usageMonth')" :clearable="false" />
      <el-button size="small" @click="openUsage">
        <Icon name="dash" :size="13" /><span>{{ t('calllogs.usageTitle') }}</span>
      </el-button>
      <span class="spacer" />
      <el-button size="small" :loading="loading" @click="reload">
        <Icon name="refresh" :size="13" /><span>{{ t('common.refresh') }}</span>
      </el-button>
      <el-button size="small" :disabled="!total" @click="exportCsv">
        <Icon name="dl" :size="13" /><span>{{ t('common.export') }}</span>
      </el-button>
    </div>

    <div class="card">
      <div class="card-h">
        <b>{{ t('calllogs.title') }}</b>
        <span class="sub">{{ t('calllogs.count', { n: total }) }}</span>
        <div class="pager">
          <span class="pill" :class="failCount ? 'warn' : 'ok'">
            {{ t('calllogs.failN', { n: failCount }) }}
          </span>
          <span class="pill">{{ t('calllogs.avgMs', { n: avgMs }) }}</span>
        </div>
      </div>

      <el-table :data="rows" size="small" v-loading="loading" max-height="580"
        class="tbl" @row-click="openDetail" :row-class-name="rowCls">
        <el-table-column prop="ts_iso" :label="t('calllogs.colTime')" width="152" />
        <el-table-column prop="account" :label="t('calllogs.colAccount')" width="112" show-overflow-tooltip />
        <el-table-column prop="model" :label="t('calllogs.colModel')" min-width="150" show-overflow-tooltip>
          <template #default="{ row }">
            <span>{{ row.model || '—' }}</span>
            <span v-if="row.served && row.served !== row.model" class="sub"> → {{ row.served }}</span>
          </template>
        </el-table-column>
        <!-- 2026-10-23 老板要求：模型后面加「内容」——显示请求体里 messages 的 content（单行预览） -->
        <el-table-column :label="t('calllogs.colContent')" min-width="240" show-overflow-tooltip>
          <template #default="{ row }">
            <span :class="{ 'muted-t': !row.prompt_text }">{{ row.prompt_text || '—' }}</span>
          </template>
        </el-table-column>
        <el-table-column :label="t('calllogs.colLatency')" width="92">
          <template #default="{ row }">{{ row.latency_ms != null ? row.latency_ms + 'ms' : '—' }}</template>
        </el-table-column>
        <!-- 2026-10-23：缓存命中量与命中率（cached ÷ prompt） -->
        <el-table-column :label="t('calllogs.colCache')" width="118">
          <template #default="{ row }">
            <span v-if="row.tok_prompt" :class="hitCls(row)" :title="t('calllogs.cacheHint')">
              {{ fmtTok(row.tok_cached) }}
              <i class="hit-pct">{{ hitRate(row) }}%</i>
            </span>
            <span v-else class="muted-t">—</span>
          </template>
        </el-table-column>
        <el-table-column :label="t('calllogs.colStatus')" width="84">
          <template #default="{ row }">
            <span :class="row.ok ? 'ok-t' : 'err-t'">{{ row.status ?? '—' }}</span>
          </template>
        </el-table-column>
        <el-table-column :label="t('calllogs.colStream')" width="66">
          <template #default="{ row }">{{ row.stream ? t('calllogs.yes') : '—' }}</template>
        </el-table-column>
        <el-table-column prop="ua" :label="t('calllogs.colUa')" min-width="130" show-overflow-tooltip />
      </el-table>

      <div class="pager-bar">
        <el-pagination
          v-model:current-page="page" :page-size="pageSize" :total="total"
          layout="prev, pager, next, total" small background @current-change="loadPage"
        />
      </div>
    </div>

    <!-- 月度用量弹窗：按账号聚合 -->
    <el-dialog v-model="usageDlg" :title="t('calllogs.usageTitle')" width="760px" top="8vh">
      <div class="card-h" style="margin-bottom: 8px">
        <b>{{ usage.month || month }}</b>
        <span class="sub">{{ t('calllogs.usageTotal', { n: usage.total_calls || 0 }) }}</span>
        <span class="spacer" />
        <el-button size="small" @click="exportUsage">
          <Icon name="dl" :size="13" /><span>{{ t('common.export') }}</span>
        </el-button>
      </div>
      <el-table :data="usage.items || []" size="small" max-height="420">
        <el-table-column prop="account" :label="t('calllogs.colAccount')" min-width="120" />
        <el-table-column prop="calls" :label="t('calllogs.colCalls')" width="90" />
        <el-table-column prop="ok" :label="t('calllogs.colOk')" width="80" />
        <el-table-column prop="fail" :label="t('calllogs.colFail')" width="80" />
        <el-table-column :label="t('calllogs.colFailRate')" width="100">
          <template #default="{ row }">{{ row.calls ? (row.fail / row.calls * 100).toFixed(1) + '%' : '—' }}</template>
        </el-table-column>
        <el-table-column :label="t('calllogs.colLatency')" width="100">
          <template #default="{ row }">{{ row.avg_ms }}ms</template>
        </el-table-column>
        <el-table-column prop="models" :label="t('calllogs.colModels')" width="90" />
      </el-table>
    </el-dialog>

    <!-- 详情弹窗：完整提示词 + 回复 -->
    <el-dialog v-model="dlg" :title="t('calllogs.detailTitle')" width="880px" top="5vh"
      class="calllog-dlg" :close-on-click-modal="true">
      <div v-if="detail" class="det">
        <div class="kv">
          <span><i>{{ t('calllogs.colTime') }}</i>{{ detail.ts_iso }}</span>
          <span><i>rid</i><code>{{ detail.rid || '—' }}</code></span>
          <span><i>{{ t('calllogs.colAccount') }}</i>{{ detail.account || '—' }}</span>
          <span><i>Key</i>{{ detail.key_id ? detail.key_id + '…' : '—' }}</span>
          <span><i>{{ t('calllogs.colModel') }}</i>{{ detail.model || '—' }}</span>
          <span><i>{{ t('calllogs.colStatus') }}</i>{{ detail.status ?? '—' }} · {{ detail.ok ? 'OK' : 'FAIL' }}</span>
          <span><i>{{ t('calllogs.colLatency') }}</i>{{ detail.latency_ms != null ? detail.latency_ms + 'ms' : '—' }}</span>
          <span><i>{{ t('calllogs.colStream') }}</i>{{ detail.stream ? t('calllogs.yes') : t('calllogs.no') }}</span>
          <span><i>IP</i>{{ detail.ip || '—' }}</span>
          <span><i>UA</i>{{ detail.ua || '—' }}</span>
          <span><i>path</i>{{ detail.path || '—' }}</span>
          <span><i>ver</i>{{ detail.ver || '—' }}</span>
        </div>
        <div class="kv" v-if="detail.tok_prompt || detail.tok_completion || detail.tok_cached || detail.tok_reasoning">
          <span><i>{{ t('logs.tokPrompt') }}</i>{{ detail.tok_prompt || 0 }}</span>
          <span><i>{{ t('logs.tokCompletion') }}</i>{{ detail.tok_completion || 0 }}</span>
          <span><i>{{ t('logs.tokCached') }}</i>{{ detail.tok_cached || 0 }}</span>
          <span><i>{{ t('logs.tokReasoning') }}</i>{{ detail.tok_reasoning || 0 }}</span>
          <span><i>{{ t('logs.cacheHit') }}</i>{{ detail.tok_prompt ? (Math.round((detail.tok_cached || 0) / detail.tok_prompt * 1000) / 10) : 0 }}%</span>
        </div>
        <div class="sec">
          <label>{{ t('calllogs.colContent') }}（完整，保留换行）</label>
          <pre>{{ detail.prompt_full || detail.prompt_text || '—' }}</pre>
        </div>
        <div class="sec">
          <label>{{ t('calllogs.prompt') }}（原始请求体 JSON）</label>
          <pre>{{ detail.prompt || '—' }}</pre>
        </div>
        <div class="sec">
          <label>{{ t('calllogs.completion') }}</label>
          <pre>{{ detail.completion || '—' }}</pre>
        </div>
      </div>
      <div v-else class="sub" style="padding: 20px 0">{{ t('calllogs.loading') }}</div>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { api, getToken } from '../api'
import Icon from '../components/Icon.vue'
import { filenameFromHeader } from '../lib/download'

const { t } = useI18n()

const rows = ref<any[]>([])
const total = ref(0)
const loading = ref(false)
const page = ref(1)
const pageSize = 50

const range = ref<[string, string] | null>(null)
const account = ref('')
const model = ref('')
const okSel = ref('')
const kw = ref('')

const dlg = ref(false)
const detail = ref<any>(null)

// 月度用量（按账号聚合）
const month = ref(new Date().toISOString().slice(0, 7))
const usageDlg = ref(false)
const usage = ref<any>({})

async function openUsage() {
  usageDlg.value = true
  try {
    usage.value = await api(`/logs/usage/monthly?month=${month.value}`)
  } catch {
    usage.value = { items: [] }
  }
}

async function exportUsage() {
  const resp = await fetch(`/logs/usage/monthly/export?month=${month.value}`, {
    headers: { Authorization: `Bearer ${getToken()}` },
  })
  if (!resp.ok) return
  const blob = await resp.blob()
  const href = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = href
  a.download = `usage-${month.value}.csv`
  a.style.display = 'none'
  document.body.appendChild(a)
  a.click()
  a.remove()
  setTimeout(() => URL.revokeObjectURL(href), 10_000)
}

const failCount = computed(() => rows.value.filter((r) => !r.ok).length)
const avgMs = computed(() => {
  const v = rows.value.map((r) => Number(r.latency_ms)).filter((n) => Number.isFinite(n) && n > 0)
  if (!v.length) return 0
  return Math.round(v.reduce((a, b) => a + b, 0) / v.length)
})

function qs(extra: Record<string, string> = {}): string {
  const p = new URLSearchParams()
  if (range.value && range.value[0]) p.set('start', `${range.value[0]} 00:00`)
  if (range.value && range.value[1]) p.set('end', `${range.value[1]} 23:59`)
  if (account.value.trim()) p.set('account', account.value.trim())
  if (model.value.trim()) p.set('model', model.value.trim())
  if (okSel.value !== '') p.set('ok', okSel.value)
  if (kw.value.trim()) p.set('q', kw.value.trim())
  Object.entries(extra).forEach(([k, v]) => p.set(k, v))
  return p.toString()
}

async function loadPage() {
  loading.value = true
  try {
    const data = await api(`/logs/calls?${qs({ limit: String(pageSize), offset: String((page.value - 1) * pageSize) })}`)
    rows.value = data.items || []
    total.value = data.total || 0
  } catch (e: any) {
    rows.value = []
    total.value = 0
  } finally {
    loading.value = false
  }
}

function reload() {
  page.value = 1
  loadPage()
}

async function openDetail(row: any) {
  detail.value = null
  dlg.value = true
  try {
    detail.value = await api(`/logs/calls/${row.id}`)
  } catch {
    detail.value = row
  }
}

async function exportCsv() {
  const q = qs()
  const resp = await fetch(`/logs/calls/export?${q}`, {
    headers: { Authorization: `Bearer ${getToken()}` },
  })
  if (!resp.ok) return
  const blob = await resp.blob()
  const name = filenameFromHeader(resp.headers.get('content-disposition') || '') ||
    `calllog-${new Date().toISOString().slice(0, 19).replace(/[:T]/g, '')}.csv`
  const href = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = href
  a.download = name
  a.style.display = 'none'
  document.body.appendChild(a)
  a.click()
  a.remove()
  setTimeout(() => URL.revokeObjectURL(href), 10_000)
}

/** 缓存命中量：≥1000 用 k 缩写，便于表格窄列显示。 */
function fmtTok(n: any): string {
  const v = Number(n) || 0
  if (v >= 1_000_000) return (v / 1_000_000).toFixed(1) + 'M'
  if (v >= 1000) return (v / 1000).toFixed(1) + 'k'
  return String(v)
}
/** 命中率 = tok_cached ÷ tok_prompt（0 保护）。 */
function hitRate(row: any): number {
  const p = Number(row.tok_prompt) || 0
  const c = Number(row.tok_cached) || 0
  return p > 0 ? Math.round((c / p) * 1000) / 10 : 0
}
function hitCls(row: any): string {
  const r = hitRate(row)
  return r >= 50 ? 'hit-good' : r > 0 ? 'hit-mid' : 'hit-none'
}

function rowCls({ row }: { row: any }) {
  return row.ok ? '' : 'row-fail'
}

onMounted(loadPage)
</script>

<style scoped>
.calllogs { display: flex; flex-direction: column; gap: 12px; }
.filters { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.w-range { width: 250px; }
.w140 { width: 140px; }
.w170 { width: 170px; }
.w120 { width: 120px; }
.w200 { width: 200px; }
.spacer { flex: 1; }
.card { background: var(--surface); border: 1px solid var(--line); border-radius: 12px; padding: 12px 14px; }
.card-h { display: flex; align-items: center; gap: 10px; margin-bottom: 10px; }
.card-h b { font-size: 13.5px; }
.pager { display: flex; gap: 6px; margin-left: auto; }
.pill { font-size: 11.5px; padding: 2px 8px; border-radius: 999px; background: var(--chip); color: var(--muted-2); }
.pill.ok { color: var(--ok); }
.pill.warn { color: var(--err); }
.tbl :deep(.row-fail) { background: color-mix(in srgb, var(--err) 6%, transparent); }
.ok-t { color: var(--ok); font-variant-numeric: tabular-nums; }
.err-t { color: var(--err); font-weight: 600; font-variant-numeric: tabular-nums; }
.pager-bar { display: flex; justify-content: flex-end; padding-top: 10px; }
.sub { font-size: 11.5px; color: var(--muted-2); }
.muted-t { color: var(--muted-2); }
.hit-pct { font-style: normal; opacity: .75; font-size: 11px; margin-left: 3px; }
.hit-good { color: var(--ok); font-variant-numeric: tabular-nums; }
.hit-mid { color: #a97c00; font-variant-numeric: tabular-nums; }
.hit-none { color: var(--muted-2); font-variant-numeric: tabular-nums; }
.kv { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 6px 14px; font-size: 12.5px; }
.kv span { display: flex; gap: 6px; align-items: baseline; overflow: hidden; }
.kv i { font-style: normal; color: var(--muted-2); min-width: 52px; }
.kv code { font-size: 11.5px; }
.sec { margin-top: 12px; }
.sec label { font-size: 12px; color: var(--muted-2); }
.sec pre {
  margin: 4px 0 0; padding: 10px 12px; max-height: 460px; overflow: auto;
  background: var(--surface-2, #f7f8fa); border: 1px solid var(--line); border-radius: 8px;
  font-size: 12px; line-height: 1.5; white-space: pre-wrap; word-break: break-word;
}
@media (max-width: 768px) {
  .kv { grid-template-columns: 1fr; }
  .w-range, .w140, .w170, .w120, .w200 { width: 100%; }
}
</style>

<!-- 2026-10-23：详情弹窗「整体固定高度 + 内容区各自内部滚动」。
     必须用**非 scoped** 样式：el-dialog 会 teleport 到 body，scoped 选择器命中不了。 -->
<style>
.calllog-dlg {
  height: min(78vh, 860px);
  display: flex;
  flex-direction: column;
  margin-bottom: 0;
}
.calllog-dlg .el-dialog__header { flex: 0 0 auto; }
.calllog-dlg .el-dialog__body {
  flex: 1 1 auto;
  min-height: 0;            /* 关键：允许子项收缩，否则 flex 子项撑破容器 */
  overflow: hidden;         /* 弹窗自身不出滚动条 */
  display: flex;
  flex-direction: column;
  padding-top: 8px;
}
.calllog-dlg .det {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0;
}
.calllog-dlg .det .kv { flex: 0 0 auto; }
.calllog-dlg .det .sec {
  flex: 1 1 0;
  min-height: 0;
  display: flex;
  flex-direction: column;
  margin-top: 10px;
}
.calllog-dlg .det .sec label { flex: 0 0 auto; }
.calllog-dlg .det .sec pre {
  flex: 1 1 auto;
  min-height: 90px;
  max-height: none;         /* 覆盖 scoped 里的 460px，交给 flex 分配 */
  overflow: auto;           /* 只有内容区自己有滚动条 */
  margin: 4px 0 0;
}
@media (max-width: 768px) {
  .calllog-dlg { height: 86vh; }
}
</style>
