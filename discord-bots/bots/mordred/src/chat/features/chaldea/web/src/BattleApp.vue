<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { setupChildBridge } from './child-bridge'

interface Effect { kind: string; value?: number; duration?: number; remaining?: number; round_remaining?: number; target?: string }
interface Combatant {
  slot: number
  servant_id: string
  level: number
  np_level: number
  attack: number
  speed: number
  hp: number
  max_hp: number
  np: number
  stars: number
  cooldowns: number[]
  buffs: Effect[]
  debuffs: Effect[]
}
interface Skill { name: string; description: string; cooldown: number; effects: Effect[] }
interface Passive { name: string; description: string; effects: Effect[] }
interface Servant {
  id: string
  name: string
  class: string
  rarity: number
  hp: number
  attack: number
  speed: number
  passives: Passive[]
  skills: Skill[]
  np: { name: string; card: string; target: string; multiplier: number; effects: Effect[]; quote?: string | null; cg_url?: string | null }
  art_url: string | null
  skill_art_url: string | null
  released: boolean
}
interface BattleCommand {
  servant_slot: number
  kind: 'attack' | 'np'
  target_slot?: number
}
interface SkillCommand { servant_slot: number; kind: 'skill'; skill_index: number; target_slot?: number }
interface TargetMode { side: 'ally' | 'enemy'; queue: 'skill' | 'command'; command: BattleCommand | SkillCommand; prompt: string }
interface BattleEvent {
  type: 'skill' | 'attack' | 'np' | 'damage' | 'buff' | 'debuff' | 'heal' | 'critical' | 'tactic' | 'trap'
  source_player_id?: string
  source_slot?: number
  target_player_id?: string
  target_slot?: number
  value?: number
  chance?: number
  label?: string
}
interface TacticalState {
  master_template?: string
  master_available?: Record<string, boolean>
  magic_card?: string
  magic_previous?: string | null
  magic_round?: number
  magic_used?: boolean
  trap_card?: string
  trap_round?: number
  trap_charges: number
  armed_trap: string | boolean | null
  used_this_phase?: boolean
}
interface TacticalItem { id: string; name: string; description: string; effects?: Effect[] }
interface MasterTemplate { id: string; name: string; description: string; skill_ids: string[]; magic_pool: string[]; trap_pool: string[] }
interface TacticalCatalogue {
  master_templates: MasterTemplate[]
  master_skills: TacticalItem[]
  magic_cards: TacticalItem[]
  trap_cards: TacticalItem[]
}
interface BattleState {
  match_id: string
  status: 'active' | 'finished'
  turn: number
  phase_no: number
  state_version: number
  active_player_id: string
  active_servant_slot: number
  first_player_id: string
  initiative_order: { player_id: string; servant_slot: number; speed: number }[]
  initiative_index: number
  winner_id: string | null
  teams: Record<string, Combatant[]>
  log: string[]
  last_events: BattleEvent[]
  phase_used_skills?: Record<string, number[][]>
  tactics: Record<string, TacticalState>
}
interface BattlePayload {
  id: string
  status: string
  state: BattleState
  player_id: string
  opponent_id: string
  catalogue: Record<string, Servant>
  tactical_catalogue: TacticalCatalogue
  spectator?: boolean
  viewer_id?: string
}
interface BattleComment { id: number; user_id: string; content: string; created_at: string }
interface DanmakuItem extends BattleComment { lane: number }

const baseUrl = import.meta.env.BASE_URL
const loading = ref(true)
const error = ref('')
const waiting = ref(false)
const cancelled = ref(false)
const payload = ref<BattlePayload | null>(null)
const commands = ref<Record<number, BattleCommand>>({})
const pendingSkill = ref<SkillCommand | null>(null)
const tacticalOpen = ref(false)
const targetMode = ref<TargetMode | null>(null)
const selectedSlot = ref(0)
const activeEvent = ref<BattleEvent | null>(null)
const accessToken = ref<string | null>(null)
const spectating = ref(new URLSearchParams(window.location.search).get('mode') === 'spectate')
const comments = ref<BattleComment[]>([])
const danmakuItems = ref<DanmakuItem[]>([])
const danmakuEnabled = ref(true)
const commentText = ref('')
const commentError = ref('')
const commentSending = ref(false)
let commentsLoaded = false
let lastCommentId = 0
let pollTimer: number | null = null
let observedVersion = 0
let eventTimers: number[] = []
const NP_CINEMATIC_DURATION_MS = 5200

const state = computed(() => payload.value?.state ?? null)
const playerId = computed(() => payload.value?.player_id ?? '')
const myTeam = computed(() => state.value?.teams[playerId.value] ?? [])
const enemyTeam = computed(() => {
  if (!state.value || !payload.value) return []
  return state.value.teams[payload.value.opponent_id] ?? []
})
const myTactics = computed(() => state.value?.tactics?.[playerId.value] ?? null)
const enemyTactics = computed(() => state.value && payload.value ? state.value.tactics?.[payload.value.opponent_id] : null)
const masterTemplate = computed(() => payload.value?.tactical_catalogue.master_templates.find(item => item.id === myTactics.value?.master_template) ?? null)
const masterSkills = computed(() => {
  const allowed = new Set(masterTemplate.value?.skill_ids ?? [])
  return payload.value?.tactical_catalogue.master_skills.filter(item => allowed.has(item.id)) ?? []
})
const randomMagic = computed(() => payload.value?.tactical_catalogue.magic_cards.find(item => item.id === myTactics.value?.magic_card) ?? null)
const randomTrap = computed(() => payload.value?.tactical_catalogue.trap_cards.find(item => item.id === myTactics.value?.trap_card) ?? null)
const canAct = computed(() => !spectating.value && state.value?.status === 'active' && state.value.active_player_id === playerId.value)
const actionableTeam = computed(() => myTeam.value.filter(member => member.hp > 0 && !isStunned(member)))
const activeActor = computed(() => state.value?.initiative_order?.[state.value.initiative_index] ?? null)
const activeMember = computed(() => {
  if (!state.value || !activeActor.value) return null
  return state.value.teams[activeActor.value.player_id]?.find(member => member.slot === activeActor.value!.servant_slot) ?? null
})
const selectedMember = computed(() => {
  if (canAct.value) return myTeam.value.find(member => member.slot === state.value?.active_servant_slot) ?? null
  return myTeam.value.find(member => member.slot === selectedSlot.value) ?? actionableTeam.value[0] ?? myTeam.value[0]
})
const canSubmit = computed(() =>
  canAct.value &&
  Boolean(activeMember.value && (isStunned(activeMember.value) || commands.value[activeMember.value.slot])) &&
  !targetMode.value &&
  !pendingSkill.value &&
  !waiting.value,
)
const usedSkillSlots = computed(() => new Set(
  (state.value?.phase_used_skills?.[playerId.value] ?? []).map(item => Number(item[0])),
))
const pendingSkillData = computed(() => {
  if (!pendingSkill.value) return null
  const member = myTeam.value.find(item => item.slot === pendingSkill.value!.servant_slot)
  if (!member) return null
  return { member, servant: servant(member), skill: servant(member).skills[pendingSkill.value.skill_index] }
})
const npCinematic = computed(() => {
  const event = activeEvent.value
  if (!event || event.type !== 'np' || event.source_player_id === undefined || event.source_slot === undefined || !state.value) return null
  const member = state.value.teams[event.source_player_id]?.find(item => item.slot === event.source_slot)
  if (!member) return null
  const data = servant(member)
  const imageUrl = data.np.cg_url ?? data.art_url
  if (!imageUrl) return null
  return {
    servant: data,
    np: data.np,
    imageUrl,
    quote: data.np.quote ?? `真名解放——${data.np.name}！`,
    customCg: Boolean(data.np.cg_url),
  }
})
const recentLog = computed(() => (state.value?.log ?? []).slice(-10).reverse())
const latestTurnLog = computed(() => {
  const logs = state.value?.log ?? []
  const marker = logs.map(line => line.startsWith('── 第 ')).lastIndexOf(true)
  return marker >= 0 ? logs.slice(marker) : logs.slice(-4)
})

function servant(member: Combatant): Servant {
  return payload.value!.catalogue[member.servant_id]
}

function hpPercent(member: Combatant): number {
  return Math.max(0, Math.round(member.hp / member.max_hp * 100))
}

function critChance(member: Combatant): number {
  const up = member.buffs.filter(effect => effect.kind === 'crit_chance_up').reduce((sum, effect) => sum + (effect.value ?? 0), 0)
  const down = member.debuffs.filter(effect => effect.kind === 'crit_chance_down').reduce((sum, effect) => sum + (effect.value ?? 0), 0)
  return Math.max(0, Math.min(100, 5 + member.stars * 2 + up - down))
}

function passiveSummary(data: Servant): string {
  return data.passives.map(passive => `${passive.name}：${passive.description}`).join('；')
}

function assetUrl(path: string): string {
  return baseUrl + path.replace(/^\//, '')
}

const insetSkillArtIds = new Set([
  'katsushika_hokusai_foreigner', 'cleopatra_assassin', 'senji_muramasa_saber',
  'musashi_saber', 'tamamo_no_mae_caster', 'kama_assassin', 'ryougi_shiki_assassin',
  'scathach_skadi_caster', 'semiramis_assassin', 'artoria_rhongomyniad_lancer',
  'okita_souji_saber', 'koyanskaya_light_assassin', 'solomon_grand_caster',
  'bb_moon_nurse_mooncancer', 'mash_decisive_shielder', 'minamoto_raikou_berserker',
  'nero_star_bride_beast', 'taira_kagekiyo_avenger', 'brynhild_lancer',
  'jeanne_archer_summer', 'ibuki_amano_murakumo_saber', 'melusine_lancer',
])

function skillStyle(data: Servant, index: number): Record<string, string> {
  if (!data.skill_art_url) return {}
  return {
    backgroundImage: `url(${assetUrl(data.skill_art_url)})`,
    backgroundPosition: `${index * 50}% 50%`,
    backgroundSize: `${insetSkillArtIds.has(data.id) ? 360 : 300}% auto`,
  }
}

function isStunned(member: Combatant): boolean {
  return member.debuffs.some(effect => effect.kind === 'stun' && (effect.remaining ?? 1) > 0)
}

const effectNames: Record<string, string> = {
  attack_up: '攻击', defense_up: '防御', card_up_b: 'Buster',
  card_up_a: 'Arts', card_up_q: 'Quick', card_up_all: '三色性能',
  evade: '回避', invincible: '无敌', sure_hit: '必中', taunt: '嘲讽', guts: '战续',
  attack_down: '攻击', defense_down: '防御', stun: '眩晕', crit_up: '暴击威力',
  crit_down: '暴击威力', crit_chance_up: '暴击率', crit_chance_down: '暴击率', poison: '毒', burn: '灼烧', regen: '再生', damage_cut: '减伤',
  np_gain_up: 'NP获取', np_damage_up: '宝具威力', np_damage_down: '宝具威力',
  quick_resist_down: 'Quick耐性', trait_damage_up: '特攻', star_gain_up: '星星获取',
  stars_per_turn: '每回合星星', np_per_turn: '每回合NP', hp_loss_per_turn: '每回合损血',
  debuff_immunity: '弱化无效', invincible_pierce: '无敌贯通', solemn_defense: '肃正防御',
  delayed_stun: '延迟眩晕', cooldown_reduce: '冷却缩短',
  speed_up: '速度', speed_down: '速度', damage_reflect: '伤害反射', execute: '处决',
}

function effectLabel(effect: Effect, debuff = false): string {
  const name = effectNames[effect.kind] || effect.kind
  const direction = debuff || effect.kind.endsWith('_down') ? '↓' : effect.kind.endsWith('_up') ? '↑' : ''
  const statusKinds = ['stun', 'taunt', 'sure_hit', 'invincible_pierce', 'delayed_stun']
  const countKinds = ['evade', 'solemn_defense', 'debuff_immunity']
  const flatKinds = ['poison', 'burn', 'regen', 'damage_cut', 'guts', 'stars_per_turn', 'np_per_turn', 'hp_loss_per_turn', 'cooldown_reduce']
  const value = statusKinds.includes(effect.kind)
    ? ''
    : countKinds.includes(effect.kind)
      ? ((effect.value ?? 1) > 1 ? `×${effect.value}` : '')
      : effect.value ? `${effect.value}${flatKinds.includes(effect.kind) ? '' : '%'}` : ''
  const turns = effect.kind === 'invincible' && effect.round_remaining
    ? `·本轮`
    : effect.remaining ? `·${effect.remaining}T` : ''
  return `${name}${direction}${value ? ` ${value}` : ''}${turns}`
}

function effectDescription(effect: Effect): string {
  const target: Record<string, string> = { self: '自身', ally: '一名队友', team: '己方全体', enemy: '一名敌人', enemy_team: '敌方全体', all_enemies: '敌方全体' }
  const immediate: Record<string, string> = { heal: '回复 HP', np_charge: '增加 NP', stars: '获得暴击星', debuff_cleanse: '解除弱化', buff_remove: '解除强化', np_drain: '减少 NP', cooldown_reduce: '缩短技能冷却' }
  const prefix = target[effect.target ?? 'self'] ?? '自身'
  if (immediate[effect.kind]) return `${prefix}${immediate[effect.kind]}${effect.value ? ` ${effect.value}` : ''}`
  if (effect.kind === 'execute') return `生命不高于 ${effect.value ?? 0}% 时立即处决${prefix}`
  if (effect.kind === 'invincible') return `${prefix}在整个行动轮内无敌，不限制抵挡次数`
  const duration = effect.duration ? `，持续 ${effect.duration} 回合` : ''
  if (['stun', 'taunt', 'sure_hit', 'invincible_pierce', 'delayed_stun'].includes(effect.kind)) return `${prefix}获得${effectNames[effect.kind]}${duration}`
  if (['evade', 'solemn_defense', 'debuff_immunity'].includes(effect.kind)) {
    const count = (effect.value ?? 1) > 1 ? ` ${effect.value} 次` : ''
    return `${prefix}获得${effectNames[effect.kind]}${count}${duration}`
  }
  if (effect.kind === 'guts') return `${prefix}获得战续（复活 ${effect.value ?? 1} HP）${duration}`
  const value = effect.value ? ` ${effect.value}${['poison', 'burn', 'regen', 'damage_cut', 'stars_per_turn', 'np_per_turn', 'hp_loss_per_turn'].includes(effect.kind) ? '' : '%'}` : ''
  const verb = effect.kind.endsWith('_down') ? '下降' : ['poison', 'burn'].includes(effect.kind) ? '附加' : '提升'
  return `${prefix}${effectNames[effect.kind] ?? effect.kind}${verb}${value}${duration}`
}

function skillSummary(skill: Skill): string {
  return skill.effects.map(effectDescription).join('；') + `；冷却 ${skill.cooldown} 回合`
}

function resetCommands() {
  const next: Record<number, BattleCommand> = {}
  const defaultTarget = enemyTeam.value.find(member => member.hp > 0)?.slot
  const member = canAct.value
    ? myTeam.value.find(item => item.slot === state.value?.active_servant_slot)
    : null
  if (member && member.hp > 0 && !isStunned(member)) {
    next[member.slot] = { servant_slot: member.slot, kind: 'attack', ...(defaultTarget === undefined ? {} : { target_slot: defaultTarget }) }
  }
  commands.value = next
  pendingSkill.value = null
  tacticalOpen.value = false
  selectedSlot.value = member?.slot ?? actionableTeam.value[0]?.slot ?? myTeam.value.find(item => item.hp > 0)?.slot ?? 0
  targetMode.value = null
}

function chooseAttack(slot: number) {
  if (waiting.value || !canAct.value || slot !== state.value?.active_servant_slot) return
  targetMode.value = { side: 'enemy', queue: 'command', command: { servant_slot: slot, kind: 'attack' }, prompt: `为 ${servant(myTeam.value[slot]).name} 选择攻击目标` }
}

function chooseSkill(slot: number, skillIndex: number) {
  const member = myTeam.value[slot]
  if (!member || slot !== state.value?.active_servant_slot || member.hp <= 0 || isStunned(member) || member.cooldowns[skillIndex] > 0 || waiting.value || !canAct.value) return
  if (usedSkillSlots.value.has(slot)) return
  const skill = servant(member).skills[skillIndex]
  const targets = new Set(skill.effects.map(effect => effect.target ?? 'self'))
  const command: SkillCommand = { servant_slot: slot, kind: 'skill', skill_index: skillIndex }
  if (targets.has('ally')) {
    targetMode.value = { side: 'ally', queue: 'skill', command, prompt: `为「${skill.name}」选择一名队友` }
  } else if (targets.has('enemy')) {
    targetMode.value = { side: 'enemy', queue: 'skill', command, prompt: `为「${skill.name}」选择一名敌人` }
  } else {
    pendingSkill.value = command
    targetMode.value = null
  }
}

function chooseNp(slot: number) {
  const member = myTeam.value[slot]
  if (!member || slot !== state.value?.active_servant_slot || member.hp <= 0 || isStunned(member) || member.np < 100 || waiting.value || !canAct.value) return
  const command: BattleCommand = { servant_slot: slot, kind: 'np' }
  if (servant(member).np.target === 'single') {
    targetMode.value = { side: 'enemy', queue: 'command', command, prompt: `为宝具「${servant(member).np.name}」选择目标` }
  } else {
    commands.value = { ...commands.value, [slot]: command }
    targetMode.value = null
  }
}

function pickTarget(side: 'ally' | 'enemy', slot: number) {
  if (!targetMode.value || targetMode.value.side !== side || waiting.value) return
  const team = side === 'ally' ? myTeam.value : enemyTeam.value
  const target = team.find(member => member.slot === slot)
  if (!target || target.hp <= 0) return
  const command = { ...targetMode.value.command, target_slot: slot }
  if (targetMode.value.queue === 'skill') {
    pendingSkill.value = command as SkillCommand
  } else {
    commands.value = { ...commands.value, [command.servant_slot]: command as BattleCommand }
  }
  targetMode.value = null
}

function targetCount(side: 'ally' | 'enemy', slot: number): number {
  const queued = [...Object.values(commands.value), ...(pendingSkill.value ? [pendingSkill.value] : [])]
  return queued.filter(command => {
    if (command.target_slot !== slot) return false
    if (command.kind === 'attack' || command.kind === 'np') return side === 'enemy'
    const skill = servant(myTeam.value[command.servant_slot]).skills[command.skill_index!]
    return skill.effects.some(effect => (effect.target === 'ally' ? side === 'ally' : effect.target === 'enemy' && side === 'enemy'))
  }).length
}

function actionDetail(member: Combatant): string {
  const command = commands.value[member.slot]
  if (!command) return '本回合无法行动'
  if (command.kind === 'np') return `${servant(member).np.target === 'all' ? '敌方全体' : '单体'}宝具 · 威力 ${servant(member).np.multiplier}%`
  const target = enemyTeam.value.find(item => item.slot === command.target_slot)
  return `普通攻击${target ? ` → ${servant(target).name}` : ''}`
}

function commandLabel(member: Combatant): string {
  if (member.hp <= 0) return '无法战斗'
  if (isStunned(member)) return '眩晕 · 本回合跳过'
  const command = commands.value[member.slot]
  if (command?.kind === 'np') return servant(member).np.name
  return '普通攻击'
}

function handleAllyClick(member: Combatant) {
  if (targetMode.value?.side === 'ally') pickTarget('ally', member.slot)
  else if (!canAct.value && member.hp > 0) selectedSlot.value = member.slot
}

function actorMember(actor: { player_id: string; servant_slot: number }): Combatant | null {
  return state.value?.teams[actor.player_id]?.find(member => member.slot === actor.servant_slot) ?? null
}

function actorName(actor: { player_id: string; servant_slot: number }): string {
  const member = actorMember(actor)
  return member ? servant(member).name : '未知灵基'
}

function unitEventClass(player: string, slot: number): Record<string, boolean> {
  const event = activeEvent.value
  return {
    'fx-cast': event?.type === 'skill' && event.source_player_id === player && event.source_slot === slot,
    'fx-attack': event?.type === 'attack' && event.source_player_id === player && event.source_slot === slot,
    'fx-np': event?.type === 'np' && event.source_player_id === player && event.source_slot === slot,
    'fx-hit': event?.type === 'damage' && event.target_player_id === player && event.target_slot === slot,
    'fx-critical': event?.type === 'critical' && event.target_player_id === player && event.target_slot === slot,
    'fx-buff': ['buff', 'heal'].includes(event?.type ?? '') && event?.target_player_id === player && event.target_slot === slot,
    'fx-debuff': event?.type === 'debuff' && event.target_player_id === player && event.target_slot === slot,
  }
}

function floatingEvent(player: string, slot: number): string {
  const event = activeEvent.value
  if (event?.target_player_id !== player || event.target_slot !== slot) return ''
  if (event.type === 'damage') return `-${event.value ?? 0}`
  if (event.type === 'critical') return `CRITICAL -${event.value ?? 0}`
  if (event.type === 'heal') return event.value ? `+${event.value}` : (event.label ?? '回复')
  if (event.type === 'buff') return event.label ?? '强化'
  if (event.type === 'debuff') return event.label ?? '弱化'
  return ''
}

function playEvents(events: BattleEvent[]) {
  eventTimers.forEach(timer => window.clearTimeout(timer))
  eventTimers = []
  const queue = events.slice(-14)
  let offset = 0
  queue.forEach((event) => {
    eventTimers.push(window.setTimeout(() => { activeEvent.value = event }, offset))
    offset += event.type === 'np' ? NP_CINEMATIC_DURATION_MS : ['skill', 'tactic', 'trap'].includes(event.type) ? 760 : event.type === 'critical' ? 680 : 480
  })
  eventTimers.push(window.setTimeout(() => { activeEvent.value = null }, offset + 240))
}

async function api<T>(path: string, options: RequestInit = {}): Promise<T> {
  if (!accessToken.value) throw new Error('未获得身份令牌，请从机器人命令打开战斗。')
  const response = await fetch(baseUrl + path.replace(/^\//, ''), {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${accessToken.value}`,
      ...(options.headers || {}),
    },
  })
  if (!response.ok) {
    const body = await response.json().catch(() => ({ detail: '请求失败' }))
    throw new Error(body.detail || `请求失败 (${response.status})`)
  }
  return response.json()
}

async function refresh(silent = false) {
  try {
    const endpoint = spectating.value ? 'api/spectate/state' : 'api/battle/state'
    const next = await api<BattlePayload>(endpoint)
    payload.value = next
    if (next.state.state_version !== observedVersion) {
      const shouldAnimate = observedVersion > 0
      observedVersion = next.state.state_version
      waiting.value = false
      resetCommands()
      if (shouldAnimate) playEvents(next.state.last_events ?? [])
    }
    await refreshComments(!commentsLoaded)
    error.value = ''
  } catch (err) {
    const message = err instanceof Error ? err.message : '无法载入战斗'
    if (message.includes('No battle found')) {
      cancelled.value = true
      payload.value = null
    } else if (!silent) {
      error.value = message
    }
  } finally {
    loading.value = false
  }
}

function commentAuthor(comment: BattleComment): string {
  if (comment.user_id === payload.value?.viewer_id || comment.user_id === playerId.value) return '御主 A'
  if (comment.user_id === payload.value?.opponent_id) return '御主 B'
  return `观众 ${comment.user_id.slice(-4)}`
}

function launchDanmaku(items: BattleComment[]) {
  if (!danmakuEnabled.value) return
  items.slice(-10).forEach((item, index) => {
    const entry: DanmakuItem = { ...item, lane: (item.id + index) % 6 }
    danmakuItems.value = [...danmakuItems.value.slice(-11), entry]
    window.setTimeout(() => {
      danmakuItems.value = danmakuItems.value.filter(current => current.id !== entry.id)
    }, 9000)
  })
}

async function refreshComments(initial = false) {
  if (!payload.value) return
  try {
    const result = await api<{ items: BattleComment[] }>(`api/battle/comments?battle_id=${encodeURIComponent(payload.value.id)}&after_id=${lastCommentId}`)
    if (!result.items.length) {
      commentsLoaded = true
      return
    }
    const known = new Set(comments.value.map(item => item.id))
    const fresh = result.items.filter(item => !known.has(item.id))
    comments.value = [...comments.value, ...fresh].slice(-30)
    lastCommentId = Math.max(lastCommentId, ...result.items.map(item => item.id))
    if (!initial) launchDanmaku(fresh)
    commentsLoaded = true
  } catch (err) {
    if (!initial) commentError.value = err instanceof Error ? err.message : '弹幕同步失败'
  }
}

async function sendComment() {
  const content = commentText.value.trim()
  if (!payload.value || !content || commentSending.value) return
  commentSending.value = true
  commentError.value = ''
  try {
    await api('api/battle/comments', {
      method: 'POST',
      body: JSON.stringify({ battle_id: payload.value.id, content }),
    })
    commentText.value = ''
    await refreshComments(false)
  } catch (err) {
    commentError.value = err instanceof Error ? err.message : '弹幕发送失败'
  } finally {
    commentSending.value = false
  }
}

async function submitAction() {
  if (!payload.value || !canSubmit.value) return
  waiting.value = true
  error.value = ''
  try {
    const result = await api<{ resolved: boolean; state: BattleState }>('api/battle/action', {
      method: 'POST',
      body: JSON.stringify({
        battle_id: payload.value.id,
        expected_version: payload.value.state.state_version,
        skills: [],
        commands: Object.values(commands.value).sort((a, b) => a.servant_slot - b.servant_slot),
      }),
    })
    if (result.resolved) {
      payload.value = { ...payload.value, state: result.state }
      observedVersion = result.state.state_version
      waiting.value = false
      resetCommands()
      playEvents(result.state.last_events ?? [])
    }
  } catch (err) {
    waiting.value = false
    error.value = err instanceof Error ? err.message : '行动提交失败'
  }
}

async function confirmSkill() {
  if (!payload.value || !pendingSkill.value || waiting.value || !canAct.value) return
  waiting.value = true
  error.value = ''
  try {
    const result = await api<{ resolved: boolean; state: BattleState }>('api/battle/skill', {
      method: 'POST',
      body: JSON.stringify({
        battle_id: payload.value.id,
        expected_version: payload.value.state.state_version,
        skill: pendingSkill.value,
      }),
    })
    payload.value = { ...payload.value, state: result.state }
    observedVersion = result.state.state_version
    pendingSkill.value = null
    waiting.value = false
    playEvents(result.state.last_events ?? [])
  } catch (err) {
    waiting.value = false
    error.value = err instanceof Error ? err.message : '技能释放失败'
  }
}

async function submitTactic(category: 'master' | 'magic' | 'trap', id: string) {
  if (!payload.value || waiting.value || !canAct.value || myTactics.value?.used_this_phase) return
  waiting.value = true
  error.value = ''
  try {
    const result = await api<{ resolved: boolean; state: BattleState }>('api/battle/tactic', {
      method: 'POST',
      body: JSON.stringify({
        battle_id: payload.value.id,
        expected_version: payload.value.state.state_version,
        tactic: { category, id },
      }),
    })
    payload.value = { ...payload.value, state: result.state }
    observedVersion = result.state.state_version
    tacticalOpen.value = false
    waiting.value = false
    playEvents(result.state.last_events ?? [])
  } catch (err) {
    waiting.value = false
    error.value = err instanceof Error ? err.message : '战术发动失败'
  }
}

async function abandonBattle() {
  if (!payload.value || !window.confirm('确定结束这场战斗吗？双方都会立即退出。')) return
  try {
    await api('api/battle/abandon', {
      method: 'POST',
      body: JSON.stringify({ battle_id: payload.value.id }),
    })
    cancelled.value = true
    payload.value = null
  } catch (err) {
    error.value = err instanceof Error ? err.message : '结束战斗失败'
  }
}

onMounted(async () => {
  const hash = new URLSearchParams(window.location.hash.replace(/^#/, ''))
  const browserTicket = hash.get('ticket')
  if (browserTicket) {
    accessToken.value = browserTicket
    window.history.replaceState({}, document.title, window.location.pathname)
  } else {
    const bridge = await setupChildBridge()
    accessToken.value = bridge?.accessToken ?? null
  }
  if (!accessToken.value) {
    loading.value = false
    error.value = '请从 Discord 对局消息的玩家入口或“观战与弹幕”按钮进入。'
    return
  }
  await refresh()
  pollTimer = window.setInterval(() => refresh(true), 1800)
})

onBeforeUnmount(() => {
  if (pollTimer !== null) window.clearInterval(pollTimer)
  eventTimers.forEach(timer => window.clearTimeout(timer))
})
</script>

<template>
  <main class="battle-shell">
    <div class="ambient ambient-one"></div><div class="ambient ambient-two"></div>
    <section v-if="loading" class="center-state"><div class="chaldea-mark">C</div><p>正在建立灵子演算连接…</p></section>
    <section v-else-if="cancelled" class="center-state error-state"><div class="chaldea-mark">✓</div><h1>战斗已经结束</h1><p>双方已解除对局占用，可以返回 Discord 重新发起挑战。</p></section>
    <section v-else-if="error && !payload" class="center-state error-state"><div class="chaldea-mark">!</div><h1>连接未完成</h1><p>{{ error }}</p></section>

    <template v-else-if="payload && state">
      <header class="battle-header glass-panel">
        <div><span class="eyebrow">CHALDEA SPIRITRON BOARD</span><h1>灵基棋盘演算</h1></div>
        <div class="turn-chip"><span>ROUND</span><strong>{{ state.turn }}</strong></div>
        <div :class="['status-chip', state.status, { enemy: !canAct }]">{{ spectating ? (state.status === 'active' ? `观战中 · ${activeMember ? servant(activeMember).name : ''} 行动` : '观战结束') : (state.status === 'active' ? (canAct ? (waiting ? '结算中' : `请指示 ${activeMember ? servant(activeMember).name : ''}`) : `等待 ${activeMember ? servant(activeMember).name : '对方'} 行动`) : '战斗结束') }}</div>
        <button v-if="!spectating" class="leave-button" @click="abandonBattle">结束战斗</button>
        <button v-else class="leave-button danmaku-toggle" @click="danmakuEnabled = !danmakuEnabled">弹幕 {{ danmakuEnabled ? '开' : '关' }}</button>
      </header>

      <nav v-if="state.status === 'active'" class="initiative-strip glass-panel" aria-label="本轮行动顺序">
        <span class="initiative-title">本轮行动顺序</span>
        <ol>
          <li v-for="(actor, index) in state.initiative_order" :key="actor.player_id + ':' + actor.servant_slot" :class="{ active: index === state.initiative_index, done: index < state.initiative_index, enemy: actor.player_id !== payload.player_id }">
            <span>{{ index + 1 }}</span><b>{{ actorName(actor) }}</b><small>SPD {{ actor.speed }}</small>
          </li>
        </ol>
      </nav>

      <section :class="['spiritron-board', { 'board-np-flash': activeEvent?.type === 'np' }]">
        <div class="board-grid"></div>
        <div v-if="danmakuEnabled" class="danmaku-layer" aria-live="polite">
          <div v-for="item in danmakuItems" :key="item.id" class="danmaku-item" :style="{ top: `${8 + item.lane * 9}%`, animationDelay: `${(item.id % 5) * 0.08}s` }"><b>{{ commentAuthor(item) }}</b><span>{{ item.content }}</span></div>
        </div>
        <div v-if="npCinematic" :class="['np-cinematic', { fallback: !npCinematic.customCg }]" role="status" aria-live="polite">
          <img :src="assetUrl(npCinematic.imageUrl)" :alt="npCinematic.np.name">
          <div class="np-cinematic-shade"></div>
          <div class="np-cinematic-copy"><span>NOBLE PHANTASM</span><h2>{{ npCinematic.np.name }}</h2><p>“{{ npCinematic.quote }}”</p><small>{{ npCinematic.servant.name }}</small></div>
        </div>
        <div v-if="activeEvent?.type === 'critical'" class="critical-banner"><span>CRITICAL</span><strong>-{{ activeEvent.value }} · 命中率 {{ activeEvent.chance ?? '?' }}%</strong></div>
        <div v-if="activeEvent?.type === 'tactic' || activeEvent?.type === 'trap'" class="tactic-banner"><span>{{ activeEvent.type === 'trap' ? 'TRAP TRIGGER' : 'MASTER TACTIC' }}</span><strong>{{ activeEvent.label }}</strong></div>
        <div v-if="enemyTactics?.armed_trap" class="trap-indicator enemy-trap">敌方已布置隐藏陷阱</div>
        <div v-if="myTactics?.armed_trap" class="trap-indicator ally-trap">己方陷阱待触发</div>
        <div class="side-caption enemy-caption"><span>{{ spectating ? 'PLAYER B' : 'ENEMY PARTY' }}</span><small>{{ payload.opponent_id }}</small></div>
        <div class="unit-row enemy-row">
          <article v-for="member in enemyTeam" :key="member.slot" :class="['board-unit', 'enemy-unit', unitEventClass(payload.opponent_id, member.slot), { 'active-actor': activeActor?.player_id === payload.opponent_id && activeActor?.servant_slot === member.slot, defeated: member.hp <= 0, 'target-candidate': targetMode?.side === 'enemy' && member.hp > 0, targeted: targetCount('enemy', member.slot) > 0 }]" @click="pickTarget('enemy', member.slot)">
            <div class="unit-overline"><span>{{ '★'.repeat(servant(member).rarity) }} · {{ servant(member).class }} · Lv.{{ member.level }}</span><b>{{ servant(member).name }}</b></div>
            <div class="unit-aura"></div><img v-if="servant(member).art_url" :src="assetUrl(servant(member).art_url!)" :alt="servant(member).name">
            <div v-if="floatingEvent(payload.opponent_id, member.slot)" class="floating-effect">{{ floatingEvent(payload.opponent_id, member.slot) }}</div>
            <div v-if="targetCount('enemy', member.slot)" class="target-count">×{{ targetCount('enemy', member.slot) }}</div>
            <div class="unit-plate"><span>ATK {{ member.attack }} · SPD {{ member.speed }}</span><div :class="['bar', 'hp', { low: hpPercent(member) <= 35, critical: hpPercent(member) <= 18 }]" :aria-label="`生命 ${member.hp} / ${member.max_hp}`"><i :style="{ width: hpPercent(member) + '%' }"></i><span>{{ member.hp }} / {{ member.max_hp }}</span></div><small>HP {{ hpPercent(member) }}% · NP{{ member.np_level }} · ★ {{ member.stars }} · <strong class="crit-readout enemy-crit">CRIT {{ critChance(member) }}% ×1.75</strong></small><div class="passive-line" :title="passiveSummary(servant(member))">被动 · {{ servant(member).passives.map(item => item.name).join(' / ') }}</div></div>
            <div class="status-dock enemy-status" aria-label="敌方状态">
              <div class="status-rail buff-rail"><em v-for="(effect, index) in member.buffs" :key="'b' + index + effect.kind" class="buff" :title="effectDescription(effect)">{{ effectLabel(effect) }}</em><small v-if="!member.buffs.length">无增益</small></div>
              <div class="status-rail debuff-rail"><em v-for="(effect, index) in member.debuffs" :key="'d' + index + effect.kind" class="debuff" :title="effectDescription(effect)">{{ effectLabel(effect, true) }}</em><small v-if="!member.debuffs.length">无减益</small></div>
            </div>
          </article>
        </div>
        <div class="versus-seal">VS</div>
        <div class="unit-row ally-row">
          <article v-for="member in myTeam" :key="member.slot" :class="['board-unit', 'ally-unit', unitEventClass(payload.player_id, member.slot), { selected: selectedMember?.slot === member.slot, 'active-actor': activeActor?.player_id === payload.player_id && activeActor?.servant_slot === member.slot, defeated: member.hp <= 0, stunned: isStunned(member), 'target-candidate': targetMode?.side === 'ally' && member.hp > 0, targeted: targetCount('ally', member.slot) > 0 }]" @click="handleAllyClick(member)">
            <div class="unit-overline"><span>{{ '★'.repeat(servant(member).rarity) }} · {{ servant(member).class }} · Lv.{{ member.level }}</span><b>{{ servant(member).name }}</b></div>
            <div class="unit-aura"></div><img v-if="servant(member).art_url" :src="assetUrl(servant(member).art_url!)" :alt="servant(member).name">
            <div v-if="floatingEvent(payload.player_id, member.slot)" class="floating-effect">{{ floatingEvent(payload.player_id, member.slot) }}</div>
            <div v-if="targetCount('ally', member.slot)" class="target-count ally-target">×{{ targetCount('ally', member.slot) }}</div>
            <div class="unit-plate"><span>ATK {{ member.attack }} · SPD {{ member.speed }}</span><div :class="['bar', 'hp', { low: hpPercent(member) <= 35, critical: hpPercent(member) <= 18 }]" :aria-label="`生命 ${member.hp} / ${member.max_hp}`"><i :style="{ width: hpPercent(member) + '%' }"></i><span>{{ member.hp }} / {{ member.max_hp }}</span></div><div class="bar np"><i :style="{ width: member.np + '%' }"></i></div><small>HP {{ hpPercent(member) }}% · NP {{ member.np }}% / NP{{ member.np_level }} · ★ {{ member.stars }} · <strong class="crit-readout">CRIT {{ critChance(member) }}% ×1.75</strong></small><div class="passive-line" :title="passiveSummary(servant(member))">被动 · {{ servant(member).passives.map(item => item.name).join(' / ') }}</div></div>
            <div class="status-dock ally-status" aria-label="己方状态">
              <div class="status-rail buff-rail"><em v-for="(effect, index) in member.buffs" :key="'b' + index + effect.kind" class="buff" :title="effectDescription(effect)">{{ effectLabel(effect) }}</em><small v-if="!member.buffs.length">无增益</small></div>
              <div class="status-rail debuff-rail"><em v-for="(effect, index) in member.debuffs" :key="'d' + index + effect.kind" class="debuff" :title="effectDescription(effect)">{{ effectLabel(effect, true) }}</em><small v-if="!member.debuffs.length">无减益</small></div>
            </div>
          </article>
        </div>
        <div class="side-caption ally-caption"><span>{{ spectating ? 'PLAYER A' : 'YOUR PARTY' }}</span><small>{{ payload.player_id }}</small></div>
      </section>

      <section v-if="latestTurnLog.length > 1" class="round-feedback glass-panel">
        <strong>{{ latestTurnLog[0] }}</strong><span v-for="line in latestTurnLog.slice(1, 7)" :key="line">{{ line }}</span>
      </section>

      <section v-if="!spectating && state.status === 'active' && selectedMember" class="turn-console command-dock glass-panel">
        <div class="selected-command">
          <span class="eyebrow">TACTICAL ORDER · {{ servant(selectedMember).class }}</span>
          <h2>{{ servant(selectedMember).name }}</h2>
          <p>{{ usedSkillSlots.has(selectedMember.slot) ? '本次行动技能已释放；' : '' }}{{ actionDetail(selectedMember) }}</p>
        </div>
        <div class="command-controls">
          <div class="skill-actions" aria-label="技能">
            <button v-for="(skill, index) in servant(selectedMember).skills" :key="skill.name" class="skill-button has-art dock-skill" :class="{ selected: pendingSkill?.servant_slot === selectedMember.slot && pendingSkill?.skill_index === index }" :style="skillStyle(servant(selectedMember), index)" :disabled="!canAct || selectedMember.hp <= 0 || isStunned(selectedMember) || selectedMember.cooldowns[index] > 0 || usedSkillSlots.has(selectedMember.slot) || waiting" :title="skill.name + '：' + skillSummary(skill)" @click="chooseSkill(selectedMember.slot, index)"><span>{{ index + 1 }}</span><small v-if="selectedMember.cooldowns[index]">{{ selectedMember.cooldowns[index] }}</small></button>
          </div>
          <div class="basic-actions">
            <button class="tactic-choice" :class="{ selected: tacticalOpen, used: myTactics?.used_this_phase }" :disabled="!canAct || waiting" @click="tacticalOpen = true">战术</button>
            <button class="attack-choice" :class="{ selected: commands[selectedMember.slot]?.kind === 'attack' }" :disabled="!canAct || selectedMember.hp <= 0 || isStunned(selectedMember) || waiting" @click="chooseAttack(selectedMember.slot)">攻击</button>
            <button class="np-button" :class="{ ready: selectedMember.np >= 100, selected: commands[selectedMember.slot]?.kind === 'np' }" :disabled="!canAct || selectedMember.hp <= 0 || isStunned(selectedMember) || selectedMember.np < 100 || waiting" @click="chooseNp(selectedMember.slot)">宝具</button>
          </div>
        </div>
        <div class="phase-copy"><p v-if="error" class="inline-error">{{ error }}</p><p v-else-if="targetMode" class="target-copy">{{ targetMode.prompt }}，点击发光单位。<button @click="targetMode = null">取消</button></p><p v-else-if="!canAct" class="waiting-copy">当前英灵正在行动，页面会自动同步结果。</p><p v-else-if="isStunned(selectedMember)">该英灵处于眩晕，确认后跳过本次行动。</p><p v-else>可使用 1 次战术与 1 个角色技能；再以攻击或宝具结束行动。</p></div>
        <button class="attack-button" :disabled="!canSubmit" @click="submitAction"><span>{{ waiting ? 'RESOLVING' : 'EXECUTE' }}</span><small>{{ waiting ? '正在结算' : (isStunned(selectedMember) ? '跳过本次行动' : '确认该英灵行动') }}</small></button>
      </section>

      <section :class="['comment-panel', 'glass-panel', { 'player-comments': !spectating && state.status === 'active' }]">
        <header><div><span class="eyebrow">LIVE SPECTATOR CHANNEL</span><h2>{{ spectating ? '观战弹幕' : '战场通讯' }}</h2></div><button class="comment-toggle" @click="danmakuEnabled = !danmakuEnabled">{{ danmakuEnabled ? '隐藏飘屏' : '显示飘屏' }}</button></header>
        <div class="comment-history" aria-label="最近弹幕"><p v-if="!comments.length">还没有弹幕，来发第一条吧。</p><p v-for="item in comments.slice(-12)" :key="item.id"><b>{{ commentAuthor(item) }}</b><span>{{ item.content }}</span></p></div>
        <form class="comment-form" @submit.prevent="sendComment"><input v-model="commentText" maxlength="60" autocomplete="off" placeholder="发送弹幕（最多 60 字）"><button :disabled="commentSending || !commentText.trim()">{{ commentSending ? '发送中' : '发送' }}</button></form>
        <small v-if="commentError" class="comment-error">{{ commentError }}</small><small v-else>每人每 2 秒最多一条；弹幕仅在本场对局内显示。</small>
      </section>

      <div v-if="pendingSkillData" class="skill-confirm-backdrop" @click.self="pendingSkill = null">
        <section class="skill-confirm glass-panel" role="dialog" aria-modal="true" aria-labelledby="skill-confirm-title">
          <div class="skill-confirm-icon skill-button has-art" :style="skillStyle(pendingSkillData.servant, pendingSkill!.skill_index)"></div>
          <div class="skill-confirm-copy"><span class="eyebrow">SKILL CONFIRMATION</span><h2 id="skill-confirm-title">{{ pendingSkillData.skill.name }}</h2><p>{{ pendingSkillData.skill.description }}</p><ul><li v-for="(effect, index) in pendingSkillData.skill.effects" :key="index">{{ effectDescription(effect) }}</li></ul><small>冷却 {{ pendingSkillData.skill.cooldown }} 回合 · 确认后立即结算</small></div>
          <div class="skill-confirm-actions"><button class="skill-cancel" :disabled="waiting" @click="pendingSkill = null">取消</button><button class="skill-release" :disabled="waiting" @click="confirmSkill">{{ waiting ? '释放中…' : '确认释放' }}</button></div>
        </section>
      </div>
      <div v-if="tacticalOpen && myTactics" class="tactic-backdrop" @click.self="tacticalOpen = false">
        <section class="tactic-drawer glass-panel" role="dialog" aria-modal="true" aria-labelledby="tactic-title">
          <header><div><span class="eyebrow">MASTER & ARCANE DECK</span><h2 id="tactic-title">御主战术终端</h2></div><button @click="tacticalOpen = false">关闭</button></header>
          <p class="tactic-rule"><b>{{ masterTemplate?.name ?? '迦勒底标准礼装' }}</b> · {{ masterTemplate?.description }}<br>每名从者的行动阶段至多发动一项战术。御主技能每场一次；随机魔术与随机陷阱每轮刷新且不会连续重复；陷阱共两次且名称对敌方隐藏。</p>
          <div class="tactic-section"><h3>御主技能</h3><div class="tactic-grid"><button v-for="item in masterSkills" :key="item.id" :disabled="waiting || myTactics.used_this_phase || !myTactics.master_available?.[item.id]" @click="submitTactic('master', item.id)"><b>{{ item.name }}</b><span>{{ item.description }}</span><small>{{ myTactics.master_available?.[item.id] ? 'READY' : 'USED' }}</small></button></div></div>
          <div class="tactic-section"><h3>本轮随机魔术</h3><div class="tactic-grid single"><button v-if="randomMagic" :disabled="waiting || myTactics.used_this_phase || myTactics.magic_used" @click="submitTactic('magic', randomMagic.id)"><b>{{ randomMagic.name }}</b><span>{{ randomMagic.description }}</span><small>{{ myTactics.magic_used ? 'USED' : `ROUND ${myTactics.magic_round}` }}</small></button></div></div>
          <div class="tactic-section"><h3>本轮随机陷阱 · 剩余 {{ myTactics.trap_charges }}</h3><div class="tactic-grid single"><button v-if="randomTrap" :disabled="waiting || myTactics.used_this_phase || myTactics.trap_charges <= 0 || Boolean(myTactics.armed_trap)" @click="submitTactic('trap', randomTrap.id)"><b>{{ randomTrap.name }}</b><span>{{ randomTrap.description }}</span><small>{{ myTactics.armed_trap === randomTrap.id ? 'ARMED' : `ROUND ${myTactics.trap_round}` }}</small></button></div></div>
          <div class="passive-panel"><h3>{{ servant(selectedMember).name }} · 被动技能</h3><article v-for="passive in servant(selectedMember).passives" :key="passive.name"><b>{{ passive.name }}</b><span>{{ passive.description }}</span></article></div>
        </section>
      </div>
      <section v-if="state.status !== 'active'" class="result-panel glass-panel"><span class="eyebrow">BATTLE FINISHED</span><h2>{{ spectating ? (state.winner_id ? `胜者 · ${state.winner_id}` : '平局') : (state.winner_id === payload.player_id ? '演算胜利' : state.winner_id ? '演算败北' : '平局') }}</h2><p>战斗结果已经写入服务器记录。</p></section>
      <aside class="battle-log glass-panel"><span class="eyebrow">COMBAT LOG</span><p v-for="(line, index) in recentLog" :key="index">{{ line }}</p></aside>
    </template>
  </main>
</template>
