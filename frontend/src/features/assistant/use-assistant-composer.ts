import {
  isAssistantStaticImageFile,
  inputImageFileFromBrowserFile,
  normalizeAssistantTaskTypes,
  normalizeAssistantQuickPrompts,
  normalizeAssistantSkillCommands,
  assistantSlashCommandMatches,
  ASSISTANT_TEXTAREA_MAX_HEIGHT_VH,
  ASSISTANT_MAX_ATTACHMENTS,
} from "./assistant-composer-model"
import React, { useCallback, useEffect, useMemo, useRef, useState } from "react"
import { toast } from "sonner"
import { type InputImageFile } from "@/backend"
import { pickLocalImageFiles } from "@/shared/image-picker"
import { inferImageMimeFromPath } from "@/shared/media"
import { isBackendFailure } from "@/shared/backend-result"
import {
  AssistantAttachment,
  AssistantQuickPrompt,
  AssistantSessionAttachment,
  AssistantSkillCommand,
  assistantSessionAttachmentToUi,
  isAssistantControlOnlyQuickPromptId,
} from "./assistant-session-normalization"
import type { BackendCaller, AgentTargetContext } from "@/backend"
import type { AssistantConversationScope } from "./assistant-session-normalization"
export type AssistantSendOptions = {
  sourceSessionId?: string
  preferredAction?: string
  preferredTaskType?: string
  quickPromptId?: string
  controlOnly?: boolean
  displayMessage?: string
  activeTarget?: AgentTargetContext
  taskOptions?: Record<string, unknown>
  candidateRef?: { runId: string; candidateId: string; candidateDigest: string; candidateVersion: number; candidateType?: "asset_range_candidate" }
}
export type AssistantComposerDraft = {
  text: string
  optimisticText: string
  backendMessage: string
  preferredTaskType?: string
  preferredAction?: string
  quickPromptId?: string
  controlOnly: boolean
  attachments: AssistantAttachment[]
  scope: { key: string }
  override: boolean
  activeTarget?: AgentTargetContext
}
export function useAssistantComposer({
  projectId,
  episodeId,
  assistantScope,
  assistantRequestEpisodeId,
  assistantWorkflowId,
  backendReady,
  callBackend,
  scopeKey,
}: {
  projectId: string
  episodeId: string
  assistantScope: AssistantConversationScope
  assistantRequestEpisodeId: string
  assistantWorkflowId: string
  backendReady: boolean
  callBackend: BackendCaller
  scopeKey: string
}) {
  const scopeRef = useRef({ key: scopeKey })
  if (scopeRef.current.key !== scopeKey) scopeRef.current = { key: scopeKey }
  useEffect(() => {
    if (scopeRef.current.key !== scopeKey) scopeRef.current = { key: scopeKey }
    return () => {
      if (scopeRef.current.key === scopeKey) scopeRef.current = { key: "" }
    }
  }, [scopeKey])
  // Catalogs belong to the project/episode context, not to individual draft resets.
  const catalogScopeRef = useRef({ key: scopeKey })
  if (catalogScopeRef.current.key !== scopeKey)
    catalogScopeRef.current = { key: scopeKey }
  const textareaRef = useRef<HTMLTextAreaElement | null>(null)

  const assistantInputFormRef = useRef<HTMLFormElement | null>(null)

  const assistantRunButtonRef = useRef<HTMLButtonElement | null>(null)

  const slashPosRef = useRef(-1)

  const slashTemplateDraftRef = useRef<{
    text: string
    taskType?: string
    quickPromptId?: string
    controlOnly?: boolean
    displayText?: string
  } | null>(null)

  const [input, setInput] = useState("")

  const [slashMenuOpen, setSlashMenuOpen] = useState(false)

  const [slashActiveIndex, setSlashActiveIndex] = useState(0)

  const [inputFocused, setInputFocused] = useState(false)

  const [attachments, setAttachments] = useState<AssistantAttachment[]>([])

  const [attachmentError, setAttachmentError] = useState<string | null>(null)

  const [slashCommands, setSlashCommands] = useState<AssistantSkillCommand[]>([])

  const [assistantQuickPrompts, setAssistantQuickPrompts] = useState<
    AssistantQuickPrompt[]
  >([])

  const [assistantTaskTypes, setAssistantTaskTypes] = useState<Set<string>>(
    () => new Set()
  )

  const slashFilter = useMemo(() => {
    if (!slashMenuOpen || slashPosRef.current < 0) return ""
    return input
      .slice(slashPosRef.current + 1)
      .split(/\s/)[0]
      .toLowerCase()
  }, [input, slashMenuOpen])

  const filteredSlashCommands = useMemo(
    () =>
      slashCommands.filter((command) =>
        assistantSlashCommandMatches(command, slashFilter)
      ),
    [slashCommands, slashFilter]
  )

  const assistantProgramActions = useMemo(() => {
    const actions = new Set<string>()
    for (const command of slashCommands) {
      if (command.source !== "agent_action" || command.execution !== "program") {
        continue
      }
      if (command.id) actions.add(command.id)
      if (command.name) actions.add(command.name)
    }
    return actions
  }, [slashCommands])

  useEffect(() => {
    if (!backendReady) {
      setSlashCommands([])
      setAssistantQuickPrompts([])
      setAssistantTaskTypes(new Set<string>())
      return
    }
    let cancelled = false
    const requestScope = catalogScopeRef.current
    const loadSkills = async () => {
      try {
        const result = await callBackend<{
          success?: boolean
          commands?: unknown[]
          skills?: unknown[]
          quickPrompts?: unknown[]
          quick_prompts?: unknown[]
          taskCatalog?: unknown[]
          task_catalog?: unknown[]
          message?: string
        }>("list_agent_skills", {
          projectId: projectId,
          episodeId: assistantRequestEpisodeId,
          scope: assistantScope,
          workflowId: assistantWorkflowId,
        })
        if (cancelled || catalogScopeRef.current !== requestScope) return
        if (isBackendFailure(result)) {
          throw new Error(result.message || "加载智能体技能失败")
        }
        const nextCommands = normalizeAssistantSkillCommands(result)
        const nextQuickPrompts = normalizeAssistantQuickPrompts(result)
        const nextTaskTypes = normalizeAssistantTaskTypes(result)
        setSlashCommands(nextCommands)
        setAssistantQuickPrompts(nextQuickPrompts)
        setAssistantTaskTypes(nextTaskTypes)
      } catch (error) {
        console.warn("加载智能体技能失败:", error)
        if (!cancelled && catalogScopeRef.current === requestScope) {
          setSlashCommands([])
          setAssistantQuickPrompts([])
          setAssistantTaskTypes(new Set<string>())
        }
      }
    }
    void loadSkills()
    return () => {
      cancelled = true
    }
  }, [
    assistantScope,
    assistantRequestEpisodeId,
    assistantWorkflowId,
    backendReady,
    callBackend,
    episodeId,
    projectId,
    scopeKey,
  ])

  useEffect(() => {
    setSlashActiveIndex(0)
  }, [slashFilter, filteredSlashCommands.length])

  const saveAgentAttachmentFile = useCallback(
    async (file: InputImageFile): Promise<AssistantAttachment | null> => {
      const result = await callBackend<{
        success?: boolean
        attachment?: AssistantSessionAttachment
        message?: string
      }>("save_agent_attachment", {
        projectId: projectId,
        attachment: {
          name: file.name,
          mimeType: file.mimeType || inferImageMimeFromPath(file.name),
          size: file.size,
          path: file.path,
          filePath: file.filePath ?? file.file_path,
          file: file.file,
          relativePath: file.relativePath,
          relative_path: file.relative_path,
          dataUrl: file.dataUrl,
        },
      })
      if (isBackendFailure(result) || !result.attachment) {
        throw new Error(result.message || "保存附件图片失败")
      }
      return assistantSessionAttachmentToUi(result.attachment)
    },
    [callBackend, projectId]
  )

  const addImageFileRefs = useCallback(
    async (files: InputImageFile[]) => {
      const requestScope = scopeRef.current
      const currentScope = () => scopeRef.current === requestScope
      if (!backendReady) {
        const message = "后端尚未就绪，暂时无法保存附件"
        setAttachmentError(message)
        toast.error(message)
        return
      }
      let saved: AssistantAttachment[]
      try {
        saved = (
          await Promise.all(
            files
              .slice(0, ASSISTANT_MAX_ATTACHMENTS)
              .map((file) => saveAgentAttachmentFile(file))
          )
        ).filter(Boolean) as AssistantAttachment[]
      } catch (error) {
        if (!currentScope()) return
        const message = error instanceof Error ? error.message : "保存附件图片失败"
        setAttachmentError(message)
        toast.error(message)
        return
      }
      if (!currentScope()) return
      if (!saved.length) return
      setAttachmentError(null)
      setAttachments((current) =>
        [...current, ...saved].slice(0, ASSISTANT_MAX_ATTACHMENTS)
      )
    },
    [backendReady, saveAgentAttachmentFile]
  )

  const addImageFiles = useCallback(
    async (files: File[]) => {
      const requestScope = scopeRef.current
      const currentScope = () => scopeRef.current === requestScope
      const imageFiles = files.filter(isAssistantStaticImageFile)
      if (imageFiles.length === 0) {
        const message = "只能添加 PNG、JPG 或 WebP 图片"
        setAttachmentError(message)
        toast.error(message)
        return
      }
      const oversized = imageFiles.find((file) => file.size > 5 * 1024 * 1024)
      if (oversized) {
        const message = "单张附件图片不能超过 5MB"
        setAttachmentError(message)
        toast.error(message)
        return
      }
      try {
        const localFiles = (
          await Promise.all(imageFiles.map(inputImageFileFromBrowserFile))
        ).filter(Boolean) as InputImageFile[]
        if (!currentScope()) return
        if (localFiles.length === 0) {
          const message = "未能读取这张图片，请换一张 PNG、JPG 或 WebP 图片"
          setAttachmentError(message)
          toast.error(message)
          return
        }
        await addImageFileRefs(localFiles)
      } catch (error) {
        if (!currentScope()) return
        const message = error instanceof Error ? error.message : "保存附件图片失败"
        setAttachmentError(message)
        toast.error(message)
      }
    },
    [addImageFileRefs]
  )

  const handlePickAttachments = useCallback(async () => {
    const requestScope = scopeRef.current
    const currentScope = () => scopeRef.current === requestScope
    if (attachments.length >= ASSISTANT_MAX_ATTACHMENTS) return
    const files = await pickLocalImageFiles({
      title: "添加附件图片",
      multiple: true,
    })
    if (!currentScope()) return
    if (files.length > 0) {
      await addImageFileRefs(files)
    }
  }, [addImageFileRefs, attachments.length])

  const handlePaste = useCallback(
    (event: React.ClipboardEvent<HTMLTextAreaElement>) => {
      const files = Array.from(event.clipboardData.items)
        .filter((item) => item.type.startsWith("image/"))
        .map((item) => item.getAsFile())
        .filter(Boolean) as File[]
      if (files.length === 0) return
      event.preventDefault()
      void addImageFiles(files)
    },
    [addImageFiles]
  )

  const handleInputChange = useCallback(
    (event: React.ChangeEvent<HTMLTextAreaElement>) => {
      const nextValue = event.target.value
      const cursor = event.target.selectionStart ?? nextValue.length
      setInput(nextValue)
      const slashTemplateDraft = slashTemplateDraftRef.current
      if (slashTemplateDraft && slashTemplateDraft.text.trim() !== nextValue.trim()) {
        slashTemplateDraftRef.current = null
      }
      const textBeforeCursor = nextValue.slice(0, cursor)
      const lastSlash = textBeforeCursor.lastIndexOf("/")
      if (lastSlash >= 0) {
        const charBefore = lastSlash > 0 ? textBeforeCursor[lastSlash - 1] : undefined
        const atBoundary = charBefore === undefined || /\s/.test(charBefore)
        const afterSlash = textBeforeCursor.slice(lastSlash + 1)
        const noSpaceAfterSlash = !/\s/.test(afterSlash)
        if (atBoundary && noSpaceAfterSlash) {
          slashPosRef.current = lastSlash
          setSlashMenuOpen(true)
        } else {
          slashPosRef.current = -1
          setSlashMenuOpen(false)
        }
      } else {
        slashPosRef.current = -1
        setSlashMenuOpen(false)
      }
      const element = event.target
      element.style.height = "auto"
      const maxHeight = window.innerHeight * (ASSISTANT_TEXTAREA_MAX_HEIGHT_VH / 100)
      element.style.height = `${Math.min(element.scrollHeight, maxHeight)}px`
      element.style.overflowY = element.scrollHeight > maxHeight ? "auto" : "hidden"
    },
    []
  )

  const selectSlashCommand = useCallback(
    (command: AssistantSkillCommand) => {
      const promptText = command.prompt.trim()
      // Slash 菜单只帮用户填入指令模板，发送前仍可继续编辑。
      const commandText = promptText || `/${command.name || command.id}`
      let nextInput = ""
      const pos = slashPosRef.current
      if (pos >= 0) {
        const before = input.slice(0, pos)
        const afterSlash = input.slice(pos)
        const tokenEnd = afterSlash.search(/\s/)
        const after = tokenEnd >= 0 ? input.slice(pos + tokenEnd) : ""
        nextInput = `${before}${commandText} ${after.trimStart()}`
      } else {
        nextInput = `${input}${input.endsWith(" ") || !input ? "" : " "}${commandText} `
      }
      setInput(nextInput)
      const taskType = command.taskType?.trim()
      slashTemplateDraftRef.current = taskType
        ? {
            text: nextInput.trim(),
            taskType,
            quickPromptId: command.id,
            ...(command.controlOnly ? { controlOnly: true } : {}),
            ...(command.controlOnly ? { displayText: command.label } : {}),
          }
        : null
      setSlashMenuOpen(false)
      setSlashActiveIndex(0)
      slashPosRef.current = -1
      window.requestAnimationFrame(() => {
        const element = textareaRef.current
        if (!element) return
        element.focus()
        element.style.height = "auto"
        const maxHeight = window.innerHeight * (ASSISTANT_TEXTAREA_MAX_HEIGHT_VH / 100)
        element.style.height = `${Math.min(element.scrollHeight, maxHeight)}px`
        element.style.overflowY = element.scrollHeight > maxHeight ? "auto" : "hidden"
      })
    },
    [input]
  )
  const prepareSend = useCallback(
    (
      messageOverride?: string,
      options?: AssistantSendOptions
    ): AssistantComposerDraft => {
      const rawText = messageOverride ?? (input || textareaRef.current?.value || "")
      const text = rawText.trim()
      const slashTemplateDraft = slashTemplateDraftRef.current
      const slashTemplateDraftTaskType = slashTemplateDraft?.taskType?.trim() || ""
      const slashTemplateMatches = Boolean(
        slashTemplateDraftTaskType && slashTemplateDraft?.text.trim() === text
      )
      const slashTemplateTaskType =
        !options?.preferredTaskType && slashTemplateMatches
          ? slashTemplateDraftTaskType
          : undefined
      const preferredTaskType = options?.preferredTaskType || slashTemplateTaskType
      const quickPromptId =
        options?.quickPromptId ||
        (slashTemplateMatches ? slashTemplateDraft?.quickPromptId : undefined)
      const slashTemplateDisplayText =
        slashTemplateMatches && slashTemplateDraft?.controlOnly
          ? slashTemplateDraft.displayText?.trim() || ""
          : ""
      const displayText = String(
        options?.displayMessage ?? (slashTemplateDisplayText || text)
      ).trim()
      const optimisticText = displayText || text

      const quickPromptControlOnly = isAssistantControlOnlyQuickPromptId(quickPromptId)
      const slashTemplateControlOnly = Boolean(
        slashTemplateMatches && slashTemplateDraft?.controlOnly
      )
      const controlOnly = Boolean(
        (options?.controlOnly || slashTemplateControlOnly) &&
        (options?.preferredAction || preferredTaskType || quickPromptControlOnly)
      )
      const backendMessage = controlOnly
        ? ""
        : text || optimisticText || "继续执行项目拆分流程"

      return {
        text,
        optimisticText,
        backendMessage,
        preferredTaskType,
        quickPromptId,
        controlOnly,
        preferredAction: options?.preferredAction,
        attachments: messageOverride !== undefined ? [] : attachments,
        scope: scopeRef.current,
        override: messageOverride !== undefined,
        ...(options && "activeTarget" in options
          ? { activeTarget: options.activeTarget }
          : {}),
      }
    },
    [input, attachments]
  )
  const clearError = useCallback(() => setAttachmentError(null), [])
  const invalidate = useCallback(() => {
    scopeRef.current = { key: scopeRef.current.key }
  }, [])
  const accept = useCallback(() => {
    setAttachmentError(null)
    setInput("")
    slashTemplateDraftRef.current = null
    setAttachments([])
    setInputFocused(false)
    setSlashMenuOpen(false)
    if (textareaRef.current) textareaRef.current.style.height = "auto"
  }, [])
  const reset = useCallback(() => {
    invalidate()
    accept()
    if (textareaRef.current) textareaRef.current.style.overflowY = "hidden"
  }, [accept, invalidate])
  const restore = useCallback((draft: AssistantComposerDraft) => {
    if (scopeRef.current !== draft.scope || draft.override) return
    setInput(draft.text)
    setAttachments(draft.attachments)
  }, [])
  const restoreConversationDraft = useCallback((draft: AssistantComposerDraft) => {
    // A deliberate conversation switch starts a new lifetime in the same canvas.
    // Async send failures still use restore(), which requires the exact lifetime.
    if (scopeRef.current.key !== draft.scope.key || draft.override) return
    setInput(draft.text)
    setAttachments(draft.attachments)
    if (draft.preferredTaskType || draft.quickPromptId) {
      slashTemplateDraftRef.current = {
        text: draft.text, taskType: draft.preferredTaskType, quickPromptId: draft.quickPromptId,
        controlOnly: draft.controlOnly, displayText: draft.optimisticText,
      }
    }
  }, [])
  const removeAttachment = useCallback(
    (id: string) => setAttachments((current) => current.filter((item) => item.id !== id)),
    []
  )

  return {
    input,
    attachments,
    attachmentError,
    inputFocused,
    setInputFocused,
    textareaRef,
    assistantInputFormRef,
    assistantRunButtonRef,
    slashMenuOpen,
    setSlashMenuOpen,
    slashActiveIndex,
    setSlashActiveIndex,
    filteredSlashCommands,
    assistantQuickPrompts,
    assistantTaskTypes,
    assistantProgramActions,
    handlePickAttachments,
    handlePaste,
    handleInputChange,
    selectSlashCommand,
    prepareSend,
    clearError,
    accept,
    reset,
    restore,
    restoreConversationDraft,
    removeAttachment,
    invalidate,
  }
}
export type AssistantComposerController = ReturnType<typeof useAssistantComposer>
