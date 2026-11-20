import { ArrowLeft, Shapes } from "lucide-react"

import { Button } from "@/components/ui/button"

interface NotFoundPageProps {
  onBack: () => void
}

export function NotFoundPage({ onBack }: NotFoundPageProps) {
  return (
    <main className="flex min-h-0 flex-1 items-center justify-center px-6">
      <div className="max-w-md text-center">
        <div className="mx-auto grid size-12 place-items-center rounded-2xl bg-indigo-500/10 text-indigo-600 dark:text-indigo-300">
          <Shapes className="size-5" />
        </div>
        <h1 className="mt-4 text-lg font-semibold text-gray-950 dark:text-gray-50">
          页面不存在
        </h1>
        <p className="mt-2 text-sm leading-relaxed text-gray-500 dark:text-gray-400">
          当前入口不在 ai-video 首轮页面蓝图内。
        </p>
        <Button className="mt-5 gap-1.5" onClick={onBack}>
          <ArrowLeft className="size-4" />
          返回项目大厅
        </Button>
      </div>
    </main>
  )
}
