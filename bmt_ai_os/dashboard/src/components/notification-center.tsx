"use client";

import {
  createContext,
  use,
  useCallback,
  useEffect,
  useRef,
  useState,
} from "react";
import { Bell, X, Info, CheckCircle, AlertTriangle, AlertCircle } from "lucide-react";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";

// ---------- Types ----------

export type NotificationType = "info" | "success" | "warning" | "error";

export interface Notification {
  id: string;
  type: NotificationType;
  title: string;
  message?: string;
  timestamp: Date;
  read: boolean;
}

interface NotificationContextValue {
  notifications: Notification[];
  unreadCount: number;
  notify: (
    type: NotificationType,
    title: string,
    message?: string
  ) => void;
  markAllRead: () => void;
  dismiss: (id: string) => void;
  clearAll: () => void;
}

// ---------- Context ----------

const NotificationContext = createContext<NotificationContextValue>({
  notifications: [],
  unreadCount: 0,
  notify: () => {},
  markAllRead: () => {},
  dismiss: () => {},
  clearAll: () => {},
});

export function useNotifications(): NotificationContextValue {
  return use(NotificationContext);
}

// ---------- Provider ----------

const MAX_NOTIFICATIONS = 50;
// How long (ms) before a toast auto-dismisses
const TOAST_DURATION = 5000;

interface ToastItem {
  id: string;
  type: NotificationType;
  title: string;
  message?: string;
  removing: boolean;
}

export function NotificationProvider({
  children,
}: {
  children: React.ReactNode;
}) {
  const [notifications, setNotifications] = useState<Notification[]>([]);
  const [toasts, setToasts] = useState<ToastItem[]>([]);
  const toastTimers = useRef<Map<string, ReturnType<typeof setTimeout>>>(
    new Map()
  );

  const removeToast = useCallback((id: string) => {
    setToasts((prev) =>
      prev.map((t) => (t.id === id ? { ...t, removing: true } : t))
    );
    setTimeout(() => {
      setToasts((prev) => prev.filter((t) => t.id !== id));
    }, 300);
  }, []);

  const notify = useCallback(
    (type: NotificationType, title: string, message?: string) => {
      const id = `${Date.now()}-${Math.random().toString(36).slice(2, 7)}`;

      // Add to persistent list
      setNotifications((prev) => {
        const next: Notification[] = [
          { id, type, title, message, timestamp: new Date(), read: false },
          ...prev,
        ];
        return next.slice(0, MAX_NOTIFICATIONS);
      });

      // Show toast
      setToasts((prev) => [...prev, { id, type, title, message, removing: false }]);

      // Auto-dismiss toast
      const timer = setTimeout(() => {
        removeToast(id);
        toastTimers.current.delete(id);
      }, TOAST_DURATION);
      toastTimers.current.set(id, timer);
    },
    [removeToast]
  );

  const dismiss = useCallback(
    (id: string) => {
      setNotifications((prev) => prev.filter((n) => n.id !== id));
      const timer = toastTimers.current.get(id);
      if (timer) {
        clearTimeout(timer);
        toastTimers.current.delete(id);
      }
      removeToast(id);
    },
    [removeToast]
  );

  const markAllRead = useCallback(() => {
    setNotifications((prev) => prev.map((n) => ({ ...n, read: true })));
  }, []);

  const clearAll = useCallback(() => {
    setNotifications([]);
    toastTimers.current.forEach((t) => clearTimeout(t));
    toastTimers.current.clear();
    setToasts([]);
  }, []);

  // Cleanup timers on unmount
  useEffect(() => {
    const timers = toastTimers.current;
    return () => timers.forEach((t) => clearTimeout(t));
  }, []);

  const unreadCount = notifications.filter((n) => !n.read).length;

  return (
    <NotificationContext
      value={{ notifications, unreadCount, notify, markAllRead, dismiss, clearAll }}
    >
      {children}
      <ToastRegion toasts={toasts} onDismiss={removeToast} />
    </NotificationContext>
  );
}

// ---------- Toast Region ----------

const typeConfig: Record<
  NotificationType,
  { icon: React.ElementType; colorClass: string }
> = {
  info: { icon: Info, colorClass: "text-blue-400" },
  success: { icon: CheckCircle, colorClass: "text-green-400" },
  warning: { icon: AlertTriangle, colorClass: "text-yellow-400" },
  error: { icon: AlertCircle, colorClass: "text-red-400" },
};

function ToastRegion({
  toasts,
  onDismiss,
}: {
  toasts: ToastItem[];
  onDismiss: (id: string) => void;
}) {
  if (toasts.length === 0) return null;

  return (
    <div
      role="region"
      aria-label="Notifications"
      aria-live="polite"
      className="fixed bottom-4 right-4 z-50 flex flex-col gap-2 w-80"
    >
      {toasts.map((toast) => {
        const { icon: Icon, colorClass } = typeConfig[toast.type];
        return (
          <div
            key={toast.id}
            role="alert"
            className={cn(
              "flex items-start gap-3 rounded-lg border border-border bg-card p-3.5 shadow-lg",
              "transition-all duration-300",
              toast.removing
                ? "opacity-0 translate-x-2"
                : "opacity-100 translate-x-0"
            )}
          >
            <Icon className={cn("mt-0.5 size-4 shrink-0", colorClass)} />
            <div className="min-w-0 flex-1">
              <p className="text-sm font-medium text-card-foreground">
                {toast.title}
              </p>
              {toast.message && (
                <p className="mt-0.5 text-xs text-muted-foreground">
                  {toast.message}
                </p>
              )}
            </div>
            <button
              onClick={() => onDismiss(toast.id)}
              aria-label="Dismiss notification"
              className="shrink-0 text-muted-foreground hover:text-foreground transition-colors"
            >
              <X className="size-3.5" />
            </button>
          </div>
        );
      })}
    </div>
  );
}

// ---------- Bell button + Dropdown ----------

export function NotificationCenter() {
  const { notifications, unreadCount, markAllRead, dismiss, clearAll } =
    useNotifications();
  const [open, setOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);

  // Close on outside click
  useEffect(() => {
    if (!open) return;
    function handlePointerDown(e: PointerEvent) {
      if (
        containerRef.current &&
        !containerRef.current.contains(e.target as Node)
      ) {
        setOpen(false);
      }
    }
    document.addEventListener("pointerdown", handlePointerDown);
    return () => document.removeEventListener("pointerdown", handlePointerDown);
  }, [open]);

  // Close on Escape
  useEffect(() => {
    if (!open) return;
    function handleKey(e: KeyboardEvent) {
      if (e.key === "Escape") setOpen(false);
    }
    document.addEventListener("keydown", handleKey);
    return () => document.removeEventListener("keydown", handleKey);
  }, [open]);

  function handleToggle() {
    if (!open && unreadCount > 0) markAllRead();
    setOpen((v) => !v);
  }

  return (
    <div ref={containerRef} className="relative">
      {/* Bell button */}
      <Button
        variant="ghost"
        size="icon"
        onClick={handleToggle}
        aria-label={
          unreadCount > 0
            ? `${unreadCount} unread notification${unreadCount > 1 ? "s" : ""}`
            : "Notifications"
        }
        aria-haspopup="true"
        aria-expanded={open}
        className="relative"
      >
        <Bell className="size-4" />
        {unreadCount > 0 && (
          <span
            aria-hidden="true"
            className="absolute -right-0.5 -top-0.5 flex size-4 items-center justify-center rounded-full bg-destructive text-[10px] font-bold text-white"
          >
            {unreadCount > 9 ? "9+" : unreadCount}
          </span>
        )}
      </Button>

      {/* Dropdown */}
      {open && (
        <div
          role="dialog"
          aria-label="Notification center"
          className={cn(
            "absolute right-0 top-full z-40 mt-2 flex w-80 flex-col rounded-lg border border-border bg-popover shadow-xl",
            "animate-in fade-in-0 slide-in-from-top-2 duration-150"
          )}
        >
          {/* Header */}
          <div className="flex items-center justify-between border-b border-border px-4 py-3">
            <span className="text-sm font-semibold text-popover-foreground">
              Notifications
            </span>
            {notifications.length > 0 && (
              <button
                onClick={clearAll}
                className="text-xs text-muted-foreground hover:text-foreground transition-colors"
              >
                Clear all
              </button>
            )}
          </div>

          {/* List */}
          <div
            className="max-h-80 overflow-y-auto"
            role="list"
            aria-label="Notification list"
          >
            {notifications.length === 0 ? (
              <div className="flex flex-col items-center gap-2 px-4 py-8 text-center">
                <Bell className="size-6 text-muted-foreground/40" />
                <p className="text-sm text-muted-foreground">
                  No notifications yet
                </p>
              </div>
            ) : (
              notifications.map((n) => {
                const { icon: Icon, colorClass } = typeConfig[n.type];
                return (
                  <div
                    key={n.id}
                    role="listitem"
                    className={cn(
                      "flex items-start gap-3 px-4 py-3 border-b border-border/50 last:border-0",
                      "transition-colors hover:bg-muted/30",
                      !n.read && "bg-muted/20"
                    )}
                  >
                    <Icon
                      className={cn("mt-0.5 size-4 shrink-0", colorClass)}
                    />
                    <div className="min-w-0 flex-1">
                      <p className="text-sm font-medium text-popover-foreground">
                        {n.title}
                      </p>
                      {n.message && (
                        <p className="mt-0.5 text-xs text-muted-foreground">
                          {n.message}
                        </p>
                      )}
                      <time
                        dateTime={n.timestamp.toISOString()}
                        className="mt-1 block text-[10px] text-muted-foreground/70"
                      >
                        {formatRelativeTime(n.timestamp)}
                      </time>
                    </div>
                    <button
                      onClick={() => dismiss(n.id)}
                      aria-label="Dismiss notification"
                      className="shrink-0 text-muted-foreground hover:text-foreground transition-colors"
                    >
                      <X className="size-3.5" />
                    </button>
                  </div>
                );
              })
            )}
          </div>
        </div>
      )}
    </div>
  );
}

// ---------- Helpers ----------

function formatRelativeTime(date: Date): string {
  const diffMs = Date.now() - date.getTime();
  const diffSec = Math.floor(diffMs / 1000);
  if (diffSec < 60) return "just now";
  const diffMin = Math.floor(diffSec / 60);
  if (diffMin < 60) return `${diffMin}m ago`;
  const diffHr = Math.floor(diffMin / 60);
  if (diffHr < 24) return `${diffHr}h ago`;
  return date.toLocaleDateString();
}
