import type { NodeEditHistoryItem } from "@/backend"
import { Badge } from "@/components/ui/badge"
import { compactReadableValue, recordValue } from "./workflow-canvas-model"
import {
  DIRECTOR_PLAN_SOUND_KIND_OPTIONS,
  DIRECTOR_PLAN_VOICE_TYPE_OPTIONS,
} from "./director-plan-editor"
import { directorPlanSoundEventText } from "./workflow-prompt-node-model"
import { nodeEditHistoryParameterTags } from "./workflow-edit-history-model"

const headingClass = "text-xs font-semibold text-gray-900 dark:text-gray-100"
const textClass = "text-xs leading-relaxed whitespace-pre-wrap break-words text-gray-800 dark:text-gray-100"

export function WorkflowPlanHistoryContent({ item }: { item?: NodeEditHistoryItem }) {
  if (!item) {
    return <div className="p-3 text-xs text-gray-500 dark:text-gray-400">请选择左侧修改记录</div>
  }
  const content = recordValue(recordValue(item.restorePatch).data)
  const speakers = Array.isArray(content.speakerRoster) ? content.speakerRoster.map(recordValue) : []
  const shots = Array.isArray(content.directorPlanShots) ? content.directorPlanShots.map(recordValue) : []
  const tags = nodeEditHistoryParameterTags(item)
  const prompt = typeof content.finalVideoPrompt === "string" ? content.finalVideoPrompt : ""

  return (
    <div className="flex min-h-0 min-w-0 flex-col md:max-h-[min(58dvh,520px)]">
      <div className="min-h-0 flex-1 space-y-5 overflow-y-auto p-3">
        {item.nodeType === "director.board" ? (
          <>
            <section className="space-y-2">
              <h3 className={headingClass}>临时说话者身份</h3>
              {speakers.length ? (
                <dl className="space-y-2">
                  {speakers.map((speaker, index) => (
                    <div key={index} className="space-y-1">
                      <dt className={headingClass}>{compactReadableValue(speaker.displayName)}</dt>
                      <dd className={textClass}>{compactReadableValue(speaker.identityDescription) || "未提供身份描述"}</dd>
                    </div>
                  ))}
                </dl>
              ) : <p className="text-xs text-gray-500 dark:text-gray-400">无临时说话者</p>}
            </section>
            <section className="space-y-3 border-t border-gray-200 pt-3 dark:border-white/10">
              <h3 className={headingClass}>镜头列表</h3>
              {shots.length ? shots.map((shot, index) => {
                const events = Array.isArray(shot.soundEvents) ? shot.soundEvents.map(recordValue) : []
                return (
                  <div key={index} className="space-y-2 border-b border-gray-200 pb-3 last:border-0 last:pb-0 dark:border-white/10">
                    <div className="flex flex-wrap items-center gap-2">
                      <h4 className={headingClass}>镜头 {String(shot.shotNo ?? index + 1).padStart(2, "0")}</h4>
                      <span className="text-xs text-gray-500 dark:text-gray-400">{compactReadableValue(shot.durationSec) || "0"} 秒</span>
                    </div>
                    <dl className="space-y-2">
                      <div><dt className={headingClass}>分镜画面</dt><dd className={textClass}>{compactReadableValue(shot.storyboardFrame)}</dd></div>
                      <div><dt className={headingClass}>视频执行</dt><dd className={textClass}>{compactReadableValue(shot.videoExecution)}</dd></div>
                      <div>
                        <dt className={headingClass}>声音事件</dt>
                        <dd>
                          {events.length ? (
                            <ul className="space-y-1">
                              {events.map((event, eventIndex) => {
                                const kind = DIRECTOR_PLAN_SOUND_KIND_OPTIONS.find((option) => option.value === event.kind)?.label
                                const voiceType = event.kind === "voice"
                                  ? DIRECTOR_PLAN_VOICE_TYPE_OPTIONS.find((option) => option.value === event.voiceType)?.label
                                  : ""
                                const duration = Number(event.kind === "voice"
                                  ? recordValue(event.deliveryOverride).durationSec
                                  : event.durationSec)
                                return (
                                  <li key={eventIndex} className={textClass}>
                                    {[kind, voiceType].filter(Boolean).join(" / ")}：{directorPlanSoundEventText(event)}
                                    {Number.isFinite(duration) && duration > 0 ? ` · ${event.kind === "voice" ? "慢说例外 " : ""}${duration} 秒` : ""}
                                  </li>
                                )
                              })}
                            </ul>
                          ) : <span className="text-xs text-gray-500 dark:text-gray-400">无</span>}
                        </dd>
                      </div>
                    </dl>
                  </div>
                )
              }) : <p className={textClass}>暂无镜头</p>}
            </section>
          </>
        ) : (
          <section className="space-y-2">
            <h3 className={headingClass}>视频提示词</h3>
            <p className={textClass}>{prompt || "（已清空）"}</p>
          </section>
        )}
      </div>
      <section className="shrink-0 space-y-2 border-t border-gray-200 p-3 dark:border-white/10">
        <h3 className={headingClass}>参数记录</h3>
        <div className="flex flex-wrap gap-1.5">
          {tags.length ? tags.map((tag) => (
            <Badge key={tag} variant="outline" className="max-w-full whitespace-normal break-words text-[10px]">{tag}</Badge>
          )) : <span className="text-xs text-gray-500 dark:text-gray-400">暂无参数记录</span>}
        </div>
      </section>
    </div>
  )
}
