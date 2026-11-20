import type { StyleTemplateOption } from "@/features/styles/types"

export function normalizeFavoriteStyleName(value: string | null | undefined) {
  return String(value ?? "").trim().replace(/\s+/g, " ").toLocaleLowerCase()
}

export function nextFavoriteStyleName(templates: StyleTemplateOption[]) {
  const existing = new Set(
    templates.map((template) => normalizeFavoriteStyleName(template.name))
  )
  let index = 1
  while (existing.has(normalizeFavoriteStyleName(`自定义风格${index}`))) {
    index += 1
  }
  return `自定义风格${index}`
}
