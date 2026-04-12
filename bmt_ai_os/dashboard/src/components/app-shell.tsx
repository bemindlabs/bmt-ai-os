"use client";

import * as React from "react";
import { usePathname } from "next/navigation";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";
import { SidebarNav } from "@/components/sidebar-nav";

const STANDALONE_ROUTES = ["/login"];

export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();

  if (STANDALONE_ROUTES.includes(pathname)) {
    return <>{children}</>;
  }

  return (
    <>
      {/* Navigation sidebar */}
      <aside className="flex w-56 shrink-0 flex-col border-r border-sidebar-border bg-sidebar">
        {/* Brand */}
        <div className="flex h-14 items-center gap-2.5 px-4">
          <span className="text-sm font-semibold tracking-tight text-sidebar-foreground">
            BMT AI OS
          </span>
          <Badge variant="secondary" className="text-[10px] py-0 px-1.5">
            v0.1
          </Badge>
        </div>

        <Separator />

        <SidebarNav />
      </aside>

      {/* Right of nav: header + workspace */}
      <div className="flex min-w-0 flex-1 flex-col overflow-hidden">
        {/* Top header */}
        <header className="flex h-14 shrink-0 items-center justify-between border-b border-border px-6">
          <span className="text-sm font-medium text-muted-foreground">
            BMT AI Operating System
          </span>
          <div className="flex items-center gap-2">
            <span className="size-2 rounded-full bg-green-500" aria-hidden="true" />
            <Badge variant="outline" className="text-xs">
              Online
            </Badge>
          </div>
        </header>

        {/* Workspace fills remaining height */}
        <main className="h-full min-h-0 flex-1 overflow-y-auto p-6">
          {children}
        </main>
      </div>
    </>
  );
}
