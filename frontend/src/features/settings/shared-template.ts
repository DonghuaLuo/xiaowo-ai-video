import type { ContentMode } from "@/features/projects/types"

export const contentModeOptions: Array<{
  id: ContentMode
  name: string
  description: string
}> = [
  {
    id: "drama",
    name: "故事版视频",
    description: "按分集原文创建剧情片段、分镜脚本、分镜和视频。",
  },
]

export function contentModeLabel(_mode: ContentMode) {
  return "故事版视频"
}

export const TEMPLATE_EDIT_ICON_BUTTON_CLS =
  "m-1 inline-flex size-8 shrink-0 items-center justify-center rounded-md text-gray-400 transition-colors hover:text-indigo-600 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500/40 dark:hover:text-indigo-300"

export function normalizeTemplateName(value: string): string {
  return value.replace(/\s+/g, " ").trim().toLocaleLowerCase()
}
