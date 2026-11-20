import {
  Landmark,
  Layers3,
  Package,
  PawPrint,
  Sparkles,
  Users,
  type LucideIcon,
} from "lucide-react"

import type { AssetMediaVersion, AssetPayload, MediaAsset } from "@/backend"
import type { AssetTab } from "@/navigation"

export type AssetItem = {
  id: string
  name: string
  desc: string
  lifecycleStatus?: "active" | "offline"
  lifecycle_status?: "active" | "offline"
  offlineAt?: string
  offline_at?: string
  lifecycleChangedAt?: string
  lifecycle_changed_at?: string
  tag?: string
  accent?: string
  canSpeak?: boolean
  voiceStyle?: string
  hideTurnaroundHeads?: boolean
  stateTag?: string
  stateTags?: string[]
  usage?: string
  version?: string
  media?: MediaAsset | null
  referenceMedia?: MediaAsset | null
  referenceMediaRole?: "original" | "reference" | null
  voiceReferenceAudio?: MediaAsset | null
  mediaVersions?: AssetMediaVersion[]
  activeMediaVersionId?: string | null
  aliases?: string[]
  assetRangeId?: string
  firstEpisodeId?: string
  sourceRange?: {
    sourceId?: string
    absoluteStart?: number
    absoluteEnd?: number
  }
  sourceRangeLabel?: string
  sourceRangeSummary?: string
  sourceRefs?: Array<Record<string, unknown>>
  visualSpec?: Record<string, unknown>
  continuity?: Record<string, unknown>
  prompts?: Record<string, unknown>
  generation?: Record<string, unknown>
}

export type AssetDialogMode =
  | "create"
  | "library"
  | "bulk"
  | "generate-all"
  | "detail"
  | "copy"
  | null

export type AssetEditPatch = Pick<
  AssetItem,
  "name" | "desc" | "tag" | "canSpeak" | "voiceStyle"
> & {
  lifecycleStatus?: "active" | "offline"
  prompts?: Record<string, unknown>
  hideTurnaroundHeads?: boolean
  media?: MediaAsset | null
  referenceMedia?: MediaAsset | null
  voiceReferenceAudio?: MediaAsset | null
  overwrite?: boolean
}

export const ASSET_NAME_DUPLICATE_MESSAGE = "名称已重复，不能修改"

export class AssetLibraryDuplicateError extends Error {
  asset: AssetItem

  constructor(asset: AssetItem) {
    super("__asset_library_duplicate__")
    this.name = "AssetLibraryDuplicateError"
    this.asset = asset
  }
}

export class AssetLibraryMissingMediaError extends Error {
  constructor(message: string) {
    super(message)
    this.name = "AssetLibraryMissingMediaError"
  }
}

export function isAssetLibraryDuplicateError(
  error: unknown
): error is AssetLibraryDuplicateError {
  return error instanceof AssetLibraryDuplicateError
}

export function isAssetLibraryMissingMediaError(
  error: unknown
): error is AssetLibraryMissingMediaError {
  return error instanceof AssetLibraryMissingMediaError
}

export const assetTabs: Array<{
  id: AssetTab
  label: string
  icon: LucideIcon
}> = [
  { id: "characters", label: "人物", icon: Users },
  { id: "creatures", label: "生物", icon: PawPrint },
  { id: "scenes", label: "场景", icon: Layers3 },
  { id: "props", label: "道具", icon: Package },
  { id: "styles", label: "收藏风格", icon: Sparkles },
]

export function getAssetMeta(tab: AssetTab): {
  title: string
  projectTitle: string
  noun: string
  icon: LucideIcon
  addLabel: string
  emptyHint: string
} {
  if (tab === "characters") {
    return {
      title: "角色集",
      projectTitle: "角色",
      noun: "角色",
      icon: Users,
      addLabel: "新建角色",
      emptyHint: "还没有角色资产，先创建角色或从全局资产导入。",
    }
  }
  if (tab === "scenes") {
    return {
      title: "场景库",
      projectTitle: "场景",
      noun: "场景",
      icon: Landmark,
      addLabel: "新建场景",
      emptyHint: "还没有场景资产，先创建故事发生地点。",
    }
  }
  if (tab === "creatures") {
    return {
      title: "生物库",
      projectTitle: "生物",
      noun: "生物",
      icon: PawPrint,
      addLabel: "新建生物",
      emptyHint: "还没有生物资产，先创建妖兽、灵兽或非人形活体。",
    }
  }
  if (tab === "props") {
    return {
      title: "道具库",
      projectTitle: "道具",
      noun: "道具",
      icon: Package,
      addLabel: "新建道具",
      emptyHint: "还没有道具资产，先创建关键线索或视觉锚点。",
    }
  }
  return {
    title: "收藏风格",
    projectTitle: "收藏风格",
    noun: "风格",
    icon: Sparkles,
    addLabel: "新建收藏风格",
    emptyHint: "还没有收藏风格，可在项目设置中上传风格图片和提示词后收藏。",
  }
}

export function assetVoiceStyleValue(
  tab: AssetTab,
  source: Pick<AssetItem, "voiceStyle" | "canSpeak">,
  patch: Partial<Pick<AssetEditPatch, "voiceStyle" | "canSpeak">> = {}
) {
  if (tab === "characters" || tab === "creatures") {
    return (patch.voiceStyle ?? source.voiceStyle ?? "").trim()
  }
  return undefined
}

export function normalizeAssetNameKey(value: string | null | undefined) {
  return String(value ?? "")
    .trim()
    .toLocaleLowerCase()
}

export function buildGlobalAssetPayload(
  tab: AssetTab,
  source: AssetItem,
  patch: Partial<AssetEditPatch> = {}
): AssetPayload {
  const voiceStyle = assetVoiceStyleValue(tab, source, patch)
  return {
    name: (patch.name ?? source.name).trim() || source.name,
    desc: (patch.desc ?? source.desc ?? "").trim(),
    canSpeak: tab === "creatures" ? Boolean(voiceStyle) : undefined,
    voiceStyle,
    prompts: patch.prompts ?? source.prompts,
    media: patch.media !== undefined ? patch.media : (source.media ?? null),
    referenceMedia: null,
    voiceReferenceAudio:
      tab === "characters" || tab === "creatures"
        ? patch.voiceReferenceAudio !== undefined
          ? patch.voiceReferenceAudio
          : source.voiceReferenceAudio ?? undefined
        : undefined,
  }
}

export function buildProjectAssetPayloadFromLibrary(
  tab: AssetTab,
  source: AssetItem,
  patch: Partial<AssetEditPatch> = {}
): AssetPayload {
  const voiceStyle = assetVoiceStyleValue(tab, source, patch)
  return {
    name: (patch.name ?? source.name).trim() || source.name,
    desc: (patch.desc ?? source.desc ?? "").trim(),
    tag: (patch.tag ?? source.tag ?? "").trim() || undefined,
    canSpeak: tab === "creatures" ? Boolean(voiceStyle) : undefined,
    voiceStyle,
    prompts: patch.prompts ?? source.prompts,
    media: patch.media !== undefined ? patch.media : (source.media ?? null),
    referenceMedia: null,
    voiceReferenceAudio:
      tab === "characters" || tab === "creatures"
        ? patch.voiceReferenceAudio !== undefined
          ? patch.voiceReferenceAudio
          : source.voiceReferenceAudio ?? undefined
        : undefined,
    overwrite: patch.overwrite,
  }
}
