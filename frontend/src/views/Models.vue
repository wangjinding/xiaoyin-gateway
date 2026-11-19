<template>
  <div class="page">
    <el-alert v-if="err" :title="err" type="error" show-icon :closable="false" class="mb" />

    <div class="kpis">
      <div v-for="c in cards" :key="c.k" class="kpi">
        <div class="k">{{ c.k }}</div>
        <div class="v">{{ c.v }}</div>
        <div class="f"><span class="muted-2">{{ c.note }}</span></div>
      </div>
    </div>

    <div class="grid2">

      <!-- 供应商：状态取 /health 的熔断器，Key 是否配置取同一份数据 -->
      <div class="card">
        <div class="card-h">
          <b>{{ t('models.providerCard') }}</b>
          <span class="sub">{{ t('models.providerCount2', { n: providerRows.length }) }}</span>
        </div>
        <div v-for="p in providerRows" :key="p.name" class="prov">
          <div class="prov-top">
            <b>{{ p.name }}</b>
            <span class="pill" :class="p.cls">{{ p.text }}</span>
          </div>
          <div class="prov-meta">
            <span class="muted-2">{{ p.models }} {{ t('models.model') }}</span>
            <span class="pill" :class="p.keySet ? 'ok' : 'err'">
              {{ p.keySet ? t('models.keyOk') : t('models.keyMissing') }}
            </span>
          </div>
        </div>
        <div v-if="!providerRows.length" class="hint">{{ t('common.empty') }}</div>
      </div>

    <!-- 供应商用量详情：OpenCode Go 套餐的三个窗口（rolling / weekly / monthly）。
         数据来自网关 /providers/opencode/usage（上游 /zen/go/v1/usage，网关侧缓存 8 秒），
         前端每 10 秒拉一次；**剩余时间**由 resetsAt 在本地倒计时，每秒刷新一次。 -->
        <div class="card">
        <div class="card-h">
          <b>{{ t('models.usageCard') }}</b>
          <span class="sub">{{ ocUsageErr || t('models.usageAuto') }}</span>
        </div>
        <div class="usage-prov">
          <div class="prov-top">
            <b>OpenCode Go</b>
            <span class="pill" :class="ocUsage ? 'ok' : 'mute'">
              {{ ocUsage ? t('models.usageLive') : t('models.usageNone') }}
            </span>
          </div>
          <template v-if="ocUsage">
            <div v-for="w in usageWindows" :key="w.key" class="usage-row">
              <span class="usage-l">{{ t(w.label) }}</span>
              <div class="usage-bar"><i :class="w.cls" :style="{ width: w.width }"></i></div>
              <span class="usage-p" :class="w.cls">{{ w.pct }}%</span>
              <span class="usage-reset">{{ t('models.usageResetIn', { t: w.resetText }) }}</span>
            </div>
            <!-- 订阅续期：官方控制台顶部那句「Renews in 17d 17h」。
                 上游 /usage 只有 rolling/weekly/monthly 三个窗口，没有单独的续期字段；
                 实测 monthly.resetsAt 与官方控制台的续期时间完全一致（2026-10-30 核对），
                 所以直接用月度重置时间当续期日。 -->
            <div class="usage-renew">
              <span class="usage-l">{{ t('models.usageRenew') }}</span>
              <span style="flex:1"></span>
              <span class="usage-renew-t">{{ renewText }}</span>
            </div>
          </template>
          <div v-else class="muted-2 usage-empty">{{ t('models.usageNone') }}</div>
        </div>
      </div>
    </div>

    <div class="card" style="margin-top: var(--gap)">
      <div class="card-h">
        <b>{{ t('models.modelListTitle') }}</b>
        <span class="sub">{{ t('models.capability') }}</span>
        <div class="pager">
          <span class="pill mute">{{ t('models.textModelCount', { n: textModelRows.length }) }}</span>
        </div>
      </div>
      <div class="lat-toolbar">
        <span class="muted-2">{{ t('models.speedtestHint', { n: SPEEDTEST_MAX_CONCURRENCY }) }}</span>
        <span style="flex:1"></span>
        <el-button size="small" :loading="latTesting" :disabled="latRunningCount > 0" @click="runSpeedtest()">
          {{ latTesting ? t('models.testingShort') : t('models.speedtest') }}
        </el-button>
      </div>
      <el-table :data="modelRows" size="small" v-loading="loading">
        <el-table-column :label="t('models.id')" min-width="215">
          <template #default="{ row }">
            <span class="code">{{ row.id }}</span>
            <!-- 2026-09-21（老板要求）：免费标志直接跟在模型名后面
                 2026-09-24：区分「免费」与「限时免费」 -->
            <span v-if="row.free" class="pill free name-free" :title="freeHint(row)">{{ freeText(row) }}</span>
          </template>
        </el-table-column>
        <el-table-column :label="t('models.type')" width="90">
          <template #default="{ row }"><span class="pill" :class="typeCls(row.type)">{{ t(typeKey(row.type)) }}</span></template>
        </el-table-column>
        <el-table-column :label="t('models.provider')" min-width="140">
          <template #default="{ row }">{{ row.provider_name || '—' }}</template>
        </el-table-column>
        <!-- 第二十七轮追加：支持的格式（三条协议线）——
             后端 /v1/models 里每个文本模型带 protocols 数组（chat/completions、messages、
             responses 的一个子集）。这里只做展示，但它有实际约束力：用不在列表里的格式
             调网关，会在入口被 400 挡下（网关不做跨格式转换，见 /v1/messages 的 400 文案）。
             图像/视频模型走专用端点，不涉及三条协议线，统一显示「不适用」。
             width 取 300：实测三颗标签（chat/completions=120px + messages=67px + responses=74px
             + 间距）并排一行需 ~273px，留足余量让多线模型那行也单行，不挤到换行。 -->
        <el-table-column width="300">
          <template #header>
            <el-tooltip :content="t('models.protocolHint')" placement="top">
              <span class="proto-th">{{ t('models.protocols') }}</span>
            </el-tooltip>
          </template>
          <template #default="{ row }">
            <span v-if="protocolsOf(row).length" class="proto-cell">
              <span v-for="p in protocolsOf(row)" :key="p" class="pill proto" :title="protoTitle(p)">{{ p }}</span>
            </span>
            <el-tooltip v-else :content="t('models.protocolNaHint')" placement="top">
              <span class="muted-2">{{ t('models.protocolNa') }}</span>
            </el-tooltip>
          </template>
        </el-table-column>
        <el-table-column :label="t('models.capability')" width="170">
          <template #default="{ row }">
            <span v-if="row.vision" class="pill ok cap">
              <Icon name="eye" :size="12" />{{ t('models.visionTag') }}
            </span>
            <!-- 2026-09-21（老板要求）：免费标志已挪到「模型」列、紧跟模型名后面，这里不再重复 -->
            <span v-if="paramKeys(row).length" class="pill warn cap" :title="paramNote(row)">
              <Icon name="lock" :size="12" />{{ t('models.paramTag') }}
            </span>
            <span v-if="!row.vision && !paramKeys(row).length" class="muted-2">—</span>
          </template>
        </el-table-column>
        <!-- 2026-11-19（老板要求）：OpenCode Go 的套餐额度与训练策略。
             额度 = 「只用这一个模型时，该套餐每月能覆盖多少用量」（官方 go.monthly_usage，美元）；
             训练 = 官方 go.training（false = 不拿你的请求训练）。
             只有 OpenCode Go 的模型带这个字段，其余供应商显示「—」。 -->
        <el-table-column width="150">
          <template #header>
            <el-tooltip :content="t('models.goQuotaHint')" placement="top">
              <span class="proto-th">{{ t('models.goQuota') }}</span>
            </el-tooltip>
          </template>
          <template #default="{ row }">
            <template v-if="row.goMeta">
              <span class="pill go-quota cap" :title="goQuotaHint(row)">{{ goQuotaText(row) }}</span>
              <span class="pill cap" :class="goTrains(row) ? 'err' : 'ok'" :title="t('models.goTrainingHint')">
                {{ goTrains(row) ? t('models.goTrainingYes') : t('models.goTrainingNo') }}
              </span>
            </template>
            <span v-else class="muted-2">—</span>
          </template>
        </el-table-column>
        <el-table-column :label="t('models.keySet')" width="90">
          <template #default="{ row }">
            <span class="pill" :class="row.key_set ? 'ok' : 'err'">
              {{ row.key_set ? t('common.yes') : t('common.no') }}
            </span>
          </template>
        </el-table-column>
        <!-- 延迟列：只有文本模型能测速（图像/视频走专用端点，不参与延迟探测）。
             2026-10-30（老板）：延迟与单测按钮从独立的「全部文本模型」卡并入这张表。 -->
        <el-table-column :label="t('models.latency')" width="150">
          <template #default="{ row }">
            <template v-if="row.type === 'text'">
              <span class="pill st-lat" :class="latCls(row.id)" :title="latErr(row.id) || ''">
                <span v-if="row.id === latCurrentId || latRunning[row.id]" class="st-spin" aria-hidden="true"></span>
                <span v-else>{{ latText(row.id) }}</span>
              </span>
              <button class="st-one"
                      :disabled="latTesting || !!latRunning[row.id] || latRunningCount >= SPEEDTEST_MAX_CONCURRENCY"
                      :title="testOneHint(row)" :aria-label="testOneHint(row)" @click="retestOne(row.id)">
                <Icon name="bolt" :size="13" />
              </button>
            </template>
            <el-tooltip v-else :content="t('models.latencyNaHint')" placement="top">
              <span class="muted-2">—</span>
            </el-tooltip>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <!-- 第三十一轮：虚拟模型 id（别名）。客户端固定写 model: wjd，实际转发到哪个真实模型
         由管理员在这里选；member 没有编辑行，只看到「wjd → 目标」这一行数据（数据来自
         /v1/models 的 alias_of —— 普通账号读不到 /config，也不需要读到）。
         保存走 PUT /config（管理员 + 网页会话），**保存即生效**：不需要重启网关。 -->
    <div v-if="aliasRows.length" class="card" style="margin-top: var(--gap)">
      <div class="card-h">
        <b>{{ t('models.aliasCard') }}</b>
      </div>

      <div v-for="a in aliasRows" :key="a.name" class="alias">
        <div class="alias-top">
          <Icon name="link" :size="14" class="alias-ico" />
          <span class="pill alias-id">{{ a.name }}</span>
          <span class="alias-arrow">→</span>
          <span v-if="a.target" class="code">{{ a.target }}</span>
          <span v-else class="muted-2">—</span>
          <span class="pill" :class="a.enabled ? 'ok' : 'mute'">
            {{ a.enabled ? t('models.aliasEnabled') : t('models.aliasDisabled') }}
          </span>
        </div>

        <!-- 管理员：选目标（只有支持 chat/completions 的文本模型可选，其余置灰） -->
        <div v-if="isAdmin" class="alias-edit">
          <el-switch v-model="a.enabled" :active-text="t('models.aliasEnabled')" />
          <el-select v-model="a.target" class="alias-sel" clearable
                     :placeholder="t('models.aliasTargetPick')">
            <el-option v-for="o in aliasOptions" :key="o.id" :value="o.id"
                       :label="o.label" :disabled="!o.ok" />
          </el-select>
          <span style="flex:1"></span>
          <el-button type="primary" size="small" :disabled="aliasSaveDisabled"
                     :loading="aliasSaving" @click="saveAlias()">
            {{ t('models.aliasSave') }}
          </el-button>
        </div>
        <div class="alias-hint">
          <div>{{ t('models.aliasLine', { id: a.name }) }}</div>
          <div>{{ t('models.aliasInherit') }}</div>
          <div v-if="isAdmin">{{ t('models.aliasPickHint') }}</div>
          <div v-if="!a.target" class="alias-warn">{{ t('models.aliasNotConfigured', { id: a.name }) }}</div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { api, errText } from '../api'
import { useSessionStore } from '../store/session'
import Icon from '../components/Icon.vue'

const router = useRouter()
const { t } = useI18n()
const store = useSessionStore()
const isAdmin = computed(() => store.isAdmin)
const items = ref<any[]>([])
const health = ref<any>({})
const loading = ref(false)
const err = ref('')

const typeKeyMap: Record<string, string> = { text: 'models.text', image: 'models.image', video: 'models.video' }
const typeClsMap: Record<string, string> = { text: 'mute', image: 'warn', video: 'warn' }
function typeKey(ty: string) { return typeKeyMap[ty] || ty }
function typeCls(ty: string) { return typeClsMap[ty] || 'mute' }

// ── 支持的格式（第二十七轮）──
// 取值范围与后端 PROTOCOLS 一致：chat/completions（OpenAI 兼容线）、messages（Anthropic 线）、
// responses（OpenAI Responses 线）。**名字直接取各家标准端点名**，不另起中文别名 —— 配置、
// 日志、前端标签、上游文档四处同名，出问题时对得上号。
function protocolsOf(row: any): string[] {
  if (!row || row.type !== 'text') return []     // 图像/视频模型走专用端点，没有协议线概念
  return (row.protocols as string[]) || []
}
// 每个格式标签的悬浮说明：这条线对应哪个端点（点进说明文档也是这个对应关系）
function protoTitle(p: string): string { return `POST /v1/${p}` }

// ── 测速（2026-10-12：单独测速改为并发）──────────────────────────
//   两套状态分开记：
//     · 一键测速（runSpeedtest）：整轮**串行**——latTesting = 整轮在跑、latCurrentId = 整轮当前那一行。
//       串行是老板定的口味（测一个显示一个），且并发会把免费额度瞬间打满 → 上游 429，
//       结果会刷成一片「失败」，反而失去参考价值。
//     · 单独测速（retestOne）：**可并发**——每行独立（latRunning 记着正在测的 id），
//       不用等上一个回来才能点下一个。上限 SPEEDTEST_MAX_CONCURRENCY 是别让手一抖
//       把全部免费档一次轰出去（免费档 429 同样会把结果刷成失败）。
const SPEEDTEST_MAX_CONCURRENCY = 3
const latTesting = ref(false)
const latCurrentId = ref('')   // 整轮测速当前测到的模型 id：该行延迟位显示加载图标
const latRunning = ref<Record<string, boolean>>({})   // 正在单独测的模型 id（可同时多个）
const latRunningCount = computed(() => Object.keys(latRunning.value).length)
// protocol 由后端返回：探针**按模型自己的协议线**挑一条（优先级 chat → messages → responses），
//   记下来才能在悬浮提示里说清「这次多少毫秒是走哪条线测的」——多线模型不写清楚会让人误解。
const latByModel = ref<Record<string, { ok: boolean; latency_ms: number | null; error: string; protocol: string }>>({})

// 探一次 = 一个模型一次请求；出错不抛，统一回一行结果（整轮 / 单测共用）
async function probeOne(id: string) {
  try {
    const j = await api('/v1/models/speedtest', { method: 'POST', body: JSON.stringify({ model: id }) })
    const r: any[] = (j && j.results) || []
    const hit = r[0]
    return hit
      ? { ok: !!hit.ok, latency_ms: hit.latency_ms ?? null, error: hit.error || '', protocol: hit.protocol || '' }
      : { ok: false, latency_ms: null, error: t('models.speedtestFail'), protocol: '' }
  } catch (e: any) {
    return { ok: false, latency_ms: null, error: (e && e.message) || String(e), protocol: '' }
  }
}

async function runSpeedtest() {
  if (latTesting.value || latRunningCount.value) return   // 整轮在跑 / 有单测在飞 → 不开整轮
  // 逐个测速：按列表顺序，测一个立刻显示那一行、再测下一个；当前测的行显示加载图标。
  //   串行天然不会把免费额度瞬间打满（并发时免费档供应商容易 429）。
  const ids = textModelRows.value.map((m) => m.id)
  latByModel.value = {}
  latTesting.value = true
  for (const id of ids) {
    latCurrentId.value = id
    const row = await probeOne(id)   // 单个模型出错不中断整轮，标记失败后继续下一个
    latByModel.value = { ...latByModel.value, [id]: row }   // 响应式替换 → 该行即时更新
  }
  latCurrentId.value = ''
  latTesting.value = false
  ElMessage.success(t('models.speedtestDone', { n: ids.length }))
}

// 单个模型测速（每行常驻的 ⚡ 按钮）：只测这一个；**并发** —— 各测各的，不等别人回来
async function retestOne(id: string) {
  if (latTesting.value || latRunning.value[id]) return   // 整轮测速中 / 这一个已经在测 → 忽略
  if (latRunningCount.value >= SPEEDTEST_MAX_CONCURRENCY) {
    ElMessage.warning(t('models.testOneBusy', { n: SPEEDTEST_MAX_CONCURRENCY }))
    return
  }
  latRunning.value = { ...latRunning.value, [id]: true }
  try {
    const row = await probeOne(id)
    latByModel.value = { ...latByModel.value, [id]: row }
  } finally {
    const next = { ...latRunning.value }
    delete next[id]
    latRunning.value = next
  }
}

// 单测按钮的悬浮说明：说清现在为什么点不了（正在测这一个 / 并发已满）
function testOneHint(m: { id: string }): string {
  if (latRunning.value[m.id]) return t('models.testOneRunning')
  if (latRunningCount.value >= SPEEDTEST_MAX_CONCURRENCY) {
    return t('models.testOneBusy', { n: SPEEDTEST_MAX_CONCURRENCY })
  }
  return t('models.testOne')
}
function latText(id: string): string {
  const row = latByModel.value[id]
  if (row) {
    if (row.ok) return row.latency_ms != null ? row.latency_ms + ' ms' : t('models.failed')
    return t('models.failed')   // 完整错误在下方 st-err 整行展示，这里只留短标记
  }
  return '—'   // 未轮到 / 空闲（当前正在测的行由模板的加载图标分支显示，不走这里）
}
function latErr(id: string): string {
  const row = latByModel.value[id]
  return row && !row.ok ? (row.error || '') : ''
}
function latCls(id: string): string {
  const row = latByModel.value[id]
  return row ? (row.ok ? 'ok' : 'err') : 'mute'
}

// 第三十一轮: /v1/models 里除了真实模型，还有「虚拟模型 id（别名）」（带 alias_of）。
//   它**不是模型**：不进模型计数、不进测速列表、也不进下方模型表（它在自己的卡片里）——
//   否则 KPI 的「N 个模型」会把别名也算进去，一键测速还会对着 wjd 报一个无意义的失败。
const aliasItems = computed(() => items.value.filter((x: any) => x.alias_of))
const models = computed(() => items.value.filter((x: any) => !x.alias_of))

// ── 别名（第三十一轮）──
// admin：读 GET /config 的 aliases（**含 enabled** —— 停用的别名在 /v1/models 里看不到），
//   可改可存；没配过就给一行以 wjd 为名的空白模板（选完目标点保存即可）。
// member：读 /v1/models 里的 alias_of，只渲染数据行（没有编辑行；PUT /config 本就只认管理员+会话）。
const ALIAS_ID = 'wjd'      // 当前就这一个（老板 2026-09-18 定）；配置层支持多个，页面按列表渲染
const aliasEdit = ref<any[]>([])
const aliasSaving = ref(false)

// 可选目标：**文本 + 支持 chat/completions**。其余一律置灰（图像/视频模型、只认 messages/
//   responses 的模型）—— 置灰只是 UX，真正拦人的是保存期的配置校验（手改 YAML 也绕不过去）。
const aliasOptions = computed(() => models.value
  .filter((m: any) => m.type === 'text')
  .map((m: any) => {
    const lines = protocolsOf(m)
    const ok = lines.includes('chat/completions')
    const provider = m.provider_name || '—'
    // 不可选的选项把"为什么不能选"写进标签（否则用户只能猜自己哪里填错了）
    return { id: m.id, ok, label: ok ? `${m.id} · ${provider}` : `${m.id} · ${provider} · ${lines.join(' / ')}` }
  })
  // 可选的排前面（同一家供应商聚在一起），再按 id —— 30 多个模型里找目标不用来回扫
  .sort((a: any, b: any) => (a.ok === b.ok ? a.label.localeCompare(b.label) : (a.ok ? -1 : 1))))

const aliasRows = computed(() => (isAdmin.value
  ? aliasEdit.value
  : aliasItems.value.map((x: any) => ({ name: x.id, enabled: true, target: x.alias_of, note: x.alias_note || '' }))))

// 启用但没选目标 = 存下去必被服务端拦（"已启用但没写 target"）→ 按钮直接置灰
const aliasSaveDisabled = computed(() => aliasSaving.value || aliasEdit.value.some((a: any) => a.enabled && !a.target))

async function loadAlias() {
  try {
    const j = await api('/config')
    const al = (j && j.config && j.config.aliases) || {}
    const rows = Object.keys(al).map((name) => ({
      name, enabled: !!al[name].enabled, target: al[name].target || '', note: al[name].note || '',
    }))
    aliasEdit.value = rows.length ? rows : [{ name: ALIAS_ID, enabled: true, target: '', note: '' }]
  } catch (e: any) {
    if (e && e.status === 401) { router.push('/login'); return }
    ElMessage.error(t('models.loadErr') + ': ' + errText(e))
  }
}

async function saveAlias() {
  if (aliasSaving.value) return
  aliasSaving.value = true
  try {
    const aliases: Record<string, any> = {}
    for (const a of aliasEdit.value) {
      aliases[a.name] = { enabled: !!a.enabled, target: a.target || '', note: a.note || '' }
    }
    // PUT /config 的 body 形式：{config: <面板视图>} —— 只提交 aliases 这一段，
    //   服务端按段合并（其余段沿用文件原文），所以这里不会碰供应商/服务参数。
    await api('/config', { method: 'PUT', body: JSON.stringify({ config: { aliases } }) })
    const hit = aliasEdit.value.find((a: any) => a.enabled && a.target)
    ElMessage.success(hit ? t('models.aliasSaved', { id: hit.name, target: hit.target })
      : t('models.aliasDisabled'))
    await load()      // 保存即生效：重新拉一遍（/v1/models 与 /config 都以服务端为准）
  } catch (e: any) {
    if (e && e.status === 401) { router.push('/login'); return }
    ElMessage.error(t('models.aliasSaveFail') + ': ' + errText(e))
  } finally {
    aliasSaving.value = false
  }
}

const providerOf = computed(() => {
  const m: Record<string, string> = {}
  for (const x of models.value) m[x.id] = x.provider_name || '—'
  return m
})
const visionOf = computed(() => {
  const m: Record<string, boolean> = {}
  for (const x of models.value) m[x.id] = !!x.vision
  return m
})

const textModelRows = computed(() =>
  models.value.filter((x) => x.type === 'text').map((m) => ({
    id: m.id,
    provider: m.provider_name || '—',
    vision: !!m.vision,
    // 免费模型（2026-09-21）：与表格「能力」列同一份数据
    free: !!m.free,
    // 免费是否带期限（2026-09-24）：Agnes 的限时免费档，标签文案换成「限时免费」
    free_limited: !!m.free_limited,
    // 模型级强制参数（第二十五轮）：被上游固定住的采样参数，用挂锁标注出来。
    paramNote: paramKeys(m).length ? paramNote(m) : '',
    // 支持的格式（第二十七轮）：悬浮这一行就能看到「能用哪几条线 + 本次测速走的哪条」
    formats: protocolsOf(m),
    // 2026-11-19（老板要求）：OpenCode Go 的套餐额度（每月能调多少）与训练策略。
    //   后端 /v1/models 的 go 字段（app/gomodels.py 从官方 models 接口拉取，缓存 6 小时）；
    //   非 OpenCode 供应商没有这个字段 → 该列显示「—」。
    goMeta: m.go || null,
  })),
)

// 测速行的悬浮提示：先说这个模型支持哪些格式，再说这次测的是哪条线
//   （多线模型不标注的话，"12 ms"到底测的是哪条线是看不出来的）。
function rowTitle(m: any): string {
  const lines = (m.formats || []).join(' / ') || t('models.protocolNa')
  const p = latByModel.value[m.id]?.protocol
  return p
    ? `${t('models.protocolHintRow', { lines })}· ${t('models.probedLine', { p })}`
    : t('models.protocolHintRow', { lines })
}

// ── 免费标注（2026-09-24 老板：Agnes 也要标免费 / 限时免费）──
// 后端 /v1/models 给 free（是否免费）+ free_limited（免费是否带期限，来自官方
// 「当前限时免费」措辞）。限时档文案单独一个，别让人以为它会一直免费。
function freeText(m: any): string {
  return m && m.free_limited ? t('models.freeLimitedTag') : t('models.freeTag')
}
function freeHint(m: any): string {
  return m && m.free_limited ? t('models.freeLimitedHint') : t('models.freeHint')
}

// ── OpenCode Go 套餐额度 / 训练策略（2026-11-19 老板要求）──
// 数据来自后端 /v1/models 的 go 字段（app/gomodels.py ← 官方 models 接口 go.monthly_usage）。
// 官方口径：monthly_usage 是「只用这一个模型时，各套餐每月额度能覆盖多少用量」（美元）。
// 单元格里只显示默认档（Go），三档明细与零保留说明放悬浮提示。
const GO_PLAN_KEYS = ['go', 'go-plus', 'go-teams'] as const

function goUsageOf(m: any): Record<string, number> {
  return (m && m.goMeta && m.goMeta.monthly_usage) || {}
}

function goQuotaText(m: any): string {
  const u = goUsageOf(m)
  if (u.go) return `$${u.go}`
  if (m && m.free) return t('models.goQuotaFree')
  return '—'
}

function goQuotaHint(m: any): string {
  const u = goUsageOf(m)
  const parts: string[] = []
  if (GO_PLAN_KEYS.some((k) => u[k])) {
    parts.push(t('models.goQuotaValues', {
      go: u.go ?? '—',
      plus: u['go-plus'] ?? '—',
      teams: u['go-teams'] ?? '—',
    }))
  } else {
    parts.push(t('models.goQuotaHint'))
  }
  if (m && m.goMeta && m.goMeta.zdr) parts.push(t('models.goZdrHint'))
  return parts.join(' · ')
}

function goTrains(m: any): boolean {
  return !!(m && m.goMeta && m.goMeta.training)
}

// ── 模型级强制参数（第二十五轮）──
// 后端 /v1/models 在 params 里给出「该模型发往上游前会被强制覆盖的参数」
// （例：kimi-k2.7-code 只接受 temperature=1）。这里只做展示，不提供编辑入口。
function paramKeys(m: any): string[] {
  return Object.keys((m && m.params) || {})
}
function paramNote(m: any): string {
  const ps = (m && m.params) || {}
  const txt = paramKeys(m).map((k) => `${k}=${ps[k]}`).join(', ')
  return t('models.paramLocked', { p: txt })
}

const keySet = computed(() => {
  const ks: Record<string, boolean> = {}
  for (const p of Object.values(health.value.providers || {}) as any) ks[p.name] = !!p.api_key_set
  return ks
})
const modelRows = computed(() => models.value.map((m) => ({ ...m, key_set: keySet.value[m.provider_name] })))

const providerRows = computed(() => {
  const p = health.value.providers || {}
  return Object.keys(p).map((k) => {
    const c = String(p[k].circuit || '').toUpperCase()
    return {
      k,                                    // 供应商 key（模板里靠它判断是不是 opencode）
      name: p[k].name,
      models: p[k].models,
      keySet: !!p[k].api_key_set,
      cls: c === 'CLOSED' ? 'ok' : c === 'HALF_OPEN' ? 'warn' : c === 'OPEN' ? 'err' : 'mute',
      text: t(`dashboard.circ_${String(p[k].circuit || '').toLowerCase() || ''}`),
    }
  })
})

const cards = computed(() => [
  { k: t('models.model'), v: models.value.length, note: t('models.providerCount2', { n: providerRows.value.length }) },
  { k: t('models.textModels'), v: models.value.filter((m) => m.type === 'text').length, note: t('models.visionTag') + ' · ' + models.value.filter((m) => m.vision).length },
  { k: t('models.imageModels'), v: models.value.filter((m) => m.type === 'image').length, note: t('images.title') },
])

async function load() {
  loading.value = true
  try {
    const j = await api('/v1/models')
    items.value = j.data || []
    try { health.value = await api('/health') } catch { /* 可选 */ }
    if (isAdmin.value) await loadAlias()      // 别名映射（管理员才有 /config 读权限）
  } catch (e: any) {
    if (e && e.status === 401) { router.push('/login'); return }
    err.value = t('models.loadErr') + ': ' + ((e && e.message) || String(e))
  } finally {
    loading.value = false
  }
}

// ── OpenCode Go 套餐用量（每 10 秒刷新）──────────────────────────────────
//   只有 opencode 供应商需要这份数据；网关侧缓存 8 秒，所以 10 秒轮询不会打穿上游。
const ocUsage = ref<any>(null)
const ocUsageErr = ref('')
let ocTimer: ReturnType<typeof setInterval> | null = null
let tickTimer: ReturnType<typeof setInterval> | null = null
// 倒计时用的「现在」：每秒 +1，驱动 resetsAt 的剩余时间重算（不用等 10 秒轮询）
const nowTick = ref(Date.now())

/** 把「剩余毫秒」格式化成 17d 18h / 4h 40m / 44m（和官方控制台一致）。 */
function fmtRemain(ms: number): string {
  if (!isFinite(ms) || ms <= 0) return '—'
  const total = Math.floor(ms / 1000)
  const dd = Math.floor(total / 86400)
  const hh = Math.floor((total % 86400) / 3600)
  const mm = Math.floor((total % 3600) / 60)
  if (dd > 0) return `${dd}d ${hh}h`
  if (hh > 0) return `${hh}h ${mm}m`
  return `${mm}m`
}

async function loadOcUsage() {
  try {
    const j = await api('/providers/opencode/usage')
    ocUsage.value = (j && (j.usage || j)) || null
    ocUsageErr.value = ''
  } catch (e: any) {
    // 不弹 toast：轮询失败只在这里挂一句，页面不闪
    ocUsageErr.value = t('models.usageErr')
  }
}

// 三条窗口按「剩余越少越危险」着色：≥85% 红、≥60% 橙、其余绿
const usageWindows = computed(() => {
  const u = ocUsage.value || {}
  const defs: Array<{ key: string; label: string }> = [
    { key: 'rolling', label: 'models.usageRolling' },
    { key: 'weekly', label: 'models.usageWeekly' },
    { key: 'monthly', label: 'models.usageMonthly' },
  ]
  return defs.map((d) => {
    const w = u[d.key] || {}
    const pct = Math.max(0, Math.min(100, Math.round(Number(w.percent) || 0)))
    const cls = pct >= 85 ? 'err' : pct >= 60 ? 'warn' : 'ok'
    // 剩余时间：resetsAt 是 ISO 时间戳（UTC），减本地 now 得到毫秒差
    let resetText = '—'
    if (w.resetsAt) {
      const t = Date.parse(String(w.resetsAt))
      if (!isNaN(t)) resetText = fmtRemain(t - nowTick.value)
    }
    return { ...d, pct, cls, width: pct + '%', resetText }
  })
})

// 订阅续期 = 月度重置时间（官方控制台的「Renews in …」就是它）。
//   同时给出倒计时和绝对日期，方便对账。
const renewText = computed(() => {
  const m = (ocUsage.value || {}).monthly || {}
  if (!m.resetsAt) return '—'
  const t = Date.parse(String(m.resetsAt))
  if (isNaN(t)) return '—'
  const d = new Date(t)
  const pad = (n: number) => String(n).padStart(2, '0')
  const abs = `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
  return `${fmtRemain(t - nowTick.value)} · ${abs}`
})

onMounted(async () => {
  await load()
  await loadOcUsage()
  ocTimer = setInterval(loadOcUsage, 10_000)          // 数据每 10 秒拉一次
  tickTimer = setInterval(() => { nowTick.value = Date.now() }, 1_000)  // 倒计时每秒走
})

onUnmounted(() => {
  if (ocTimer) { clearInterval(ocTimer); ocTimer = null }
  if (tickTimer) { clearInterval(tickTimer); tickTimer = null }
})
</script>

<style scoped>
.chain { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
.chain-item { display: inline-flex; align-items: center; gap: 6px; }
.arrow { color: var(--muted-2); }
.vision { color: var(--primary); }
.plock { color: var(--warn); }
/* 免费模型：绿色系，跟「视觉」(主题色) / 「参数固定」(橙) 区分开；跟在模型名后面 */
.pill.free { background: rgba(16, 185, 129, 0.14); color: #059669; }
/* OpenCode Go 的套餐额度（2026-11-19）：中性蓝，与免费（绿）/ 参数固定（橙）区分 */
.pill.go-quota { background: rgba(59, 130, 246, 0.12); color: #2563eb; }
/* 免费标注的间距（2026-09-24 老板：间隔不一样）——
   表格单元格里是行内排布、没有 flex gap，靠这个 margin 与模型名分开；
   测速行是 flex（.st-row gap: 8px），必须把 margin 归零：否则标签左侧 8+6=14px、
   右侧只有 8px，跟其它行「模型名 → 供应商名」的节奏对不上。左右统一由 gap 决定。 */
.name-free { margin-left: 6px; vertical-align: middle; }
.st-row .name-free { margin-left: 0; }
/* 支持的格式：三条线是并列关系（没有谁更优），统一用主题色弱底，
   不用 ok/warn/err —— 否则「messages」看起来像警告、「responses」像被禁用。 */
.proto {
  color: var(--primary); background: var(--primary-soft);
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;   /* 与全局 .code 同一套 */
  font-size: 11px; padding: 2px 7px;
}
.proto-cell { display: inline-flex; align-items: center; gap: 5px; flex-wrap: wrap; }
.proto-th { border-bottom: 1px dotted var(--muted-2); cursor: help; }
.prov { padding: 10px 0; border-bottom: 1px solid var(--line-2); }
.prov:last-child { border-bottom: 0; }
.prov-top { display: flex; align-items: center; gap: 8px; }
.prov-top b { font-size: 13px; }
.prov-meta { display: flex; align-items: center; gap: 8px; margin-top: 6px; font-size: 11.5px; }
/* OpenCode Go 套餐用量（供应商卡片内） */
/* 供应商用量详情卡片（独立卡片，放在供应商卡片下方） */
.usage-prov { padding: 2px 0 4px; }
/* 模型清单卡里的测速工具条（原「全部文本模型」卡的按钮，合并后挪到这里） */
.lat-toolbar { display: flex; align-items: center; gap: 8px; padding: 2px 0 8px; border-bottom: 1px dashed var(--line-2); margin-bottom: 4px; }
.usage-prov .prov-top { margin-bottom: 8px; }
.usage-row { display: flex; align-items: center; gap: 10px; padding: 5px 0; font-size: 12px; }
.usage-l { flex: 0 0 76px; color: var(--muted-2); }
.usage-bar { flex: 1; height: 6px; border-radius: 3px; background: var(--line-2); overflow: hidden; min-width: 80px; }
.usage-bar i { display: block; height: 100%; border-radius: 3px; transition: width .35s ease; }
.usage-bar i.ok { background: #10b981; }
.usage-bar i.warn { background: #f59e0b; }
.usage-bar i.err { background: #ef4444; }
.usage-p { flex: 0 0 40px; text-align: right; font-variant-numeric: tabular-nums; font-weight: 600; }
.usage-reset { flex: 0 0 120px; text-align: right; color: var(--muted-2); font-size: 11px; font-variant-numeric: tabular-nums; }
/* 订阅续期：卡片底部单独一行，和三条窗口隔开 */
.usage-renew { display: flex; align-items: center; gap: 10px; margin-top: 7px; padding-top: 7px; border-top: 1px dashed var(--line-2); font-size: 12px; }
.usage-renew-t { color: var(--muted-2); font-size: 11.5px; font-variant-numeric: tabular-nums; }
.usage-p.ok { color: #10b981; }
.usage-p.warn { color: #f59e0b; }
.usage-p.err { color: #ef4444; }
.usage-empty { font-size: 11px; padding: 2px 0; }
.cap { display: inline-flex; align-items: center; gap: 4px; }
.st { margin-top: 8px; border-top: 1px dashed var(--line-2); padding-top: 6px; }
.st-item { padding: 4px 0; }
.st-item + .st-item { border-top: 1px dashed var(--line); }
.st-row { display: flex; align-items: center; gap: 8px; font-size: 12px; }
.st-err {
  display: flex; align-items: flex-start; gap: 6px;
  margin: 4px 2px 2px; padding: 6px 8px;
  border-radius: 8px;
  background: var(--err-soft);
  color: var(--err);
  font-size: 11.5px; line-height: 1.55;
  overflow-wrap: anywhere;   /* 长错误（JSON / 无空格串）也能自动换行不溢出 */
  word-break: break-word;
}
.st-err-ico { flex: none; margin-top: 1px; color: var(--err); }
.st-err-txt { flex: 1; min-width: 0; }
/* 每个模型行右侧的「单独测速」图标按钮 */
.st-one {
  flex: none; display: inline-flex; align-items: center; justify-content: center;
  width: 24px; height: 24px; padding: 0; margin-left: 2px;
  border: 1px solid var(--line); background: transparent; color: var(--muted);
  border-radius: 8px; cursor: pointer; transition: color .15s, border-color .15s, background .15s;
}
.st-one:hover:not(:disabled) { color: var(--primary); border-color: var(--primary); background: var(--primary-soft); }
.st-one:disabled { opacity: 0.45; cursor: not-allowed; }
/* 当前正在测的模型行：延迟位显示一个旋转加载图标 */
.st-spin {
  display: inline-block; width: 12px; height: 12px; vertical-align: middle;
  border: 2px solid var(--line); border-top-color: var(--primary);
  border-radius: 50%; animation: st-spin 0.7s linear infinite;
}
@keyframes st-spin { to { transform: rotate(360deg); } }
@media (prefers-reduced-motion: reduce) { .st-spin { animation-duration: 1.6s; } }
.st-title { font-weight: 600; color: var(--text); }
.st-prov { flex: 1; }
.st-lat { min-width: 88px; text-align: center; }
.st-loading { font-style: italic; }
.lat-head { display: flex; align-items: center; gap: 8px; padding: 2px 0 6px; }
/* 第三十一轮：别名卡片（别名不是模型，用"指针"感的排版：名字 → 目标）。
   2026-09-18 老板：卡片的副标题与 member 的「只读：…」提示都删掉，只留数据行 + 说明。 */
.alias { padding: 10px 0; }
.alias + .alias { border-top: 1px dashed var(--line); }
.alias-top { display: flex; align-items: center; gap: 8px; font-size: 13px; }
.alias-ico { flex: none; color: var(--primary); }
.alias-id {
  color: var(--primary); background: var(--primary-soft);
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 11.5px; padding: 2px 8px;
}
.alias-arrow { color: var(--muted-2); }
.alias-edit { display: flex; align-items: center; gap: 10px; margin-top: 10px; flex-wrap: wrap; }
.alias-sel { width: 340px; max-width: 100%; }
.alias-hint { margin-top: 8px; font-size: 11.5px; line-height: 1.65; color: var(--muted-2); }
.alias-warn { color: var(--warn); }
</style>
