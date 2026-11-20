import { useEffect, useId, useRef, useState, type ReactNode } from "react"
import { ChevronDown } from "lucide-react"
import { Popover, PopoverContent, PopoverAnchor } from "@/components/ui/popover"
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group"
import { Switch } from "@/components/ui/switch"
import type { VideoVisualInputCapabilities } from "@/utils/video-model-capabilities"
import "./frame-reference-menu.css"

export type FrameRole = "first_frame" | "last_frame"
export type FrameReferenceOptions = { frameRole: FrameRole; useNativeFrame: boolean }
export type FrameReferenceRow = { kind: string; enabled?: boolean; mediaIdentity?: string; frameRole?: FrameRole; useNativeFrame?: boolean }

export function isFrameImage(row: Record<string, unknown>) {
  return ["assetType", "assetKind", "mediaPurpose", "preferredTargetSlot", "slot", "targetSlot"]
    .some((key) => row[key] === "frame_image" || row[key] === "frame_reference")
}

/** Storyboard video only uses modes that accept ordinary image references. */
export function frameTransportSelection(rows: FrameReferenceRow[], visual?: VideoVisualInputCapabilities, nativeRequired = false) {
  const roles = rows.filter((row) => row.enabled !== false && row.kind === "frame").map((row) => row.frameRole ?? "first_frame")
  if (new Set(roles).size !== roles.length) return { valid: false, native: new Set<number>() }
  const candidates = rows.flatMap((row, index) => row.enabled !== false && row.kind === "frame" && row.useNativeFrame !== false ? [index] : [])
  if (nativeRequired && (!roles.includes("first_frame") || candidates.length !== roles.length)) return { valid: false, native: new Set<number>() }
  // Keep original indices for thumbnail controls and validate frame conflicts
  // above using all associations, but count each submitted media input once.
  const inputKey = (row: FrameReferenceRow, index: number) => JSON.stringify([
    row.mediaIdentity || `row:${index}`,
    row.kind === "frame" ? row.frameRole ?? "first_frame" : "reference",
  ])
  const videoCount = new Set(rows.flatMap((row, index) =>
    row.enabled !== false && row.kind === "video" ? [inputKey(row, index)] : []
  )).size
  if (candidates.length > 2) return { valid: false, native: new Set<number>() }
  const subsets = nativeRequired ? [candidates] : Array.from({ length: 1 << candidates.length }, (_, mask) => candidates.filter((_, bit) => mask & (1 << bit)))
    .sort((a, b) => b.length - a.length)
  for (const subset of subsets) {
    const imageCount = new Set(rows.flatMap((row, index) =>
      row.enabled !== false && row.kind !== "video" && !subset.includes(index) ? [inputKey(row, index)] : []
    )).size
    const counts = { first_frame: 0, last_frame: 0, reference_image: imageCount, reference_video: videoCount }
    subset.forEach((index) => counts[rows[index].frameRole ?? "first_frame"]++)
    if (visual?.modes.some((mode) =>
      (!nativeRequired ? mode.max_counts.reference_image > 0 : true) &&
      Object.entries(counts).every(([role, count]) => count <= (mode.max_counts[role as keyof typeof counts] ?? 0)) &&
      mode.required_roles.every((role) => counts[role] > 0) &&
      counts.reference_image + counts.reference_video >= mode.min_reference_materials &&
      counts.reference_image + counts.reference_video <= mode.max_reference_materials
    )) return { valid: true, native: new Set(subset) }
  }
  return { valid: false, native: new Set<number>() }
}

export function supportsNativeFrame(role: FrameRole, visual?: VideoVisualInputCapabilities, nativeRequired = false) {
  const supported = role === "first_frame" ? visual?.supports_first_frame : visual?.supports_last_frame
  return Boolean(supported && visual?.modes.some((mode) => (nativeRequired || mode.max_counts.reference_image > 0) && mode.max_counts[role] > 0))
}

export function frameNativeConstraint(rows: FrameReferenceRow[], index: number, visual?: VideoVisualInputCapabilities, nativeRequired = false) {
  const role = rows[index].frameRole ?? "first_frame"
  const label = role === "last_frame" ? "尾帧" : "首帧"
  if (!visual) return nativeRequired ? "尚未获取当前模型的原生帧能力。" : "尚未获取当前模型的帧能力，暂按普通参考图处理。"
  if (!supportsNativeFrame(role, visual, nativeRequired)) return nativeRequired ? `当前模型不支持原生${label}。` : `当前模型的故事版视频不支持原生${label}，通过提示词作为${label}参考。`
  const modes = visual.modes.filter((mode) => (nativeRequired || mode.max_counts.reference_image > 0) && mode.max_counts[role] > 0)
  if (role === "last_frame" && modes.every((mode) => mode.required_roles.includes("first_frame")) &&
    !rows.some((row) => row.enabled !== false && row.kind === "frame" && (row.frameRole ?? "first_frame") === "first_frame" && row.useNativeFrame !== false)) {
    return nativeRequired ? "原生尾帧需要同时关联原生首帧。" : "原生尾帧需要同时关联并开启原生首帧；当前按普通参考图处理。"
  }
  return nativeRequired ? `当前模型不支持原生${label}与这些参考素材的组合。` : `当前模型不支持原生${label}与这些参考图的组合，按普通参考图处理。`
}

export function AssetReferenceMenu({ referenceLabel, enabled, onEnabledChange, frame, selected, onPreview, children, value, nativeAvailable, nativeActive, combinationValid, constraint, video, nativeRequired = false, modelLabel, unavailableRoles, unsupportedRoles = [], nativeControlsAspectRatio, onChange }: {
  referenceLabel: string
  enabled: boolean
  onEnabledChange: (enabled: boolean) => void
  frame: boolean
  selected?: boolean
  onPreview?: () => void
  children: ReactNode
  value: FrameReferenceOptions
  nativeAvailable: boolean
  nativeActive: boolean
  video: boolean
  nativeRequired?: boolean
  modelLabel?: string
  combinationValid: boolean
  constraint: string
  unavailableRoles: FrameRole[]
  unsupportedRoles?: FrameRole[]
  nativeControlsAspectRatio: boolean
  onChange: (value: FrameReferenceOptions) => void
}) {
  const id = useId()
  const [open, setOpen] = useState(false)
  const triggerRef = useRef<HTMLButtonElement>(null)
  useEffect(() => {
    if (!open) return
    // Canvas panels stop bubbling pointer events; capture outside clicks before them.
    const dismissOutside = (event: PointerEvent) => {
      const target = event.target as Node
      if (!document.getElementById(`${id}-panel`)?.contains(target) && !triggerRef.current?.contains(target)) setOpen(false)
    }
    document.addEventListener("pointerdown", dismissOutside, true)
    return () => document.removeEventListener("pointerdown", dismissOutside, true)
  }, [id, open])
  const roleLabel = value.frameRole === "last_frame" ? "尾帧" : "首帧"
  const explanation = !video
    ? value.frameRole === "last_frame"
      ? "生成分镜图时，让末段画面趋近这张图的视觉状态。"
      : "生成分镜图时，参考这张图延续首镜头的视觉状态。"
    : !combinationValid
      ? "当前素材组合不受模型支持，请调整首尾帧或参考图数量后再生成。"
      : !nativeAvailable
        ? constraint
        : !value.useNativeFrame
          ? `已关闭原生约束，通过提示词作为${roleLabel}参考。`
          : nativeActive
            ? `将此图作为视频的原生${roleLabel}传给模型。${nativeControlsAspectRatio ? "首帧须与项目画幅一致。" : ""}`
            : constraint
  return <Popover open={open} onOpenChange={setOpen}>
    <PopoverAnchor asChild>
      <button
        type="button"
        ref={triggerRef}
        className={`frame-reference-trigger ${selected ? "ring-2 ring-indigo-500 ring-offset-1" : ""} ${enabled ? "" : "grayscale opacity-45"}`}
        title={enabled ? "右键设置参考资产" : "已禁用 · 右键启用"}
        aria-pressed={selected}
        aria-label={`${enabled ? "已启用" : "已禁用"}参考资产，右键设置`}
        onClick={(event) => { event.stopPropagation(); onPreview?.() }}
        onContextMenu={(event) => { event.preventDefault(); event.stopPropagation(); setOpen(true) }}
        onKeyDown={(event) => { if (event.key === "ContextMenu" || (event.shiftKey && event.key === "F10")) { event.preventDefault(); setOpen(true) } }}
      >
        {children}
        <span className="frame-reference-trigger__chevron" aria-hidden="true">
          <ChevronDown size={10} strokeWidth={3} />
        </span>
      </button>
    </PopoverAnchor>
    <PopoverContent
      id={`${id}-panel`}
      className="frame-reference-settings z-[10020]"
      align="start"
      side="top"
      sideOffset={10}
      aria-labelledby={`${id}-title`}
      onClick={(event) => event.stopPropagation()}
      onPointerDown={(event) => event.stopPropagation()}
      onCloseAutoFocus={(event) => event.preventDefault()}
    >
      <div className="frame-reference-settings__header">
        <span id={`${id}-title`} className="frame-reference-settings__badge">{referenceLabel}</span>
      </div>
      <div className="frame-reference-settings__native">
        <label htmlFor={`${id}-enabled`}><strong>参与生成</strong><small>禁用后保留关联，仅用于预览</small></label>
        <Switch id={`${id}-enabled`} checked={enabled} onCheckedChange={onEnabledChange} />
      </div>
      {frame && <>
      <p id={`${id}-role`} className="frame-reference-settings__label">画面用途</p>
      <RadioGroup
        className="frame-reference-settings__roles"
        value={value.frameRole}
        aria-labelledby={`${id}-role`}
        onValueChange={(role) => {
          if (!unavailableRoles.includes(role as FrameRole) && !unsupportedRoles.includes(role as FrameRole)) onChange({ ...value, frameRole: role as FrameRole })
        }}
      >
        {(["first_frame", "last_frame"] as const).map((role) => (
          <label key={role} className="frame-reference-settings__choice" data-frame-role={role}
            data-disabled={unavailableRoles.includes(role) || unsupportedRoles.includes(role) || undefined}>
            <RadioGroupItem value={role} disabled={unavailableRoles.includes(role) || unsupportedRoles.includes(role)} aria-label={role === "first_frame" ? "首帧" : "尾帧"} />
            <span>
              <strong>{role === "first_frame" ? "首帧" : "尾帧"}</strong>
              <small>{unsupportedRoles.includes(role) ? "模型不支持" : unavailableRoles.includes(role) ? "已被占用" : role === "first_frame" ? "开场画面" : "收尾画面"}</small>
            </span>
          </label>
        ))}
      </RadioGroup>
      {video && <div className="frame-reference-settings__model">
        <span>视频模型</span><span>{modelLabel || "未选择"}</span>
      </div>}
      {video && nativeAvailable && !nativeRequired && <div className="frame-reference-settings__native">
        <label htmlFor={`${id}-native`}>
          <strong>原生{roleLabel}约束</strong>
          <small>关闭后作为普通参考图</small>
        </label>
        <Switch
          id={`${id}-native`}
          checked={value.useNativeFrame}
          onCheckedChange={(checked) => onChange({ ...value, useNativeFrame: checked })}
        />
      </div>}
      <p className="frame-reference-settings__note" role="status">{enabled ? explanation : "已禁用，此图不参与生成；启用后按当前帧画面设置使用。"}</p>
      </>}
    </PopoverContent>
  </Popover>
}
