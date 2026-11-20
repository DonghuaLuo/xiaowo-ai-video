import { StrictMode, useEffect, useState } from "react"
import { createRoot } from "react-dom/client"
import { PluginSDK } from "xiaowo-sdk"
import { Toaster } from "@/components/ui/sonner"
import App from "./App.tsx"
import "./styles/globals.css"

function Root() {
  const [isDark, setIsDark] = useState(() =>
    document.documentElement.classList.contains("dark")
  )

  useEffect(() => {
    void PluginSDK.waitReady()
      .then(() => PluginSDK.showWindow())
      .catch((error) => {
        console.error("显示插件窗口失败:", error)
      })
    const observer = new MutationObserver(() => {
      setIsDark(document.documentElement.classList.contains("dark"))
    })
    observer.observe(document.documentElement, { attributeFilter: ["class"] })
    return () => observer.disconnect()
  }, [])

  return (
    <StrictMode>
      <App />
      <Toaster theme={isDark ? "dark" : "light"} />
    </StrictMode>
  )
}

createRoot(document.getElementById("root")!).render(<Root />)
