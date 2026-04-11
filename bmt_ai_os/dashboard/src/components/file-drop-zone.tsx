"use client";

import { useRef, useState, useCallback } from "react";
import { X, FileText, Image } from "lucide-react";

export interface AttachedFile {
  id: string;
  file: File;
  previewUrl: string | null;
  isImage: boolean;
}

interface FileDropZoneProps {
  children: React.ReactNode;
  attachments: AttachedFile[];
  onAttach: (files: AttachedFile[]) => void;
  onRemove: (id: string) => void;
}

function buildAttachedFile(file: File): AttachedFile {
  const isImage = file.type.startsWith("image/");
  const previewUrl = isImage ? URL.createObjectURL(file) : null;
  return {
    id: `${Date.now()}-${Math.random().toString(36).slice(2)}`,
    file,
    previewUrl,
    isImage,
  };
}

export function FileDropZone({
  children,
  attachments,
  onAttach,
  onRemove,
}: FileDropZoneProps) {
  const [isDragging, setIsDragging] = useState(false);
  const dragCounter = useRef(0);

  const handleFiles = useCallback(
    (files: FileList | File[]) => {
      const arr = Array.from(files);
      if (arr.length === 0) return;
      onAttach(arr.map(buildAttachedFile));
    },
    [onAttach]
  );

  function handleDragEnter(e: React.DragEvent) {
    e.preventDefault();
    dragCounter.current += 1;
    if (dragCounter.current === 1) setIsDragging(true);
  }

  function handleDragLeave(e: React.DragEvent) {
    e.preventDefault();
    dragCounter.current -= 1;
    if (dragCounter.current === 0) setIsDragging(false);
  }

  function handleDragOver(e: React.DragEvent) {
    e.preventDefault();
  }

  function handleDrop(e: React.DragEvent) {
    e.preventDefault();
    dragCounter.current = 0;
    setIsDragging(false);
    handleFiles(e.dataTransfer.files);
  }

  return (
    <div
      className="relative flex flex-col gap-2"
      onDragEnter={handleDragEnter}
      onDragLeave={handleDragLeave}
      onDragOver={handleDragOver}
      onDrop={handleDrop}
    >
      {isDragging && (
        <div
          className="pointer-events-none absolute inset-0 z-10 flex items-center justify-center rounded-lg border-2 border-dashed border-primary bg-primary/10"
          aria-hidden="true"
        >
          <span className="text-sm font-medium text-primary">
            Drop files here
          </span>
        </div>
      )}

      {attachments.length > 0 && (
        <div
          className="flex flex-wrap gap-2"
          role="list"
          aria-label="Attached files"
        >
          {attachments.map((a) => (
            <div
              key={a.id}
              role="listitem"
              className="relative flex items-center gap-1.5 rounded-md border border-border bg-muted px-2 py-1 text-xs"
            >
              {a.isImage && a.previewUrl ? (
                // eslint-disable-next-line @next/next/no-img-element
                <img
                  src={a.previewUrl}
                  alt={a.file.name}
                  className="size-8 rounded object-cover"
                />
              ) : (
                <FileText className="size-4 shrink-0 text-muted-foreground" />
              )}
              <span className="max-w-[120px] truncate text-foreground">
                {a.file.name}
              </span>
              <button
                type="button"
                onClick={() => onRemove(a.id)}
                aria-label={`Remove ${a.file.name}`}
                className="ml-0.5 rounded-full p-0.5 hover:bg-destructive/20 focus:outline-none focus:ring-1 focus:ring-ring"
              >
                <X className="size-3 text-muted-foreground" />
              </button>
            </div>
          ))}
        </div>
      )}

      {children}
    </div>
  );
}

/** Hook that converts a paste event's image items into AttachedFile objects. */
export function usePasteAttach(onAttach: (files: AttachedFile[]) => void) {
  return useCallback(
    (e: React.ClipboardEvent) => {
      const items = Array.from(e.clipboardData?.items ?? []);
      const imageFiles = items
        .filter((item) => item.kind === "file" && item.type.startsWith("image/"))
        .map((item) => item.getAsFile())
        .filter((f): f is File => f !== null);
      if (imageFiles.length > 0) {
        e.preventDefault();
        onAttach(imageFiles.map(buildAttachedFile));
      }
    },
    [onAttach]
  );
}

/** Serialises attachments to a short context string appended to the message. */
export function attachmentsToContext(attachments: AttachedFile[]): string {
  if (attachments.length === 0) return "";
  const lines = attachments.map((a) => `[attached file: ${a.file.name}]`);
  return "\n\n" + lines.join("\n");
}
