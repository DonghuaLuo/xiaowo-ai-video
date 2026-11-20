import { useEffect, useRef, useState } from "react"
import { Plus, Trash2, Upload, X } from "lucide-react"
import type { InputImageFile, MediaAsset } from "@/backend"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Textarea } from "@/components/ui/textarea"
import { useBackend } from "@/hooks/useBackend"
import { pickLocalMediaFile } from "@/shared/image-picker"
import { mediaAssetFromImageFile, mediaPreviewSrc } from "@/shared/media"
import { ReferenceAudioCropDialog } from "@/shared/reference-audio-crop-dialog"
import { ReferenceAudioPlayer } from "@/shared/reference-audio-player"
import { toast } from "sonner"
import type { WorkflowNodeData } from "./workflow-canvas-model"
import {
  addVideoTaskVoice, hasVideoTaskVoiceName, removeVideoTaskVoice, updateVideoVoiceStyle, videoTaskVoiceName, videoVoiceStyleFromSoundPrompt,
  type VideoVoiceOverride, type VideoVoiceSettings,
} from "./video-task-voice-model"

type VoiceSource = {
  speakerId: string
  displayName: string
  voiceStyle: string
  referenceAudio?: MediaAsset | null
}

const selectClass = "nodrag w-full min-w-0 rounded-[6px] px-2 text-xs shadow-none"

export function VideoTaskVoiceSettings({ id, data, soundPrompt, settings, readOnly, onSettingsChange }: {
  id: string
  data: WorkflowNodeData
  soundPrompt: string
  settings: VideoVoiceSettings
  readOnly: boolean
  onSettingsChange: (settings: VideoVoiceSettings, soundPrompt: string) => void
}) {
  const { callBackend, onBackendEvent, backendReady } = useBackend()
  const [voices, setVoices] = useState<VoiceSource[]>([])
  const [available, setAvailable] = useState<VoiceSource[]>([])
  const [projectSpeakers, setProjectSpeakers] = useState<VoiceSource[]>([])
  const [error, setError] = useState("")
  const [revision, setRevision] = useState(0)
  const [adding, setAdding] = useState(false)
  const [selectedRole, setSelectedRole] = useState("")
  const [selectedProjectRole, setSelectedProjectRole] = useState("")
  const [customName, setCustomName] = useState("")
  const [newMode, setNewMode] = useState<"text" | "reference_audio">("text")
  const [crop, setCrop] = useState<{ speakerId: string; file: InputImageFile } | null>(null)
  const latest = useRef({ id, projectId: data.projectId, settings, soundPrompt, readOnly, active: true })
  Object.assign(latest.current, { id, projectId: data.projectId, settings, soundPrompt, readOnly })
  useEffect(() => {
    latest.current.active = true
    return () => { latest.current.active = false }
  }, [])
  useEffect(() => {
    setVoices([]); setAvailable([]); setProjectSpeakers([]); setError(""); setAdding(false); setCrop(null)
    setSelectedRole(""); setSelectedProjectRole(""); setCustomName("")
  }, [id, data.projectId])
  const previewKey = JSON.stringify({
    projectId: data.projectId, eyebrow: data.eyebrow,
    videoTaskCard: { ...data.videoTaskCard, ...settings, soundPrompt }, inputLinks: data.inputLinks,
    referenceManifest: data.referenceManifest, referenceDisplayRows: data.referenceDisplayRows,
    generationConfig: data.generationConfig,
  })
  useEffect(() => onBackendEvent("project_changed", (event) => {
    if (event.projectId === data.projectId) setRevision((value) => value + 1)
  }), [data.projectId, onBackendEvent])
  useEffect(() => {
    if (!backendReady || !data.workflowCardDetailLoaded) return
    let cancelled = false
    const timer = setTimeout(() => {
      void callBackend<{ success: boolean; speakers?: VoiceSource[]; availableSpeakers?: VoiceSource[]; projectSpeakers?: VoiceSource[]; message?: string }>("preview_video_task_voices", {
        projectId: data.projectId, data: JSON.parse(previewKey),
      }).then((result) => {
        if (cancelled) return
        if (!result.success) { setError(result.message || "声音设置读取失败"); return }
        setVoices(result.speakers ?? [])
        setAvailable(result.availableSpeakers ?? [])
        setProjectSpeakers(result.projectSpeakers ?? [])
        setError("")
      }).catch((cause) => { if (!cancelled) setError(cause instanceof Error ? cause.message : "声音设置读取失败") })
    }, 200)
    return () => { cancelled = true; clearTimeout(timer) }
  }, [backendReady, data.workflowCardDetailLoaded, data.projectId, previewKey, revision, callBackend])

  const changeVoice = (speakerId: string, patch: Partial<VideoVoiceOverride>, nextSound = latest.current.soundPrompt) => {
    const current = latest.current
    if (current.readOnly || !current.settings.usedSpeakerIds.includes(speakerId)) return
    onSettingsChange({ ...current.settings, voiceOverrides: {
      ...current.settings.voiceOverrides,
      [speakerId]: { mode: "text", ...current.settings.voiceOverrides[speakerId], ...patch },
    } }, nextSound)
  }
  const selectedVoice = selectedRole === "project"
    ? projectSpeakers.find((row) => row.speakerId === selectedProjectRole)
    : available.find((row) => row.speakerId === selectedRole)
  const sources = [...voices,
    ...Object.entries(data.videoTaskCard?.assetNameMap ?? {}).flatMap(([key, name]) => typeof name === "string"
      ? [{ speakerId: `asset:${key}`, displayName: name }] : []),
    ...available, ...projectSpeakers, { speakerId: "project:narrator", displayName: "旁白" }]
  const candidateName = selectedRole === "custom" ? customName.trim() : selectedVoice?.displayName.trim() || ""
  const duplicateName = Boolean(candidateName && hasVideoTaskVoiceName(settings, candidateName, sources))
  const canAdd = Boolean(candidateName && !duplicateName && (selectedRole === "custom"
    || selectedVoice && !settings.usedSpeakerIds.includes(selectedVoice.speakerId)))
  const canChoose = (row: VoiceSource) => !settings.usedSpeakerIds.includes(row.speakerId)
    && !hasVideoTaskVoiceName(settings, row.displayName, sources)
  const addVoice = () => {
    const voice = selectedRole === "custom"
      ? { speakerId: `temporary:${crypto.randomUUID()}`, displayName: customName.trim(), voiceStyle: "" }
      : selectedVoice
    if (!voice?.displayName || readOnly || !canAdd) return
    onSettingsChange(addVideoTaskVoice(settings, voice, newMode, sources),
      voice.voiceStyle ? updateVideoVoiceStyle(soundPrompt, voice.displayName, voice.voiceStyle) : soundPrompt)
    setAdding(false); setSelectedRole(""); setSelectedProjectRole(""); setCustomName("")
  }
  const pickAudio = async (speakerId: string) => {
    const owner = { id, projectId: data.projectId }
    try {
      const file = await pickLocalMediaFile("上传参考音频", "audio")
      const current = latest.current
      if (file && current.active && current.id === owner.id && current.projectId === owner.projectId
          && !current.readOnly && current.settings.usedSpeakerIds.includes(speakerId)) setCrop({ speakerId, file })
    } catch (cause) { toast.error(cause instanceof Error ? cause.message : "参考音频读取失败") }
  }
  const saveAudio = async (file: InputImageFile) => {
    if (!crop || readOnly) return
    const owner = { id, projectId: data.projectId, speakerId: crop.speakerId }
    // The crop dialog removes its temporary file after this callback resolves.
    const result = await callBackend<{ success: boolean; referenceAudio?: MediaAsset; message?: string }>("import_video_task_reference_audio", {
      projectId: owner.projectId, media: mediaAssetFromImageFile(file),
    })
    if (!result.success || !result.referenceAudio) throw new Error(result.message || "参考音频保存失败")
    const current = latest.current
    if (current.active && current.id === owner.id && current.projectId === owner.projectId && !current.readOnly)
      changeVoice(owner.speakerId, { mode: "reference_audio", referenceAudio: result.referenceAudio })
  }

  return <section aria-label="声音列表" className="space-y-2 text-xs">
    <div className="flex items-center justify-between gap-2">
      <span className="font-medium text-gray-700 dark:text-gray-200">声音列表</span>
      <Button type="button" variant="ghost" size="icon" className="nodrag size-6" aria-label="添加声音"
        disabled={readOnly} onClick={() => setAdding(true)}><Plus className="size-3.5" /></Button>
    </div>
    {!settings.usedSpeakerIds.length && !adding ? <p className="text-gray-500">暂无声音信息</p> : null}
    {error && settings.usedSpeakerIds.length ? <p role="alert" className="text-amber-700 dark:text-amber-300">{error}</p> : null}
    {adding ? <div className="space-y-2 rounded-md border border-gray-200 p-2 dark:border-white/15">
      <div className="flex items-center justify-between"><span>新建声音</span>
        <Button type="button" variant="ghost" size="icon" className="size-5" aria-label="取消添加声音" onClick={() => setAdding(false)}><X className="size-3" /></Button>
      </div>
      <div className="grid grid-cols-[minmax(0,1fr)_minmax(0,1fr)_auto] items-start gap-1.5">
        <div className="min-w-0">
          <Select value={selectedRole} disabled={readOnly} onValueChange={(value) => { setSelectedRole(value); setSelectedProjectRole("") }}>
            <SelectTrigger aria-label="指定角色" size="sm" className={selectClass}><SelectValue placeholder="选择角色" /></SelectTrigger>
            <SelectContent className="z-[400]">
              {available.filter(canChoose).map((row) => <SelectItem key={row.speakerId} value={row.speakerId}>{row.displayName}</SelectItem>)}
              <SelectItem value="project">从项目角色中选择</SelectItem>
              <SelectItem value="custom">手动填写角色名称</SelectItem>
            </SelectContent>
          </Select>
        </div>
        <Select value={newMode} disabled={readOnly} onValueChange={(value) => setNewMode(value as typeof newMode)}>
          <SelectTrigger aria-label="新声音类型" size="sm" className={selectClass}><SelectValue /></SelectTrigger>
          <SelectContent className="z-[400]">
            <SelectItem value="text">声音提示词</SelectItem><SelectItem value="reference_audio">参考音频</SelectItem>
          </SelectContent>
        </Select>
        <Button type="button" aria-label="确认添加声音" variant="outline" size="sm"
          className="nodrag h-8 gap-1.5 rounded-[6px] border-indigo-200 bg-indigo-50/60 px-2.5 text-xs text-indigo-700 shadow-none hover:border-indigo-300 hover:bg-indigo-100 hover:text-indigo-800 dark:border-indigo-400/25 dark:bg-indigo-400/10 dark:text-indigo-200 dark:hover:bg-indigo-400/20"
          disabled={readOnly || !canAdd} onClick={addVoice}>
          <Plus className="size-3.5" strokeWidth={1.75} />添加
        </Button>
      </div>
      {selectedRole === "project" ? <Select value={selectedProjectRole} disabled={readOnly} onValueChange={setSelectedProjectRole}>
        <SelectTrigger aria-label="选择项目角色" size="sm" className={selectClass}><SelectValue placeholder="选择项目角色" /></SelectTrigger>
        <SelectContent className="z-[400]">
          {projectSpeakers.filter(canChoose).map((row) => <SelectItem key={row.speakerId} value={row.speakerId}>{row.displayName}</SelectItem>)}
        </SelectContent>
      </Select> : null}
      {selectedRole === "custom" ? <Input aria-label="角色名称" placeholder="角色名称" value={customName} disabled={readOnly} className="nodrag h-8 w-full rounded-[6px] px-1 text-[11px]" onChange={(event) => setCustomName(event.target.value)} /> : null}
      {duplicateName ? <p role="alert" className="text-amber-700 dark:text-amber-300">该角色已添加声音，请勿重复添加</p> : null}
    </div> : null}
    {settings.usedSpeakerIds.map((speakerId) => {
      const voice = voices.find((row) => row.speakerId === speakerId) ?? available.find((row) => row.speakerId === speakerId)
        ?? projectSpeakers.find((row) => row.speakerId === speakerId)
      const design = settings.voiceDesign.speakers.find((row) => row.speakerId === speakerId)
      const override = settings.voiceOverrides[speakerId]
      const name = videoTaskVoiceName(settings, speakerId, sources)
      const audio = override && "referenceAudio" in override ? override.referenceAudio : voice?.referenceAudio
      const mode = override?.mode === "text" ? "text" : override?.mode === "reference_audio" || audio ? "reference_audio" : "text"
      const style = override?.voiceStyle ?? videoVoiceStyleFromSoundPrompt(soundPrompt, name, voice?.voiceStyle || design?.voiceStyle || "")
      return <div key={speakerId} className="space-y-2 rounded-md bg-gray-500/5 p-2">
        <div className="flex items-center justify-between gap-2"><span className="font-medium">{name}</span>
          <Button type="button" variant="ghost" size="icon" className="nodrag size-6" aria-label={`删除${name}的声音`} disabled={readOnly} onClick={() => {
            const next = removeVideoTaskVoice(settings, speakerId)
            onSettingsChange(next, soundPrompt.split("\n").filter((line) => !line.trim().startsWith(`- ${name}：`)).join("\n"))
          }}><Trash2 className="size-3.5" /></Button>
        </div>
        {mode === "reference_audio" ? <div className="flex min-w-0 items-center gap-1 rounded-md border border-indigo-100 bg-indigo-50/40 px-2 py-1.5 dark:border-indigo-900/40 dark:bg-indigo-950/20">
          <ReferenceAudioPlayer src={audio ? mediaPreviewSrc(audio) : null} className="min-w-0 flex-1" />
          <Button type="button" aria-label={`上传${name}的参考音频`} title={audio ? "替换参考音频" : "上传参考音频"} variant="ghost" size="icon-sm"
            className="nodrag size-[30px] shrink-0 rounded-sm text-indigo-600 hover:bg-indigo-50 dark:text-indigo-300 dark:hover:bg-indigo-950/30"
            disabled={readOnly} onClick={() => void pickAudio(speakerId)}>
            <Upload className="size-3.5" />
          </Button>
          <Button type="button" variant="ghost" size="icon-sm"
            className="nodrag size-[30px] shrink-0 rounded-sm text-rose-600 hover:bg-rose-50/80 hover:text-rose-700 disabled:text-gray-400 dark:text-rose-300 dark:hover:bg-rose-400/10 dark:hover:text-rose-200 dark:disabled:text-gray-500"
            disabled={readOnly || !audio} onClick={() => changeVoice(speakerId, { mode: "reference_audio", referenceAudio: null })}
            title="移除参考音频" aria-label={`移除${name}的参考音频`}>
            <Trash2 className="size-3.5" />
          </Button>
        </div> : <Textarea aria-label={`${name}的声音设计提示词`} value={style} readOnly={readOnly} placeholder="填写声音设计提示词"
          className="nodrag nowheel min-h-20 resize-y text-xs" onChange={(event) => changeVoice(speakerId,
            { mode: "text", voiceStyle: event.target.value }, updateVideoVoiceStyle(soundPrompt, name, event.target.value))} />}
      </div>
    })}
    <ReferenceAudioCropDialog open={Boolean(crop)} sourceFile={crop?.file ?? null} callBackend={callBackend}
      title="裁剪参考音频" onClose={() => setCrop(null)} onConfirm={saveAudio} />
  </section>
}
