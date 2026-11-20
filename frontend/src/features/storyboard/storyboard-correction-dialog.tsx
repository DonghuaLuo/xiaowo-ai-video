import { useEffect, useRef, useState } from "react"
import { ImageIcon, Loader2 } from "lucide-react"
import { toast } from "sonner"
import type { MediaAsset } from "@/backend"
import { Button } from "@/components/ui/button"
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { useBackend } from "@/hooks/useBackend"
import { backendFailureMessage, errMsg } from "@/shared/backend-result"
import { localMediaFileSrc } from "@/shared/media"
import { resolveProjectMediaUrl } from "@/utils/style-thumbnails"

export type StoryboardReportScope = {
  projectId: string
  episodeId: string
  nodeId: string
  versionId: string
}

type CorrectionContext = {
  success: boolean
  reportId: string
  issues: Array<{ id: string; title: string; note: string; target: string }>
  assets: Array<{ id: string; name: string; available: boolean; media: MediaAsset | null }>
  baseMedia: MediaAsset
  modelName: string
  modelError: string
  maxReferenceImages: number | null
}

function ReferenceImage({ projectId, media, name }: { projectId: string; media: MediaAsset | null; name: string }) {
  const [src, setSrc] = useState("")
  useEffect(() => {
    let cancelled = false
    setSrc("")
    void resolveProjectMediaUrl(projectId, media).then((url) => {
      if (!cancelled) setSrc(localMediaFileSrc(media) || url || "")
    }).catch(() => { if (!cancelled) setSrc("") })
    return () => { cancelled = true }
  }, [projectId, media])
  return <div className="flex aspect-video items-center justify-center overflow-hidden rounded bg-gray-100 dark:bg-white/5">
    {src ? <img src={src} alt={name} className="size-full object-contain" onError={() => setSrc("")} /> : <ImageIcon className="size-6 text-gray-400" />}
  </div>
}

export function StoryboardCorrectionDialog({ scope, onClose, onSubmitted }: {
  scope: StoryboardReportScope
  onClose: () => void
  onSubmitted: () => void
}) {
  const { callBackend } = useBackend()
  const [context, setContext] = useState<CorrectionContext | null>(null)
  const [error, setError] = useState("")
  const [issueIds, setIssueIds] = useState<string[]>([])
  const [assetIds, setAssetIds] = useState<string[]>([])
  const [supplement, setSupplement] = useState("")
  const [submitting, setSubmitting] = useState(false)
  const submittingRef = useRef(false)
  const alive = useRef(true)
  const { projectId, episodeId, nodeId, versionId } = scope
  useEffect(() => {
    alive.current = true
    let cancelled = false
    void callBackend<CorrectionContext>("get_storyboard_correction_context", { projectId, episodeId, nodeId, versionId }).then((result) => {
      if (cancelled) return
      if (result.success === false) throw new Error(backendFailureMessage(result, "无法读取修正信息"))
      setContext(result)
      setIssueIds(result.issues.map((item) => item.id))
    }).catch((reason) => { if (!cancelled) setError(errMsg(reason, "无法读取修正信息")) })
    return () => { cancelled = true; alive.current = false }
  }, [callBackend, projectId, episodeId, nodeId, versionId])
  const referenceCount = 1 + assetIds.length
  const overLimit = context?.maxReferenceImages != null && referenceCount > context.maxReferenceImages
  const toggle = (items: string[], id: string) => items.includes(id) ? items.filter((item) => item !== id) : [...items, id]
  const submit = async () => {
    if (!context || submittingRef.current || overLimit || !issueIds.length || context.modelError) return
    submittingRef.current = true
    setSubmitting(true)
    try {
      const result = await callBackend<{ success: boolean }>("start_storyboard_correction", {
        projectId, episodeId, nodeId, versionId, reportId: context.reportId, issueIds, assetIds, supplement,
      })
      if (result.success === false) throw new Error(backendFailureMessage(result, "无法启动修正"))
      if (alive.current) {
        toast.success("已开始修正，完成后将生成新版本")
        onSubmitted()
      }
    } catch (reason) {
      if (alive.current) setError(errMsg(reason, "无法启动修正"))
    } finally {
      submittingRef.current = false
      if (alive.current) setSubmitting(false)
    }
  }
  return <Dialog open onOpenChange={(open) => { if (!open && !submitting) onClose() }}>
    <DialogContent overlayClassName="!z-[390]" className="!z-[400] flex max-h-[88dvh] !w-[min(860px,calc(100vw-2rem))] !max-w-none flex-col gap-4 overflow-hidden" showCloseButton={!submitting}
      onPointerDownOutside={(event) => event.preventDefault()}>
      <DialogHeader>
        <DialogTitle>修正分镜图</DialogTitle>
        <DialogDescription>以当前查看的分镜图为原图，修正选中的问题。生成新版本并保留原图。</DialogDescription>
      </DialogHeader>
      <div className="min-h-0 space-y-4 overflow-y-auto overscroll-contain pr-1 text-sm">
        {!context && !error && <p role="status" className="flex items-center gap-2 py-6"><Loader2 className="size-4 animate-spin" />正在读取报告与关联资产……</p>}
        {error && <p role="alert" className="rounded-md bg-red-50 p-3 text-red-700 dark:bg-red-950/30 dark:text-red-300">{error}</p>}
        {context && <>
          <div className="flex items-center gap-3 rounded-md border p-2">
            <div className="w-32 shrink-0"><ReferenceImage projectId={projectId} media={context.baseMedia} name="待修正分镜图" /></div>
            <div><p className="font-medium">待修正原图 · 固定发送</p><p className="mt-1 text-xs text-muted-foreground">图片模型：{context.modelName}</p></div>
          </div>
          <fieldset disabled={submitting} className="space-y-2">
            <legend className="mb-2 font-medium">本次修正问题</legend>
            {context.issues.map((issue) => <label key={issue.id} className="flex cursor-pointer items-start gap-2 rounded-md border border-red-200/70 p-3 dark:border-red-900/60">
              <input type="checkbox" checked={issueIds.includes(issue.id)} onChange={() => setIssueIds((items) => toggle(items, issue.id))} className="mt-1 shrink-0 accent-red-600" />
              <span className="min-w-0"><span className="font-medium text-red-700 dark:text-red-400">{issue.title}</span>
                {issue.note && <span className="mt-1 block whitespace-pre-wrap break-words text-xs">{issue.note}</span>}
                {issue.target && <span className="mt-1 block whitespace-pre-wrap break-words text-xs text-muted-foreground">计划要求：{issue.target}</span>}
              </span>
            </label>)}
            <p className="text-xs text-muted-foreground">可以取消勾选误判的问题。</p>
          </fieldset>
          <label className="block space-y-2"><span className="font-medium">补充要求 <span className="text-xs font-normal text-muted-foreground">（可选）</span></span>
            <textarea value={supplement} onChange={(event) => setSupplement(event.target.value)} disabled={submitting} maxLength={10000} rows={3} className="block w-full resize-y rounded-md border bg-transparent px-3 py-2 text-sm outline-none focus:ring-1 focus:ring-ring" placeholder="说明修正细节；如果要改变剧情或镜头目标，请先修改分镜脚本。" />
          </label>
          <fieldset disabled={submitting}>
            <legend className="mb-2 font-medium">附加资产参考图 <span className="text-xs font-normal text-muted-foreground">（按需勾选）</span></legend>
            {context.assets.length ? <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
              {context.assets.map((asset) => <label key={asset.id} className={`rounded-md border p-2 ${asset.available ? "cursor-pointer" : "opacity-50"}`}>
                <ReferenceImage projectId={projectId} media={asset.media} name={asset.name} />
                <span className="mt-2 flex items-start gap-1.5 text-xs"><input type="checkbox" disabled={!asset.available} checked={assetIds.includes(asset.id)} onChange={() => setAssetIds((items) => toggle(items, asset.id))} className="mt-0.5" /><span className="break-words">{asset.name}{!asset.available && <span className="block text-muted-foreground">暂无可用图片</span>}</span></span>
              </label>)}
            </div> : <p className="text-xs text-muted-foreground">这条工作链暂无关联的资产图。</p>}
          </fieldset>
          {context.modelError && <p role="alert" className="text-red-600 dark:text-red-400">{context.modelError}</p>}
        </>}
      </div>
      <DialogFooter className="items-center border-t pt-3 sm:justify-between">
        <p className={`text-xs ${overLimit ? "text-red-600 dark:text-red-400" : "text-muted-foreground"}`}>
          原图 1 张＋资产 {assetIds.length} 张{context?.maxReferenceImages != null && `，模型上限 ${context.maxReferenceImages} 张`}{overLimit && "，请减少勾选"}
        </p>
        <div className="flex gap-2"><Button variant="outline" onClick={onClose} disabled={submitting}>取消</Button>
          <Button onClick={() => void submit()} disabled={!context || submitting || !issueIds.length || overLimit || Boolean(context.modelError)}>{submitting && <Loader2 className="size-4 animate-spin" />}生成修正版</Button></div>
      </DialogFooter>
    </DialogContent>
  </Dialog>
}
