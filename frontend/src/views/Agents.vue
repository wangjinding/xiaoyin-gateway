<template>
  <!-- 智能体页 = 内嵌「小银智能体」（整页 iframe，不留网关自己的外壳） -->
  <div class="dsh-page">
    <iframe
      v-if="url"
      :src="url"
      class="dsh-frame"
      allow="clipboard-read; clipboard-write; fullscreen"
      referrerpolicy="no-referrer"
      @load="loaded = true"
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
import { onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { dshEntry } from '../lib/agents'

const { t } = useI18n()

const url = ref('')
const loading = ref(true)
const loaded = ref(false)
const frame = ref<HTMLIFrameElement | null>(null)

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
