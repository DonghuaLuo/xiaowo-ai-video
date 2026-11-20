import type {
  AssetStylePrompts,
  StyleTemplateOption,
} from "@/features/styles/types"

export const GENERAL_STYLE_TEMPLATE_ID = "general_universal_high_art"
export const GENERAL_STYLE_CATEGORY = "general"

const presetThemeVisualPrefixRe =
  /^[^，,。；;]*(?:时代背景|时代设定|世界观背景)[，,]\s*/
const presetThemeVisualTailRe =
  /[，,。；;]?\s*(?:整体时代设定保持|整体世界观保持)[^，,。；;]*语境[。；;，,]?\s*/g

function stripPresetThemeVisualText(
  prompt: string,
  template?: StyleTemplateOption | null
) {
  if (
    !template ||
    isGeneralStyleTemplate(template) ||
    template.category === "favorite"
  ) {
    return prompt
  }
  return prompt
    .replace(presetThemeVisualPrefixRe, "")
    .replace(presetThemeVisualTailRe, "，")
    .replace(/^[\s，,；;。]+/, "")
    .replace(/[\s，,；;。]+$/g, "")
    .trim()
}

export const GENERAL_GLOBAL_STYLE_PROMPT = ""

export const GENERAL_CHARACTER_STYLE_PROMPT = ""

export const GENERAL_CREATURE_STYLE_PROMPT = ""

export type GeneralStylePromptKind =
  | "global"
  | "character"
  | "creature"

export function isGeneralStyleTemplate(
  template?: StyleTemplateOption | null
): boolean {
  return (
    template?.id === GENERAL_STYLE_TEMPLATE_ID ||
    template?.category === GENERAL_STYLE_CATEGORY
  )
}

export function styleTemplateVisualTypeTags(
  template?: StyleTemplateOption | null
) {
  const tags = template?.visualTypeTags ?? template?.visual_type_tags
  return Array.isArray(tags) ? tags : []
}

export function defaultVisualTypeTag(template?: StyleTemplateOption | null) {
  const tags = styleTemplateVisualTypeTags(template)
  const preferred =
    template?.defaultVisualTypeTag ?? template?.default_visual_type_tag
  return tags.includes(preferred ?? "") ? preferred ?? "" : tags[0] ?? ""
}

export function normalizeVisualTypeTag(
  value: string | null | undefined,
  template?: StyleTemplateOption | null
) {
  const tags = styleTemplateVisualTypeTags(template)
  const text = value?.trim() ?? ""
  return tags.includes(text) ? text : defaultVisualTypeTag(template)
}

export function styleTagPrefix(visualTypeTag: string) {
  const visualTypeText = visualTypeTag.trim()
  return visualTypeText ? `画面类型：${visualTypeText}。` : ""
}

function stripKnownStyleTagPrefix(prompt: string) {
  let text = prompt.trim()
  const labeledPrefix = text.match(/^画面类型[:：]([^。]*)(?:。|$)\s*/)
  if (labeledPrefix && !labeledPrefix[1]?.includes("统一美术风格")) {
    return text
      .slice(labeledPrefix[0].length)
      .replace(/^[\s，,；;。]+/, "")
      .trimStart()
  }
  return text
}

export function withStyleTagPrefix(
  prompt: string,
  visualTypeTag: string
) {
  const text = stripKnownStyleTagPrefix(prompt)
  const prefix = styleTagPrefix(visualTypeTag)
  if (!prefix) return text
  if (!text) return prefix
  return text.startsWith(prefix) || text === prefix ? text : `${prefix}${text}`
}

function templateVisualTypeStylePrompts(
  template?: StyleTemplateOption | null
) {
  const prompts =
    template?.visualTypeStylePrompts ?? template?.visual_type_style_prompts
  return prompts && typeof prompts === "object" && !Array.isArray(prompts)
    ? prompts
    : null
}

function readStylePromptField(
  fields: AssetStylePrompts | null | undefined,
  kind: GeneralStylePromptKind
) {
  if (!fields) return ""
  const value =
    kind === "character"
      ? fields.characterAssetPrompt ?? fields.character_asset_prompt
      : kind === "creature"
        ? fields.creatureAssetPrompt ?? fields.creature_asset_prompt
        : fields.assetPrompt ?? fields.asset_prompt
  return (value ?? "").trim()
}

function templateVisualTypeStylePrompt(
  template: StyleTemplateOption | null | undefined,
  kind: GeneralStylePromptKind,
  visualTypeTag: string
) {
  const promptMap = templateVisualTypeStylePrompts(template)
  if (!promptMap) return ""
  return readStylePromptField(promptMap[visualTypeTag], kind)
}

export function styleTemplatePrompt(
  template: StyleTemplateOption | null | undefined,
  kind: GeneralStylePromptKind,
  visualTypeTag: string
) {
  if (!template) return ""
  const base =
    kind === "character"
      ? template.characterAssetPrompt ?? template.character_asset_prompt ?? ""
      : kind === "creature"
        ? template.creatureAssetPrompt ?? template.creature_asset_prompt ?? ""
        : template.assetPrompt ?? template.asset_prompt ?? template.prompt ?? ""
  const normalizedBase = stripPresetThemeVisualText(base, template)
  if (!isGeneralStyleTemplate(template)) return normalizedBase
  const normalizedTag = normalizeVisualTypeTag(visualTypeTag, template)
  return (
    templateVisualTypeStylePrompt(template, kind, normalizedTag) ||
    withStyleTagPrefix(normalizedBase, normalizedTag)
  )
}
