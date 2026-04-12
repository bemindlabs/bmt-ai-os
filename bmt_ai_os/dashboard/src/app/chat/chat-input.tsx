"use client";

import { useRef } from "react";
import { Button } from "@/components/ui/button";
import { SlashCommandMenu } from "@/components/slash-command-menu";
import {
  FileDropZone,
  usePasteAttach,
  type AttachedFile,
} from "@/components/file-drop-zone";
import { VoiceInput } from "@/components/voice-input";
import { Send, Square, Paperclip } from "lucide-react";
import { filterCommands, type SlashCommand } from "@/lib/commands";

// ─── Props ────────────────────────────────────────────────────────────────────

interface ChatInputProps {
  input: string;
  isBusy: boolean;
  attachments: AttachedFile[];
  slashQuery: string | null;
  slashIndex: number;
  textareaRef: React.RefObject<HTMLTextAreaElement | null>;
  onInputChange: (e: React.ChangeEvent<HTMLTextAreaElement>) => void;
  onKeyDown: (e: React.KeyboardEvent<HTMLTextAreaElement>) => void;
  onAttach: (files: AttachedFile[]) => void;
  onRemoveAttachment: (id: string) => void;
  onSlashSelect: (cmd: SlashCommand) => void;
  onSlashIndexChange: (index: number) => void;
  onVoiceTranscript: (text: string) => void;
  onSend: () => void;
  onStop: () => void;
}

// ─── ChatInput ────────────────────────────────────────────────────────────────

export function ChatInput({
  input,
  isBusy,
  attachments,
  slashQuery,
  slashIndex,
  textareaRef,
  onInputChange,
  onKeyDown,
  onAttach,
  onRemoveAttachment,
  onSlashSelect,
  onSlashIndexChange,
  onVoiceTranscript,
  onSend,
  onStop,
}: ChatInputProps) {
  const fileInputRef = useRef<HTMLInputElement>(null);
  const slashCommands = slashQuery !== null ? filterCommands(slashQuery) : [];

  const handlePaste = usePasteAttach(onAttach);

  function handlePaperclipClick() {
    fileInputRef.current?.click();
  }

  function handleFileInputChange(e: React.ChangeEvent<HTMLInputElement>) {
    if (e.target.files && e.target.files.length > 0) {
      const built: AttachedFile[] = Array.from(e.target.files).map((f) => ({
        id: `${Date.now()}-${Math.random().toString(36).slice(2)}`,
        file: f,
        previewUrl: f.type.startsWith("image/")
          ? URL.createObjectURL(f)
          : null,
        isImage: f.type.startsWith("image/"),
      }));
      onAttach(built);
      e.target.value = "";
    }
  }

  return (
    <div className="flex flex-col gap-2">
      {/* Slash command menu (BMTOS-103) */}
      <div className="relative">
        {slashQuery !== null && slashCommands.length > 0 && (
          <SlashCommandMenu
            commands={slashCommands}
            activeIndex={slashIndex}
            onSelect={onSlashSelect}
            onActiveIndexChange={onSlashIndexChange}
          />
        )}

        {/* FileDropZone wraps the textarea (BMTOS-104) */}
        <FileDropZone
          attachments={attachments}
          onAttach={onAttach}
          onRemove={onRemoveAttachment}
        >
          <textarea
            ref={textareaRef}
            value={input}
            onChange={onInputChange}
            onKeyDown={onKeyDown}
            onPaste={handlePaste}
            placeholder="Type a message or /command… (Enter to send, Shift+Enter for newline)"
            rows={2}
            disabled={isBusy}
            className="w-full resize-none rounded-lg border border-input bg-background px-3 py-2 text-sm placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-ring/50 disabled:opacity-50"
          />
        </FileDropZone>
      </div>

      {/* Action row */}
      <div className="flex items-center gap-2 justify-end">
        {/* Hidden file input (BMTOS-104) */}
        <input
          ref={fileInputRef}
          type="file"
          multiple
          className="hidden"
          onChange={handleFileInputChange}
          aria-hidden="true"
        />

        {/* Paperclip button */}
        <Button
          type="button"
          variant="outline"
          size="icon"
          onClick={handlePaperclipClick}
          disabled={isBusy}
          aria-label="Attach file"
          title="Attach file"
        >
          <Paperclip className="size-4" />
        </Button>

        {/* Voice input (BMTOS-104) */}
        <VoiceInput onTranscript={onVoiceTranscript} disabled={isBusy} />

        {/* Stop / Send button */}
        {isBusy ? (
          <Button
            type="button"
            variant="destructive"
            size="icon"
            onClick={onStop}
            aria-label="Stop generation"
            title="Stop generation"
          >
            <Square className="size-4 fill-current" />
          </Button>
        ) : (
          <Button
            onClick={onSend}
            disabled={!input.trim() && attachments.length === 0}
            size="icon"
            aria-label="Send message"
          >
            <Send className="size-4" />
          </Button>
        )}
      </div>
    </div>
  );
}
