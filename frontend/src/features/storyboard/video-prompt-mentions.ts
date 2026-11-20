import { inlineAssetTagReferenceMatches, type InlineAssetTag } from "./inline-asset-tags"

export type PromptBindings = Record<string, string>
export type PromptMentionOption = {
  key: string
  label: string
  kind: InlineAssetTag["kind"] | "image"
  assetId: string
  title: string
  previewSrc?: string
}

export const PROMPT_MENTION_PATTERN = /@\[([^\[\]\r\n]+)\]/g
const PROMPT_REFERENCE_PATTERN = /@\[([^\[\]\r\n]+)\]|(?<!<)<([^<>\r\n]+)>(?!>)|[@＠]?参考视频[ \t]*([0-9]+)/g

function referenceLabel(editorLabel: string | undefined, canonicalLabel: string | undefined, number: string | undefined): string {
  return editorLabel ?? canonicalLabel ?? `参考视频${number!.replace(/^0+(?=\d)/, "")}`
}

export function promptMentionOptions(manifest: Record<string, any>[], tags: InlineAssetTag[]): PromptMentionOption[] {
  const seen = new Set<string>()
  return manifest.flatMap((row) => {
    if (!row.mentionKey || !row.mentionLabel || seen.has(row.mentionKey)) return []
    seen.add(row.mentionKey)
    const tag = tags.find((item) => inlineAssetTagReferenceMatches(item, row))
    return [{
      key: row.mentionKey,
      label: row.mentionLabel,
      kind: row.mentionKind,
      assetId: row.assetId || "",
      title: `${row.referenceLabel || row.mentionLabel}：${["storyboard", "handoff", "frame"].includes(row.mentionKind) ? row.mentionLabel : row.displayName || row.mentionLabel}`,
      previewSrc: tag?.previewSrc,
    }]
  })
}

export function bindPromptMentions(text: string, bindings: PromptBindings, options: PromptMentionOption[], additionalTexts: string[] = []): PromptBindings {
  const available = new Map<string, string>()
  for (const option of options) {
    const previous = available.get(option.label)
    available.set(option.label, previous === undefined || previous === option.key ? option.key : "")
  }
  const videos = new Map(options.filter((option) => option.kind === "video").map((option) => [option.label, option.key]))
  return Object.fromEntries([text, ...additionalTexts].flatMap((fieldText) => [...fieldText.matchAll(PROMPT_REFERENCE_PATTERN)]).flatMap((match) => {
    const label = referenceLabel(match[1], match[2], match[3])
    const key = bindings[label] || (match[3] === undefined ? available : videos).get(label) || ""
    // An unknown <name> is ordinary prompt prose; keep an existing bound identity.
    return match[2] !== undefined && !key ? [] : [[label, key] as const]
  }))
}

export function rebasePromptMentions(text: string, bindings: PromptBindings, options: PromptMentionOption[], additionalTexts: string[] = []) {
  const namedReferences = new Map<string, string>()
  for (const option of options) {
    const previous = namedReferences.get(option.label)
    namedReferences.set(option.label, previous === undefined || previous === option.key ? option.key : "")
  }
  // The stored prompt uses <name>; only the editable view uses @[name].
  text = text.replace(/@\[[^\[\]\r\n]+\]|(?<!<)<([^<>\r\n]+)>(?!>)/g, (token, name: string | undefined) =>
    name !== undefined && namedReferences.get(name) ? `@[${name}]` : token)
  bindings = { ...bindings }
  for (const match of text.matchAll(PROMPT_MENTION_PATTERN)) {
    const label = match[1]
    const key = namedReferences.get(label)
    if (key && !Object.prototype.hasOwnProperty.call(bindings, label)) bindings[label] = key
  }
  // Enabling/disabling references must not rewrite the story or video numbers.
  // Stable bindings resolve current provider indices only at submission time.
  return { text, promptBindings: bindPromptMentions(text, bindings, options, additionalTexts) }
}

export const PROMPT_MENTION_COLORS: Record<PromptMentionOption["kind"], string> = {
  custom_image: "text-zinc-700 bg-zinc-500/10 dark:text-zinc-300",
  character: "text-[#3730A3] bg-[#EEF2FF] dark:text-[#E0E7FF] dark:bg-[#4F46E5]/18",
  scene: "text-[#047857] bg-[#ECFDF5] dark:text-[#D1FAE5] dark:bg-[#10B981]/16",
  prop: "text-[#C2410C] bg-[#FFF7ED] dark:text-[#FFEDD5] dark:bg-[#F97316]/16",
  creature: "text-[#BE185D] bg-[#FDF2F8] dark:text-[#FCE7F3] dark:bg-[#EC4899]/16",
  storyboard: "text-[#1D4ED8] bg-[#EFF6FF] dark:text-[#DBEAFE] dark:bg-[#3B82F6]/18",
  handoff: "text-[#047857] bg-[#ECFDF5] dark:text-[#D1FAE5] dark:bg-[#10B981]/18",
  frame: "text-fuchsia-700 bg-fuchsia-500/10 dark:text-fuchsia-300",
  video: "text-violet-700 bg-violet-500/10 dark:text-violet-300",
  image: "text-zinc-700 bg-zinc-500/10 dark:text-zinc-300",
}

export const PROMPT_MENTION_TYPE_LABELS: Record<PromptMentionOption["kind"], string> = {
  custom_image: "自定义图片",
  character: "角色", scene: "场景", prop: "道具", creature: "生物",
  storyboard: "分镜图", handoff: "视觉交接图", frame: "帧画面",
  video: "参考视频", image: "参考图",
}
