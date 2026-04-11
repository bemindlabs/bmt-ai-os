import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import "./globals.css";
import { SidebarNav } from "@/components/sidebar-nav";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "BMT AI OS",
  description: "BMT AI OS — On-device AI operating system dashboard",
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html
      lang="en"
      className={`${geistSans.variable} ${geistMono.variable} dark h-full antialiased`}
    >
      <body className="flex h-full bg-background text-foreground">
        {/* Sidebar */}
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

        {/* Main area */}
        <div className="flex min-w-0 flex-1 flex-col">
          {/* Top header */}
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

          {/* Page content */}
          <main className="flex-1 overflow-y-auto p-6">{children}</main>
        </div>
      </body>
    </html>
  );
}
