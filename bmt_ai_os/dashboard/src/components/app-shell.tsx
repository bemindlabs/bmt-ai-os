import * as React from "react"

/**
 * AppShell wraps page content inside the main layout.
 * It provides a scrollable full-height container so individual pages
 * don't need to manage their own overflow.
 */
export function AppShell({ children }: { children: React.ReactNode }) {
  return (
    <div className="h-full overflow-y-auto p-6">
      {children}
    </div>
  )
}
