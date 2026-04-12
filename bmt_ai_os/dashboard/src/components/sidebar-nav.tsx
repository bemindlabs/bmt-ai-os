"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import {
  LayoutDashboard,
  BrainCircuit,
  BrainCog,
  Code2,
  Database,
  MessageSquare,
  Settings,
  ScrollText,
  LogOut,
  HardDrive,
  Server,
  Terminal,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { useAuth } from "@/components/auth-provider";
import { logout } from "@/lib/auth";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";

const navItems = [
  { href: "/", label: "Overview", icon: LayoutDashboard },
  { href: "/models", label: "Models", icon: BrainCircuit },
  { href: "/chat", label: "Chat", icon: MessageSquare },
  { href: "/editor", label: "Editor", icon: Code2 },
  { href: "/fleet", label: "Fleet", icon: Server },
  { href: "/training", label: "Training", icon: BrainCog },
  { href: "/knowledge", label: "Knowledge", icon: Database },
  { href: "/agents", label: "Agents", icon: BrainCog },
  { href: "/image-builder", label: "Image Builder", icon: HardDrive },
  { href: "/terminal", label: "Terminal", icon: Terminal },
  { href: "/logs", label: "Logs", icon: ScrollText },
  { href: "/settings", label: "Settings", icon: Settings },
];

export function SidebarNav() {
  const pathname = usePathname();
  const router = useRouter();
  const { user } = useAuth();

  async function handleLogout() {
    await logout();
    router.replace("/login");
  }

  return (
    <div className="flex flex-1 flex-col">
      <nav className="flex flex-col gap-1 px-2 py-4">
        {navItems.map(({ href, label, icon: Icon }) => {
          const active = href === "/" ? pathname === "/" : pathname.startsWith(href);
          return (
            <Link
              key={href}
              href={href}
              className={cn(
                "flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition-colors",
                active
                  ? "bg-sidebar-accent text-sidebar-accent-foreground"
                  : "text-sidebar-foreground/70 hover:bg-sidebar-accent/50 hover:text-sidebar-foreground"
              )}
            >
              <Icon className="size-4 shrink-0" />
              {label}
            </Link>
          );
        })}
      </nav>

      {/* Push user section to bottom */}
      <div className="mt-auto">
        <Separator />
        {user && (
          <div className="flex items-center justify-between px-3 py-3">
            <div className="flex min-w-0 flex-col gap-0.5">
              <span className="truncate text-xs font-medium text-sidebar-foreground">
                {user.username}
              </span>
              <Badge
                variant="secondary"
                className="w-fit text-[10px] py-0 px-1.5 capitalize"
              >
                {user.role}
              </Badge>
            </div>
            <Button
              variant="ghost"
              size="icon-sm"
              onClick={handleLogout}
              aria-label="Sign out"
              className="shrink-0 text-sidebar-foreground/70 hover:text-sidebar-foreground"
            >
              <LogOut className="size-4" />
            </Button>
          </div>
        )}
      </div>
    </div>
  );
}
