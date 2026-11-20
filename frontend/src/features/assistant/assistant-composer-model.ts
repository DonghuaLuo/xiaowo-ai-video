import { type InputImageFile } from "@/backend"
import { localImageFileFromFile } from "@/shared/image-picker"
import { inferImageMimeFromPath } from "@/shared/media"
import {
  ASSISTANT_STATIC_IMAGE_MIME_TYPES,
  AssistantQuickPrompt,
  AssistantSkillCommand,
  isAssistantTruthyFlag,
} from "./assistant-session-normalization"

export const ASSISTANT_TEXTAREA_MAX_HEIGHT_VH = 50

export const ASSISTANT_MAX_ATTACHMENTS = 5

export function isAssistantStaticImageFile(file: File) {
  const mimeType = String(file.type || "").toLowerCase()
  if (ASSISTANT_STATIC_IMAGE_MIME_TYPES.has(mimeType)) return true
  return /\.(png|jpe?g|webp)$/i.test(file.name || "")
}

export function readAssistantImageDataUrl(file: File) {
  return new Promise<string>((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => resolve(String(reader.result || ""))
    reader.onerror = () => reject(reader.error ?? new Error("读取图片失败"))
    reader.readAsDataURL(file)
  })
}

export async function inputImageFileFromBrowserFile(
  file: File
): Promise<InputImageFile | null> {
  if (!isAssistantStaticImageFile(file)) return null
  const localFile = localImageFileFromFile(file)
  if (localFile) return localFile
  const dataUrl = await readAssistantImageDataUrl(file)
  if (!dataUrl.startsWith("data:image/")) return null
  return {
    name: file.name || "image.png",
    mimeType: file.type || inferImageMimeFromPath(file.name),
    size: file.size,
    dataUrl,
  }
}

export function normalizeAssistantSkillCommand(
  raw: unknown,
  fallbackSource: AssistantSkillCommand["source"]
): AssistantSkillCommand | null {
  if (!raw || typeof raw !== "object") return null
  const row = raw as Record<string, unknown>
  const id = String(row.id || row.name || "").trim()
  const name = String(row.name || id).trim()
  const label = String(row.label || name || id).trim()
  const prompt = String(row.prompt || label || name).trim()
  const execution = String(row.execution || "").trim()
  const rawControlOnly = row.controlOnly ?? row.control_only
  if (!id || !label || !prompt) return null
  return {
    id,
    name,
    label,
    description: String(row.description || "").trim(),
    prompt,
    source: String(row.source || fallbackSource).trim() || fallbackSource,
    ...(execution ? { execution } : {}),
    ...(isAssistantTruthyFlag(rawControlOnly) ? { controlOnly: true } : {}),
  }
}

export function normalizeAssistantQuickPromptSlashCommand(
  raw: unknown,
  index: number
): AssistantSkillCommand | null {
  if (!raw || typeof raw !== "object") return null
  const row = raw as Record<string, unknown>
  const label = String(row.label || "").trim()
  const prompt = String(row.prompt || row.message || "").trim()
  if (!label || !prompt) return null
  const id = String(row.id || row.name || "").trim() || `quick_prompt_${index}`
  const taskType = String(row.taskType || row.task_type || "").trim()
  const rawControlOnly = row.controlOnly ?? row.control_only
  return {
    id,
    name: id,
    label,
    description: prompt === label ? "填入输入框，发送前可继续编辑" : prompt,
    prompt,
    ...(taskType ? { taskType } : {}),
    ...(isAssistantTruthyFlag(rawControlOnly) ? { controlOnly: true } : {}),
    source: "quick_prompt",
  }
}

export function normalizeAssistantTaskTypes(raw: unknown): Set<string> {
  if (!raw || typeof raw !== "object") return new Set()
  const row = raw as Record<string, unknown>
  const catalog = Array.isArray(row.taskCatalog)
    ? row.taskCatalog
    : Array.isArray(row.task_catalog)
      ? row.task_catalog
      : []
  return new Set(
    catalog
      .map((item) => {
        if (!item || typeof item !== "object") return ""
        const task = item as Record<string, unknown>
        return String(task.taskType || task.task_type || "").trim()
      })
      .filter(Boolean)
  )
}

export function normalizeAssistantQuickPrompts(raw: unknown): AssistantQuickPrompt[] {
  if (!raw || typeof raw !== "object") return []
  const row = raw as Record<string, unknown>
  const prompts = Array.isArray(row.quickPrompts)
    ? row.quickPrompts
    : Array.isArray(row.quick_prompts)
      ? row.quick_prompts
      : []
  return prompts
    .map((item, index) => {
      if (!item || typeof item !== "object") return null
      const prompt = item as Record<string, unknown>
      const label = String(prompt.label || "").trim()
      const message = String(prompt.prompt || prompt.message || "").trim()
      if (!label || !message) return null
      const id = String(prompt.id || prompt.name || "").trim() || `quick_prompt_${index}`
      const taskType = String(prompt.taskType || prompt.task_type || "").trim()
      const rawControlOnly = prompt.controlOnly ?? prompt.control_only
      return {
        id,
        label,
        prompt: message,
        ...(taskType ? { taskType } : {}),
        ...(isAssistantTruthyFlag(rawControlOnly) ? { controlOnly: true } : {}),
      }
    })
    .filter((item): item is AssistantQuickPrompt => Boolean(item))
}

export function normalizeAssistantSkillCommands(raw: unknown): AssistantSkillCommand[] {
  if (!raw || typeof raw !== "object") return []
  const row = raw as Record<string, unknown>
  const commands = Array.isArray(row.commands) ? row.commands : []
  const quickPrompts = Array.isArray(row.quickPrompts)
    ? row.quickPrompts
    : Array.isArray(row.quick_prompts)
      ? row.quick_prompts
      : []
  const normalized = [
    ...quickPrompts
      .map((item, index) => normalizeAssistantQuickPromptSlashCommand(item, index))
      .filter(Boolean),
    ...commands
      .map((item) => normalizeAssistantSkillCommand(item, "agent_action"))
      .filter(Boolean),
  ] as AssistantSkillCommand[]
  const seen = new Set<string>()
  return normalized.filter((command) => {
    const key = `${command.source || ""}:${command.id}`
    if (seen.has(key)) return false
    seen.add(key)
    return true
  })
}

export function assistantSlashCommandMatches(
  command: AssistantSkillCommand,
  query: string
) {
  if (!query) return true
  const haystack = [
    command.id,
    command.name,
    command.label,
    command.description,
    command.prompt,
  ]
    .join(" ")
    .toLowerCase()
  return haystack.includes(query)
}
