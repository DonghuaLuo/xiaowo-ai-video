import type { PromptBindings } from "./video-prompt-mentions"
import { videoVoiceSettingsKey, type VideoVoiceSettings } from "./video-task-voice-model"

export type VideoPromptDraft = {
  text: string
  soundPrompt?: string
  voiceSettings?: VideoVoiceSettings
  assetNameMap: Record<string, string>
  promptBindings: PromptBindings
}

export type VideoPromptHistory = {
  past: VideoPromptDraft[]
  present: VideoPromptDraft
  future: VideoPromptDraft[]
}

export function createVideoPromptHistory(draft: VideoPromptDraft): VideoPromptHistory {
  return { past: [], present: draft, future: [] }
}

export function sameVideoPromptDraft(left: VideoPromptDraft, right: VideoPromptDraft) {
  const sameMap = (a: Record<string, string>, b: Record<string, string>) =>
    Object.keys(a).length === Object.keys(b).length && Object.keys(a).every((key) => a[key] === b[key])
  return left.text === right.text && (left.soundPrompt ?? "") === (right.soundPrompt ?? "") && sameMap(left.assetNameMap, right.assetNameMap)
    && sameMap(left.promptBindings, right.promptBindings)
    && videoVoiceSettingsKey(left.voiceSettings) === videoVoiceSettingsKey(right.voiceSettings)
}

export function editVideoPromptHistory(history: VideoPromptHistory, draft: VideoPromptDraft): VideoPromptHistory {
  if (sameVideoPromptDraft(history.present, draft)) return history
  // Keep identity metadata in the same undo unit as the text, including deleted mentions.
  const historyLimit = 100
  return { past: [...history.past, history.present].slice(-historyLimit), present: draft, future: [] }
}

export function stepVideoPromptHistory(history: VideoPromptHistory, direction: "undo" | "redo"): VideoPromptHistory {
  if (direction === "undo") {
    if (!history.past.length) return history
    return {
      past: history.past.slice(0, -1),
      present: history.past[history.past.length - 1],
      future: [history.present, ...history.future],
    }
  }
  if (!history.future.length) return history
  return {
    past: [...history.past, history.present],
    present: history.future[0],
    future: history.future.slice(1),
  }
}
