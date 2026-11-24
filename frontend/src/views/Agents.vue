<template>
  <!-- 智能体页 = 内嵌的完整 DeepSeek Harness（整页 iframe，不留网关自己的外壳） -->
  <div class="dsh-page">
    <iframe
      ref="frame"
      v-if="url"
      :src="url"
      class="dsh-frame"
      allow="clipboard-read; clipboard-write; fullscreen"
      referrerpolicy="no-referrer"
      @load="onFrameLoad"
    />

    <div v-else class="dsh-state">
      <p v-if="loading">{{ t('agents.dshLoading') }}</p>
      <template v-else>
        <p>{{ t('agents.dshNotReady') }}</p>
        <el-button type="primary" @click="load">{{ t('agents.retry') }}</el-button>
      </template>
    </div>

    <!-- 加载中：盖一层，避免 iframe 白屏闪一下 -->
    <div v-if="url && !loaded" class="dsh-mask">{{ t('agents.dshLoading') }}</div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { dshEntry } from '../lib/agents'
import { useSessionStore } from '../store/session'

const { t } = useI18n()
const store = useSessionStore()

const url = ref('')
const loading = ref(true)
const loaded = ref(false)
const frame = ref<HTMLIFrameElement | null>(null)

/** 管理员看完整界面；普通用户只留聊天区（隐藏 DSH 左侧的工作区/会话栏） */
const isAdmin = computed(() => store.isAdmin)

function onFrameLoad() {
  loaded.value = true
  if (!isAdmin.value) hideSidebar()
}

/**
 * 极简模式：往同源 iframe 里注入一段样式，把侧栏和拖拽条藏掉，聊天区铺满。
 * DSH 的 class 是 CSS Modules 加的哈希前缀，所以用 [class*="xxx"] 选择器，升级也不会失效。
 */
function hideSidebar() {
  const doc = frame.value?.contentDocument
  if (!doc) return
  const STYLE_ID = 'gw-mini-agent'
  if (doc.getElementById(STYLE_ID)) return
  const el = doc.createElement('style')
  el.id = STYLE_ID
  el.textContent = `
    /* 布局是 grid：列宽写死在 grid-template-columns 上，只藏元素不够，得改列 */
    [class*="frame"] { grid-template-columns: 0 1fr 0 !important; }
    [class*="sidebarCol"], [class*="handle"], [class*="rightbarCol"] { display: none !important; }
    [class*="centerCol"] { width: auto !important; flex: 1 1 auto !important; }
    /* 工作区选择器也藏掉：普通用户只有一个智能体，不该让他挑工作区 */
    button[class*="_workspace"], [class*="heroWorkspaceRow"] { display: none !important; }
  `
  doc.head.appendChild(el)
}

async function load() {
  loading.value = true
  loaded.value = false
  try {
    const j = await dshEntry()
    url.value = j.ready && j.url ? j.url : ''
  } catch {
    url.value = ''
  } finally {
    loading.value = false
  }
}

onMounted(load)
</script>

<style scoped>
/* 顶栏约 56px，其余铺满；用 dvh 兼容移动端地址栏 */
.dsh-page {
  position: relative;
  height: calc(100vh - 56px);
  min-height: 420px;
  background: #fff;
}
.dsh-frame {
  display: block;
  width: 100%;
  height: 100%;
  border: 0;
}
.dsh-state {
  height: 100%;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 12px;
  color: var(--el-text-color-secondary);
  font-size: 14px;
}
.dsh-mask {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--el-text-color-secondary);
  font-size: 13px;
  background: #fff;
}
</style>
