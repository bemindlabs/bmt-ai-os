"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Mic, MicOff } from "lucide-react";
import { Button } from "@/components/ui/button";

// Minimal type declarations for the Web Speech API (not in all lib.dom.d.ts versions).
interface SpeechRecognitionResultItem {
  readonly transcript: string;
}

interface SpeechRecognitionResultEntry {
  readonly [index: number]: SpeechRecognitionResultItem;
}

interface SpeechRecognitionEventData {
  readonly resultIndex: number;
  readonly results: SpeechRecognitionResultEntry[];
}

interface SpeechRecognitionInstance {
  continuous: boolean;
  interimResults: boolean;
  lang: string;
  onresult: ((event: SpeechRecognitionEventData) => void) | null;
  onerror: (() => void) | null;
  onend: (() => void) | null;
  start(): void;
  stop(): void;
}

type SpeechRecognitionCtor = new () => SpeechRecognitionInstance;

declare global {
  interface Window {
    SpeechRecognition?: SpeechRecognitionCtor;
    webkitSpeechRecognition?: SpeechRecognitionCtor;
  }
}

interface VoiceInputProps {
  onTranscript: (text: string) => void;
  disabled?: boolean;
}

export function VoiceInput({ onTranscript, disabled = false }: VoiceInputProps) {
  const [isRecording, setIsRecording] = useState(false);
  const [isSupported, setIsSupported] = useState(false);
  const recognitionRef = useRef<SpeechRecognitionInstance | null>(null);

  useEffect(() => {
    const SpeechRecognitionCtor =
      typeof window !== "undefined"
        ? window.SpeechRecognition ?? window.webkitSpeechRecognition
        : null;
    setIsSupported(SpeechRecognitionCtor != null);
  }, []);

  const stop = useCallback(() => {
    recognitionRef.current?.stop();
    recognitionRef.current = null;
    setIsRecording(false);
  }, []);

  const start = useCallback(() => {
    const SpeechRecognitionCtor =
      window.SpeechRecognition ?? window.webkitSpeechRecognition;
    if (!SpeechRecognitionCtor) return;

    const recognition = new SpeechRecognitionCtor();
    recognition.continuous = true;
    recognition.interimResults = false;
    recognition.lang = "en-US";

    recognition.onresult = (event: SpeechRecognitionEventData) => {
      const transcript = Array.from(event.results)
        .slice(event.resultIndex)
        .map((r) => r[0].transcript)
        .join("");
      if (transcript) onTranscript(transcript);
    };

    recognition.onerror = () => stop();
    recognition.onend = () => stop();

    recognitionRef.current = recognition;
    recognition.start();
    setIsRecording(true);
  }, [onTranscript, stop]);

  // Clean up on unmount.
  useEffect(() => () => { recognitionRef.current?.stop(); }, []);

  if (!isSupported) return null;

  function handleToggle() {
    if (isRecording) {
      stop();
    } else {
      start();
    }
  }

  return (
    <div className="relative inline-flex items-center">
      {isRecording && (
        <span
          className="absolute -top-1 -right-1 size-2.5 rounded-full bg-destructive animate-pulse"
          aria-hidden="true"
        />
      )}
      <Button
        type="button"
        variant={isRecording ? "destructive" : "outline"}
        size="icon"
        onClick={handleToggle}
        disabled={disabled}
        aria-label={isRecording ? "Stop recording" : "Start voice input"}
        aria-pressed={isRecording}
      >
        {isRecording ? (
          <MicOff className="size-4" />
        ) : (
          <Mic className="size-4" />
        )}
      </Button>
    </div>
  );
}
