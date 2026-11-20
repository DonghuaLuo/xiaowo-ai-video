import React, { useEffect, useState } from "react"
import { ChevronRight, ClipboardList } from "lucide-react"
import { Button } from "@/components/ui/button"
import { cn } from "@/lib/utils"
import {
  ASSISTANT_OTHER_OPTION_LABEL,
  ASSISTANT_OTHER_OPTION_VALUE,
  AssistantPendingQuestion,
  AssistantPendingQuestionItem,
  AssistantQuestionOption,
} from "./assistant-session-normalization"

export type AssistantQuestionAnswerValue = string | string[]

export function getAssistantQuestionKey(
  question: AssistantPendingQuestionItem,
  index: number
) {
  return question.question.trim() || `question_${index + 1}`
}

export function isAssistantOtherOption(option: AssistantQuestionOption) {
  const label = option.label.trim().toLowerCase()
  return label === "其他" || label === "other"
}

export function getAssistantOptionValue(option: AssistantQuestionOption) {
  return isAssistantOtherOption(option)
    ? ASSISTANT_OTHER_OPTION_VALUE
    : option.value?.trim() || option.label
}

export function getAssistantAnswerValue(
  question: AssistantPendingQuestionItem,
  value: string
) {
  if (value === ASSISTANT_OTHER_OPTION_VALUE) return value
  const option = question.options.find((item) => getAssistantOptionValue(item) === value)
  return option?.label?.trim() || value.trim()
}

export function buildAssistantQuestionOptions(
  options: AssistantQuestionOption[]
): AssistantQuestionOption[] {
  const normalized = Array.isArray(options) ? options : []
  if (normalized.some(isAssistantOtherOption)) return normalized
  return [
    ...normalized,
    {
      label: ASSISTANT_OTHER_OPTION_LABEL,
      description: "若以上选项都不符合，可自行输入",
    },
  ]
}

export function isAssistantOtherSelected(
  question: AssistantPendingQuestionItem,
  value: AssistantQuestionAnswerValue
) {
  if (question.multiSelect) {
    return Array.isArray(value) && value.includes(ASSISTANT_OTHER_OPTION_VALUE)
  }
  return value === ASSISTANT_OTHER_OPTION_VALUE
}

export function isAssistantQuestionReady(
  question: AssistantPendingQuestionItem,
  value: AssistantQuestionAnswerValue,
  customValue: string
) {
  if (question.multiSelect) {
    if (!Array.isArray(value) || value.length === 0) return false
    return !isAssistantOtherSelected(question, value) || customValue.trim().length > 0
  }
  if (typeof value !== "string" || value.trim().length === 0) return false
  return !isAssistantOtherSelected(question, value) || customValue.trim().length > 0
}

export function buildAssistantQuestionAnswers(
  questions: AssistantPendingQuestionItem[],
  answers: Record<string, AssistantQuestionAnswerValue>,
  customAnswers: Record<string, string>
) {
  const payload: Record<string, string> = {}
  questions.forEach((question, index) => {
    const key = getAssistantQuestionKey(question, index)
    const answerKey = question.question || key
    const value = answers[key]
    if (question.multiSelect) {
      if (!Array.isArray(value)) return
      const values = value
        .map((item) =>
          item === ASSISTANT_OTHER_OPTION_VALUE
            ? customAnswers[key]?.trim()
            : getAssistantAnswerValue(question, item)
        )
        .filter(Boolean)
      if (values.length) payload[answerKey] = values.join(", ")
      return
    }
    if (typeof value !== "string") return
    const answerValue =
      value === ASSISTANT_OTHER_OPTION_VALUE
        ? customAnswers[key]?.trim()
        : getAssistantAnswerValue(question, value)
    if (answerValue) payload[answerKey] = answerValue
  })
  return payload
}

export function AssistantPendingQuestionWizard({
  pendingQuestion,
  disabled,
  submitting,
  onSubmit,
}: {
  pendingQuestion: AssistantPendingQuestion
  disabled: boolean
  submitting: boolean
  onSubmit: (questionId: string, answers: Record<string, string>) => void
}) {
  const questions = pendingQuestion.questions
  const [currentIndex, setCurrentIndex] = useState(0)
  const [visitedIndexes, setVisitedIndexes] = useState<number[]>([])
  const [answers, setAnswers] = useState<Record<string, AssistantQuestionAnswerValue>>({})
  const [customAnswers, setCustomAnswers] = useState<Record<string, string>>({})

  useEffect(() => {
    const nextAnswers: Record<string, AssistantQuestionAnswerValue> = {}
    const nextCustomAnswers: Record<string, string> = {}
    questions.forEach((question, index) => {
      const key = getAssistantQuestionKey(question, index)
      nextAnswers[key] = question.multiSelect ? [] : ""
      nextCustomAnswers[key] = ""
    })
    setCurrentIndex(0)
    setVisitedIndexes(questions.length ? [0] : [])
    setAnswers(nextAnswers)
    setCustomAnswers(nextCustomAnswers)
  }, [pendingQuestion.question_id, questions])

  if (!questions.length) return null

  const normalizedIndex = Math.min(currentIndex, questions.length - 1)
  const currentQuestion = questions[normalizedIndex]
  const currentKey = getAssistantQuestionKey(currentQuestion, normalizedIndex)
  const currentAnswer = answers[currentKey] ?? (currentQuestion.multiSelect ? [] : "")
  const currentCustomAnswer = customAnswers[currentKey] ?? ""
  const isFirst = normalizedIndex === 0
  const isLast = normalizedIndex === questions.length - 1
  const currentReady = isAssistantQuestionReady(
    currentQuestion,
    currentAnswer,
    currentCustomAnswer
  )
  const allReady = questions.every((question, index) => {
    const key = getAssistantQuestionKey(question, index)
    return isAssistantQuestionReady(
      question,
      answers[key] ?? (question.multiSelect ? [] : ""),
      customAnswers[key] ?? ""
    )
  })

  const setSingleAnswer = (key: string, value: string) => {
    setAnswers((current) => ({ ...current, [key]: value }))
  }

  const toggleMultiAnswer = (key: string, value: string, checked: boolean) => {
    setAnswers((current) => {
      const existing = Array.isArray(current[key]) ? current[key] : []
      return {
        ...current,
        [key]: checked
          ? Array.from(new Set([...existing, value]))
          : existing.filter((item) => item !== value),
      }
    })
  }

  const handleSubmit = (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (disabled || submitting || !allReady) return
    onSubmit(
      pendingQuestion.question_id,
      buildAssistantQuestionAnswers(questions, answers, customAnswers)
    )
  }

  return (
    <form
      className="border-t border-indigo-100/80 bg-indigo-50/25 px-3 py-2 dark:border-indigo-950/40 dark:bg-indigo-950/10"
      onSubmit={handleSubmit}
    >
      <div className="flex max-h-[34vh] min-h-0 flex-col gap-2.5">
        <div className="flex items-center justify-between gap-2">
          <div className="flex min-w-0 items-center gap-1.5">
            <ClipboardList className="size-3 text-indigo-500 dark:text-indigo-300" />
            <span className="text-[10px] font-semibold tracking-[0.18em] text-indigo-600 uppercase dark:text-indigo-300">
              {currentQuestion.header || "问题"}
            </span>
          </div>
          <span className="font-mono text-[10px] text-gray-400">
            {String(normalizedIndex + 1).padStart(2, "0")} /{" "}
            {String(questions.length).padStart(2, "0")}
          </span>
        </div>

        {questions.length > 1 ? (
          <div className="flex items-center gap-1">
            {questions.map((question, index) => {
              const active = index === normalizedIndex
              const visited = visitedIndexes.includes(index)
              return (
                <button
                  key={`${pendingQuestion.question_id}-${index}`}
                  type="button"
                  disabled={disabled || submitting || !visited}
                  className={cn(
                    "h-1 flex-1 rounded-full transition disabled:cursor-not-allowed",
                    active
                      ? "bg-indigo-500 shadow-[0_0_10px_rgb(99_102_241_/_0.35)]"
                      : visited
                        ? "bg-indigo-200 dark:bg-indigo-900/70"
                        : "bg-gray-200/70 dark:bg-white/10"
                  )}
                  title={question.header || `问题 ${index + 1}`}
                  onClick={() => setCurrentIndex(index)}
                />
              )
            })}
          </div>
        ) : null}

        <p className="border-l-2 border-indigo-400 pl-2 text-[12.5px] leading-[1.45] font-medium text-gray-800 dark:text-gray-100">
          {currentQuestion.question}
        </p>

        <div className="min-h-0 overflow-y-auto pr-1">
          <div className="overflow-hidden rounded-lg border border-gray-200/80 bg-white/70 dark:border-white/10 dark:bg-white/[0.035]">
            {buildAssistantQuestionOptions(currentQuestion.options).map(
              (option, index) => {
                const optionValue = getAssistantOptionValue(option)
                const checked = currentQuestion.multiSelect
                  ? Array.isArray(currentAnswer) && currentAnswer.includes(optionValue)
                  : currentAnswer === optionValue
                return (
                  <label
                    key={optionValue}
                    className={cn(
                      "relative block cursor-pointer border-b border-gray-200/70 px-2.5 py-1.5 transition-colors last:border-b-0 dark:border-white/10",
                      checked
                        ? "bg-indigo-50/85 dark:bg-indigo-950/20"
                        : "hover:bg-gray-50/85 dark:hover:bg-white/[0.055]",
                      (disabled || submitting) && "cursor-not-allowed opacity-60"
                    )}
                  >
                    <input
                      type={currentQuestion.multiSelect ? "checkbox" : "radio"}
                      name={`assistant-question-${pendingQuestion.question_id}-${currentKey}`}
                      checked={checked}
                      disabled={disabled || submitting}
                      className="sr-only"
                      onChange={(event) => {
                        if (currentQuestion.multiSelect) {
                          toggleMultiAnswer(currentKey, optionValue, event.target.checked)
                          return
                        }
                        setSingleAnswer(currentKey, optionValue)
                      }}
                    />
                    {checked ? (
                      <span className="absolute inset-y-0 left-0 w-0.5 bg-indigo-500" />
                    ) : null}
                    <div className="flex items-start justify-between gap-2">
                      <div className="flex min-w-0 flex-1 items-start gap-2">
                        <span
                          className={cn(
                            "mt-0.5 grid size-3.5 shrink-0 place-items-center border text-[9px]",
                            currentQuestion.multiSelect
                              ? "rounded-[3px]"
                              : "rounded-full",
                            checked
                              ? "border-indigo-500 bg-indigo-500 text-white"
                              : "border-gray-300 text-transparent dark:border-white/20"
                          )}
                        >
                          {checked ? "✓" : ""}
                        </span>
                        <div className="min-w-0">
                          <div className="flex flex-wrap items-center gap-2">
                            <span className="font-mono text-[10.5px] text-gray-400 dark:text-gray-500">
                              {String(index + 1).padStart(2, "0")}
                            </span>
                            <span className="text-[12px] font-semibold text-gray-900 dark:text-gray-50">
                              {option.label}
                            </span>
                            {option.recommended ? (
                              <span className="rounded-lg border border-indigo-200 bg-indigo-50 px-1.5 py-0 text-[9.5px] text-indigo-600 dark:border-indigo-900/60 dark:bg-indigo-950/25 dark:text-indigo-200">
                                推荐
                              </span>
                            ) : null}
                          </div>
                          {option.description ? (
                            <p className="mt-0.5 text-[11px] leading-[1.45] text-gray-500 dark:text-gray-400">
                              {option.description}
                            </p>
                          ) : null}
                        </div>
                      </div>
                      <ChevronRight className="mt-0.5 size-3.5 shrink-0 text-gray-300 dark:text-gray-600" />
                    </div>
                  </label>
                )
              }
            )}
          </div>
        </div>

        {isAssistantOtherSelected(currentQuestion, currentAnswer) ? (
          <textarea
            value={currentCustomAnswer}
            disabled={disabled || submitting}
            rows={2}
            className="max-h-28 min-h-12 w-full resize-none rounded-lg border border-indigo-200/80 bg-white/70 px-2.5 py-2 text-[12px] leading-[1.5] text-gray-700 transition outline-none focus:border-indigo-400 dark:border-indigo-900/60 dark:bg-white/[0.04] dark:text-gray-200"
            placeholder="输入你的补充说明"
            onChange={(event) =>
              setCustomAnswers((current) => ({
                ...current,
                [currentKey]: event.target.value,
              }))
            }
          />
        ) : null}

        <div className="flex shrink-0 items-center justify-between gap-2">
          <Button
            type="button"
            variant="ghost"
            size="sm"
            className="h-7 px-2 text-[12px] text-gray-500 hover:text-gray-900 dark:text-gray-400 dark:hover:text-gray-100"
            disabled={disabled || submitting || isFirst}
            onClick={() => setCurrentIndex((current) => Math.max(0, current - 1))}
          >
            上一步
          </Button>
          {isLast ? (
            <Button
              type="submit"
              size="sm"
              className="h-7 bg-gradient-to-r from-indigo-600 via-sky-600 to-emerald-500 px-3 text-[12px] text-white shadow-sm hover:opacity-90"
              disabled={disabled || submitting || !allReady}
            >
              {submitting ? "提交中..." : "提交选择"}
            </Button>
          ) : (
            <Button
              type="button"
              size="sm"
              className="h-7 bg-gradient-to-r from-indigo-600 via-sky-600 to-emerald-500 px-3 text-[12px] text-white shadow-sm hover:opacity-90"
              disabled={disabled || submitting || !currentReady}
              onClick={() => {
                const nextIndex = Math.min(questions.length - 1, currentIndex + 1)
                setVisitedIndexes((current) =>
                  Array.from(new Set([...current, nextIndex]))
                )
                setCurrentIndex(nextIndex)
              }}
            >
              下一步
            </Button>
          )}
        </div>
      </div>
    </form>
  )
}
