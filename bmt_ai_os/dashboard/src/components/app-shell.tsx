"use client";

import { usePathname } from "next/navigation";
import { SidebarNav } from "@/components/sidebar-nav";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";

const BARE_PATHS = ["/login"];

export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();

  if (BARE_PATHS.some((p) => pathname.startsWith(p))) {
    return <>{children}</>;
  }

  return (
    <>
      <aside className="flex w-56 shrink-0 flex-col border-r border-sidebar-border bg-sidebar">
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

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex h-14 shrink-0 items-center justify-between border-b border-border px-6">
          <span className="text-sm font-medium text-muted-foreground">
            BMT AI Operating System
          </span>
          <div className="flex items-center gap-2">
            <span className="size-2 rounded-full bg-green-500" />
            <Badge variant="outline" className="text-xs">
              Online
            </Badge>
          </div>
        </header>
        <main className="flex-1 overflow-y-auto p-6">{children}</main>
      </div>
    </>
  );
}
