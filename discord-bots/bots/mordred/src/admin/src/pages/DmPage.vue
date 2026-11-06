<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import {
  NAlert, NButton, NCard, NDatePicker, NForm, NFormItem, NInput,
  NInputNumber, NSelect, NSpace, NSwitch, NTag, NText,
} from 'naive-ui'
import { api } from '../api'
import { toastError, toastSuccess } from '../feedback'

interface DmUser { user_id: string; greetings_opt_in: boolean; created_at: string | null }
interface Campaign {
  id: string; kind: string; name: string; scheduled_at: string;
  status: string; target_user_id: string | null; deliveries: Record<string, number>
}

const loading = ref(false)
const settings = reactive({ enabled: true, daily_limit: 10, timezone: 'Asia/Shanghai' })
const users = ref<DmUser[]>([])
const campaigns = ref<Campaign[]>([])
const manual = reactive({ user_id: null as string | null, content: '' })
const holiday = reactive({ name: '', content: '', scheduled_at: Date.now() + 3600000 })

const userOptions = computed(() => users.value.map((u) => ({
  label: `${u.user_id}${u.greetings_opt_in ? ' · 已订阅祝福' : ''}`,
  value: u.user_id,
})))

function deliverySummary(c: Campaign): string {
  const entries = Object.entries(c.deliveries ?? {})
  return entries.length ? entries.map(([k, v]) => `${k}: ${v}`).join(' / ') : '尚未生成投递'
}

async function load(): Promise<void> {
  loading.value = true
  try {
    const [s, u, c] = await Promise.all([
      api.get<typeof settings>('dm/settings'),
      api.get<{ items: DmUser[] }>('dm/users'),
      api.get<{ items: Campaign[] }>('dm/campaigns'),
    ])
    Object.assign(settings, s)
    users.value = u.items
    campaigns.value = c.items
  } finally { loading.value = false }
}

async function saveSettings(): Promise<void> {
  await api.put('dm/settings', settings)
  toastSuccess('私信设置已保存，Bot 最迟 15 秒内生效')
}

async function sendManual(): Promise<void> {
  if (!manual.user_id || !manual.content.trim()) { toastError('请选择用户并填写内容'); return }
  await api.post('dm/manual', { user_id: manual.user_id, content: manual.content.trim() })
  manual.content = ''
  toastSuccess('留言已入队，将由 Bot 发送')
  await load()
}

async function createHoliday(): Promise<void> {
  if (!holiday.name.trim() || !holiday.content.trim()) { toastError('请填写活动名称与祝福内容'); return }
  await api.post('dm/campaigns', {
    name: holiday.name.trim(), content: holiday.content.trim(),
    scheduled_at: new Date(holiday.scheduled_at).toISOString(),
  })
  holiday.name = ''; holiday.content = ''
  toastSuccess('节日祝福已排期，只会发送给主动订阅的用户')
  await load()
}

async function setStatus(id: string, status: 'paused' | 'scheduled' | 'cancelled'): Promise<void> {
  await api.put(`dm/campaigns/${id}/status`, { status })
  toastSuccess('活动状态已更新')
  await load()
}

onMounted(() => void load())
</script>

<template>
  <n-space vertical :size="16">
    <n-alert type="info" title="发送边界">
      普通管理员无权使用本页；手动留言仅能发给主动私信过 Mordred 的用户，节日祝福仅发给明确订阅者。用户可发送“取消祝福”随时退订。
    </n-alert>

    <n-card title="私信聊天设置" size="small">
      <n-form inline label-placement="left">
        <n-form-item label="启用"><n-switch v-model:value="settings.enabled" /></n-form-item>
        <n-form-item label="每日成功回复上限"><n-input-number v-model:value="settings.daily_limit" :min="1" :max="100" /></n-form-item>
        <n-form-item label="重置时区"><n-input v-model:value="settings.timezone" disabled style="width: 170px" /></n-form-item>
        <n-button type="primary" :loading="loading" @click="saveSettings">保存</n-button>
      </n-form>
    </n-card>

    <n-card title="owner_user 手动留言" size="small">
      <n-form label-placement="top">
        <n-form-item label="收件用户"><n-select v-model:value="manual.user_id" filterable :options="userOptions" placeholder="选择已建立私信的用户" /></n-form-item>
        <n-form-item label="留言内容"><n-input v-model:value="manual.content" type="textarea" :maxlength="1800" show-count :autosize="{ minRows: 4, maxRows: 10 }" /></n-form-item>
      </n-form>
      <n-button type="primary" @click="sendManual">入队发送</n-button>
    </n-card>

    <n-card title="节日祝福排期" size="small">
      <n-form label-placement="top">
        <n-form-item label="活动名称"><n-input v-model:value="holiday.name" maxlength="120" /></n-form-item>
        <n-form-item label="发送时间"><n-date-picker v-model:value="holiday.scheduled_at" type="datetime" /></n-form-item>
        <n-form-item label="祝福内容（可用 {display_name}）"><n-input v-model:value="holiday.content" type="textarea" :maxlength="1800" show-count :autosize="{ minRows: 4, maxRows: 10 }" /></n-form-item>
      </n-form>
      <n-button type="primary" @click="createHoliday">创建排期</n-button>
    </n-card>

    <n-card title="最近任务" size="small">
      <n-space v-if="campaigns.length" vertical :size="10">
        <n-card v-for="c in campaigns" :key="c.id" size="small">
          <n-space vertical :size="6">
            <n-space align="center"><n-text strong>#{{ c.id }} · {{ c.name }}</n-text><n-tag size="small">{{ c.kind }}</n-tag><n-tag size="small" type="info">{{ c.status }}</n-tag></n-space>
            <n-text depth="3">{{ new Date(c.scheduled_at + 'Z').toLocaleString() }} · {{ deliverySummary(c) }}</n-text>
            <n-space v-if="!['completed', 'completed_with_errors', 'cancelled'].includes(c.status)">
              <n-button v-if="c.status !== 'paused'" size="tiny" @click="setStatus(c.id, 'paused')">暂停</n-button>
              <n-button v-else size="tiny" @click="setStatus(c.id, 'scheduled')">恢复</n-button>
              <n-button size="tiny" type="error" ghost @click="setStatus(c.id, 'cancelled')">取消</n-button>
            </n-space>
          </n-space>
        </n-card>
      </n-space>
      <n-text v-else depth="3">暂无任务</n-text>
    </n-card>
  </n-space>
</template>
