import type { MediaAsset } from "@/backend"
import { mediaPreviewSrc } from "@/shared/media"
import type { InlineAssetTag } from "./inline-asset-tags"

export type PreviewSelection = { side: "input" | "output"; key: string }
type PreviewMedia = { key: string; label: string; kind: "image" | "video"; media: MediaAsset | null; src: string }

export function selectWorkflowPreview(
  director: boolean,
  inputs: InlineAssetTag[],
  outputs: PreviewMedia[],
  selection: PreviewSelection | null,
): { side: PreviewSelection["side"]; item: PreviewMedia } | undefined {
  const availableInputs = inputs.flatMap((tag) => {
    const src = mediaPreviewSrc(tag.media, tag.previewSrc) || ""
    // Project-relative files receive their URL when the selected media resolves.
    const relativePath = tag.media?.relativePath || tag.media?.relative_path || tag.media?.file
    if (!src.trim() && !relativePath?.trim()) return []
    const item: PreviewMedia = {
      key: tag.key, label: tag.label, kind: tag.kind === "video" ? "video" : "image",
      media: tag.media ?? null, src,
    }
    return [{ tag, item }]
  })
  const availableOutputs = outputs.filter((item) => Boolean(item.src.trim()))
  const selectedInput = selection?.side === "input"
    ? availableInputs.find(({ item }) => item.key === selection.key)?.item : undefined
  const selectedOutput = selection?.side === "output"
    ? availableOutputs.find((item) => item.key === selection.key) : undefined
  if (selectedInput) return { side: "input", item: selectedInput }
  if (selectedOutput) return { side: "output", item: selectedOutput }

  const input = (availableInputs.find(({ tag }) => tag.kind === "storyboard") ?? availableInputs[0])?.item
  const output = availableOutputs[0]
  if (director && output) return { side: "output", item: output }
  if (input) return { side: "input", item: input }
  if (output) return { side: "output", item: output }
  return undefined
}
