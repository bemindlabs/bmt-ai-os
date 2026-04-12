"use client";

import { useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Prism as SyntaxHighlighter } from "react-syntax-highlighter";
import { oneDark } from "react-syntax-highlighter/dist/esm/styles/prism";
import { Copy, Check } from "lucide-react";

// ─── CopyButton ───────────────────────────────────────────────────────────────

export function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);

  async function handleCopy() {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // clipboard API unavailable — silently fail
    }
  }

  return (
    <button
      onClick={handleCopy}
      className="absolute right-2 top-2 flex items-center gap-1 rounded bg-zinc-700 px-1.5 py-0.5 text-xs text-zinc-200 opacity-0 transition-opacity group-hover/code:opacity-100 hover:bg-zinc-600"
      aria-label="Copy code"
      type="button"
    >
      {copied ? (
        <>
          <Check className="size-3" />
          Copied
        </>
      ) : (
        <>
          <Copy className="size-3" />
          Copy
        </>
      )}
    </button>
  );
}

// ─── MarkdownContent ──────────────────────────────────────────────────────────

interface MarkdownContentProps {
  content: string;
}

export function MarkdownContent({ content }: MarkdownContentProps) {
  return (
    <ReactMarkdown
      remarkPlugins={[remarkGfm]}
      components={{
        h1: ({ children }) => (
          <h1 className="mb-2 text-base font-bold">{children}</h1>
        ),
        h2: ({ children }) => (
          <h2 className="mb-1.5 text-sm font-bold">{children}</h2>
        ),
        h3: ({ children }) => (
          <h3 className="mb-1 text-sm font-semibold">{children}</h3>
        ),
        p: ({ children }) => (
          <p className="mb-2 last:mb-0 leading-relaxed">{children}</p>
        ),
        code: ({ className, children, ...props }) => {
          return (
            <code
              className="rounded bg-black/20 px-1 py-0.5 font-mono text-[0.8em]"
              {...props}
            >
              {children}
            </code>
          );
        },
        pre: ({ children }) => {
          const codeChild =
            children &&
            typeof children === "object" &&
            "props" in (children as React.ReactElement)
              ? (children as React.ReactElement<{
                  className?: string;
                  children?: string;
                }>)
              : null;

          const className = codeChild?.props?.className ?? "";
          const match = /language-(\w+)/.exec(className);
          const lang = match?.[1] ?? "text";
          const codeText = String(codeChild?.props?.children ?? "").replace(
            /\n$/,
            "",
          );

          return (
            <div className="group/code relative my-2 overflow-hidden rounded-lg text-xs">
              <CopyButton text={codeText} />
              <SyntaxHighlighter
                style={oneDark}
                language={lang}
                PreTag="div"
                customStyle={{
                  margin: 0,
                  borderRadius: "0.5rem",
                  fontSize: "0.75rem",
                  padding: "0.75rem 1rem",
                }}
              >
                {codeText}
              </SyntaxHighlighter>
            </div>
          );
        },
        ul: ({ children }) => (
          <ul className="mb-2 ml-4 list-disc space-y-0.5">{children}</ul>
        ),
        ol: ({ children }) => (
          <ol className="mb-2 ml-4 list-decimal space-y-0.5">{children}</ol>
        ),
        li: ({ children }) => <li className="leading-relaxed">{children}</li>,
        blockquote: ({ children }) => (
          <blockquote className="my-1 border-l-2 border-muted-foreground/40 pl-3 text-muted-foreground">
            {children}
          </blockquote>
        ),
        a: ({ href, children }) => (
          <a
            href={href}
            target="_blank"
            rel="noopener noreferrer"
            className="underline decoration-dotted hover:decoration-solid"
          >
            {children}
          </a>
        ),
        hr: () => <hr className="my-3 border-muted" />,
        strong: ({ children }) => (
          <strong className="font-semibold">{children}</strong>
        ),
        em: ({ children }) => <em className="italic">{children}</em>,
      }}
    >
      {content}
    </ReactMarkdown>
  );
}
