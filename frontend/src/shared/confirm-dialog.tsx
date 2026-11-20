import { Loader2 } from "lucide-react"

import {
  AlertDialog,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog"
import { Button } from "@/components/ui/button"

export function ConfirmDialog({
  open,
  title,
  description,
  confirmLabel,
  loadingLabel,
  loading,
  onConfirm,
  onCancel,
  overlayClassName,
  contentClassName,
}: {
  open: boolean
  title: string
  description?: string
  confirmLabel: string
  loadingLabel: string
  loading: boolean
  onConfirm: () => void | Promise<void>
  onCancel: () => void
  overlayClassName?: string
  contentClassName?: string
}) {
  return (
    <AlertDialog
      open={open}
      onOpenChange={(nextOpen) => {
        if (!nextOpen && !loading) onCancel()
      }}
    >
      <AlertDialogContent
        overlayClassName={overlayClassName}
        className={`border-gray-200/70 bg-white text-gray-950 dark:border-white/10 dark:bg-[#202025] dark:text-gray-50 ${contentClassName ?? ""}`}
      >
        <AlertDialogHeader>
          <AlertDialogTitle>{title}</AlertDialogTitle>
          <AlertDialogDescription className="text-gray-500 dark:text-gray-400">
            {description ?? "请确认是否继续。"}
          </AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <Button
            type="button"
            variant="outline"
            disabled={loading}
            onClick={onCancel}
          >
            取消
          </Button>
          <Button
            type="button"
            variant="destructive"
            disabled={loading}
            onClick={() => void onConfirm()}
          >
            {loading ? (
              <Loader2
                className="h-3.5 w-3.5 motion-safe:animate-spin"
                aria-hidden
              />
            ) : null}
            {loading ? loadingLabel : confirmLabel}
          </Button>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  )
}
