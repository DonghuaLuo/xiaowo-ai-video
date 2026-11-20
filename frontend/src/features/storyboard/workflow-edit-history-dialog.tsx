import { CheckCircle2, Loader2, RefreshCcw, X } from "lucide-react"
import { isWorkflowVideoTaskType } from "./workflow-video-task-types"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip"
import { cn } from "@/lib/utils"
import { ConfirmDialog } from "@/shared/confirm-dialog"
import { formatWorkflowFullDateTime } from "./workflow-task-status"
import {
  nodeEditHistoryContentColumns,
  nodeEditHistoryParameterTags,
} from "./workflow-edit-history-model"
import type { WorkflowEditHistoryController } from "./use-workflow-edit-history"
import { WorkflowPlanHistoryContent } from "./workflow-plan-history-content"

export interface WorkflowEditHistoryDialogProps {
  controller: WorkflowEditHistoryController
  nodeTitle?: string
  nodeType?: string
}

export function WorkflowEditHistoryDialog({
  controller,
  nodeTitle,
  nodeType,
}: WorkflowEditHistoryDialogProps) {
  const historyNodeType = controller.selectedItem?.nodeType ?? nodeType
  const planHistory = historyNodeType === "director.board" || isWorkflowVideoTaskType(historyNodeType)
  const columns = nodeEditHistoryContentColumns(controller.selectedItem)
  const tags = nodeEditHistoryParameterTags(controller.selectedItem)
  return (
    <>
      <Dialog
        open={Boolean(controller.nodeId)}
        onOpenChange={(open) => {
          if (!open) controller.close()
        }}
      >
        <DialogContent className={cn(
          "flex max-h-[min(82dvh,720px)] !max-w-none flex-col gap-0 overflow-hidden p-4 pb-3",
          planHistory ? "!w-[min(980px,calc(100vw-1.5rem))]" : "!w-[min(1220px,calc(100vw-1.5rem))]"
        )}>
          <DialogHeader className="gap-0 pr-8 pb-1">
            <DialogTitle className="m-0 text-base leading-5">
              修改记录
            </DialogTitle>
            <DialogDescription className="m-0 truncate text-sm leading-5 font-medium text-gray-700 dark:text-gray-200">
              {nodeTitle ?? "当前节点"}
            </DialogDescription>
          </DialogHeader>
          <div className={cn(
            "grid min-h-0 flex-1 gap-3 overflow-y-auto pt-2 pb-3",
            planHistory ? "md:grid-cols-[220px_minmax(0,1fr)]" : "md:grid-cols-[240px_minmax(0,1fr)_minmax(0,1fr)]"
          )}>
            <div className="max-h-[min(34dvh,220px)] overflow-y-auto rounded-md border border-gray-200 bg-white p-1 md:max-h-[min(58dvh,520px)] dark:border-white/10 dark:bg-white/[0.03]">
              {controller.loading ? (
                <div className="px-3 py-4 text-xs text-gray-500 dark:text-gray-400">
                  正在加载...
                </div>
              ) : controller.items.length ? (
                controller.items.map((item, index) => {
                  const selected = item.id === controller.selectedItem?.id
                  const current = item.id === controller.currentId
                  const deleting = controller.deletingId === item.id
                  const versionLabel = `修改版本 ${controller.items.length - index}`
                  return (
                    <div
                      key={item.id}
                      className={cn(
                        "group rounded-sm px-3 py-2 text-xs transition-colors",
                        selected
                          ? "bg-gray-100 text-gray-950 ring-1 ring-gray-200 ring-inset dark:bg-[#2a2a30] dark:text-gray-50 dark:ring-white/10"
                          : "text-gray-700 hover:bg-gray-100 dark:text-gray-200 dark:hover:bg-white/10"
                      )}
                    >
                      <div className="flex items-start gap-2">
                        <button
                          type="button"
                          className="min-w-0 flex-1 text-left"
                          onClick={() => controller.select(item.id)}
                        >
                          <span className="flex min-w-0 items-center gap-1.5">
                            {current ? (
                              <span
                                className="size-2 shrink-0 rounded-full bg-emerald-500 ring-2 ring-emerald-100 dark:bg-emerald-400 dark:ring-emerald-950/70"
                                aria-label="当前版本"
                                title="当前版本"
                              />
                            ) : null}
                            <span className="truncate font-medium">
                              {versionLabel}
                            </span>
                          </span>
                          <span className="mt-0.5 block truncate opacity-70">
                            {formatWorkflowFullDateTime(
                              item.createdAt || item.displayTime
                            ) || "未知时间"}
                          </span>
                        </button>
                        {!current ? (
                          <Tooltip>
                            <TooltipTrigger asChild>
                              <Button
                                type="button"
                                variant="ghost"
                                size="icon"
                                className="h-6 w-6 shrink-0 rounded-full text-gray-400 opacity-0 transition-opacity group-focus-within:opacity-100 group-hover:opacity-100 hover:bg-rose-50 hover:text-rose-600 dark:text-gray-500 dark:hover:bg-rose-950/30 dark:hover:text-rose-300"
                                disabled={Boolean(controller.deletingId)}
                                aria-label={`删除${versionLabel}`}
                                onClick={(event) => {
                                  event.stopPropagation()
                                  controller.requestDelete(item)
                                }}
                              >
                                {deleting ? (
                                  <Loader2 className="size-3.5 animate-spin" />
                                ) : (
                                  <X className="size-3.5" />
                                )}
                              </Button>
                            </TooltipTrigger>
                            <TooltipContent>删除该版本</TooltipContent>
                          </Tooltip>
                        ) : null}
                      </div>
                    </div>
                  )
                })
              ) : (
                <div className="px-3 py-4 text-xs text-gray-500 dark:text-gray-400">
                  暂无修改记录
                </div>
              )}
            </div>
            {planHistory ? (
              <div className="min-h-0 min-w-0 overflow-hidden rounded-md border border-gray-200 bg-white dark:border-white/10 dark:bg-white/[0.03]">
                <WorkflowPlanHistoryContent item={controller.selectedItem} />
              </div>
            ) : <>
            <div className="max-h-[min(38dvh,360px)] overflow-y-auto rounded-md border border-gray-200 bg-gray-50 p-3 md:max-h-[min(58dvh,520px)] dark:border-white/10 dark:bg-black/20">
              {controller.selectedItem ? (
                <div className="space-y-3">
                  <div className="text-xs font-semibold text-gray-900 dark:text-gray-100">
                    {columns.middleTitle}
                  </div>
                  <div className="text-xs leading-relaxed break-words whitespace-pre-wrap text-gray-800 dark:text-gray-100">
                    {columns.middleText}
                  </div>
                  <div className="border-t border-gray-200/80 pt-3 dark:border-white/10">
                    <div className="mb-2 text-[11px] font-semibold text-gray-500 dark:text-white/50">
                      参数记录
                    </div>
                    <div className="flex flex-wrap gap-1.5">
                      {tags.length ? (
                        tags.map((tag) => (
                          <Badge
                            key={tag}
                            variant="outline"
                            className="rounded-full bg-white/80 text-[10px] dark:bg-white/[0.04]"
                          >
                            {tag}
                          </Badge>
                        ))
                      ) : (
                        <span className="text-[11px] text-gray-400 dark:text-gray-500">
                          暂无参数记录
                        </span>
                      )}
                    </div>
                  </div>
                </div>
              ) : (
                <div className="text-xs text-gray-500 dark:text-gray-400">
                  请选择左侧修改记录
                </div>
              )}
            </div>
            <div className="max-h-[min(38dvh,360px)] overflow-y-auto rounded-md border border-gray-200 bg-white p-3 md:max-h-[min(58dvh,520px)] dark:border-white/10 dark:bg-white/[0.03]">
              {controller.selectedItem ? (
                <div className="space-y-3">
                  <div className="text-xs font-semibold text-gray-900 dark:text-gray-100">
                    {columns.rightTitle}
                  </div>
                  <div className="text-xs leading-relaxed break-words whitespace-pre-wrap text-gray-800 dark:text-gray-100">
                    {columns.rightText}
                  </div>
                </div>
              ) : (
                <div className="text-xs text-gray-500 dark:text-gray-400">
                  请选择左侧修改记录
                </div>
              )}
            </div>
            </>}
          </div>
          <DialogFooter className="pt-2">
            <Button
              type="button"
              size="sm"
              variant="ghost"
              className={cn(
                "h-7 min-w-[76px] rounded-full border px-2.5 text-[11px] font-medium shadow-none transition-colors",
                controller.selectedIsCurrent
                  ? "border-emerald-200 bg-emerald-50 text-emerald-700 hover:bg-emerald-50 disabled:opacity-100 dark:border-emerald-400/30 dark:bg-emerald-400/10 dark:text-emerald-200 dark:hover:bg-emerald-400/10"
                  : "border-indigo-200 bg-white text-indigo-700 hover:border-indigo-300 hover:bg-indigo-50 hover:text-indigo-800 disabled:opacity-55 dark:border-indigo-400/25 dark:bg-indigo-400/10 dark:text-indigo-200 dark:hover:border-indigo-300/45 dark:hover:bg-indigo-400/15 dark:hover:text-indigo-100",
                controller.restoringId &&
                  "border-indigo-300 bg-indigo-50 text-indigo-800 dark:border-indigo-300/45 dark:bg-indigo-400/15 dark:text-indigo-100"
              )}
              disabled={
                !controller.selectedItem ||
                controller.selectedIsCurrent ||
                Boolean(controller.restoringId)
              }
              onClick={() => void controller.restore(controller.selectedItem)}
            >
              {controller.restoringId ? (
                <Loader2 className="size-3 animate-spin" />
              ) : controller.selectedIsCurrent ? (
                <CheckCircle2 className="size-3" />
              ) : (
                <RefreshCcw className="size-3" />
              )}
              {controller.selectedIsCurrent ? "当前版本" : "切换版本"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
      <ConfirmDialog
        open={Boolean(controller.deleteTarget)}
        title="删除修改记录"
        description="确认删除这条修改记录？删除后仅移除该记录，不会改变当前节点内容。"
        confirmLabel="删除"
        loadingLabel="删除中..."
        loading={Boolean(controller.deletingId)}
        onCancel={() => controller.cancelDelete()}
        onConfirm={controller.deleteSelected}
      />
    </>
  )
}
