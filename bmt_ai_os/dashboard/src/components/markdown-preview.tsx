"use client";

import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import rehypeSlug from "rehype-slug";
import rehypeAutolinkHeadings from "rehype-autolink-headings";
import { Prism as SyntaxHighlighter } from "react-syntax-highlighter";
import { vscDarkPlus } from "react-syntax-highlighter/dist/esm/styles/prism";
import { cn } from "@/lib/utils";

// ---------------------------------------------------------------------------
// GitHub-style Markdown Preview
//
// Supports: GFM tables, task lists, strikethrough, autolinks, fenced code
// with syntax highlighting, heading anchors, and responsive images.
// ---------------------------------------------------------------------------

interface MarkdownPreviewProps {
  children: string;
  className?: string;
  /** Additional react-markdown components to merge (e.g., wiki-link renderers) */
  components?: Record<string, React.ComponentType<unknown>>;
}

export function MarkdownPreview({
  children,
  className,
  components: extraComponents,
}: MarkdownPreviewProps) {
  return (
    <article
      className={cn(
        "prose prose-sm prose-invert max-w-none",
        // GitHub-style tweaks
        "prose-headings:border-b prose-headings:border-border prose-headings:pb-2",
        "prose-h1:text-xl prose-h2:text-lg prose-h3:text-base",
        "prose-a:text-blue-400 prose-a:no-underline hover:prose-a:underline",
        "prose-code:before:content-none prose-code:after:content-none",
        "prose-code:bg-muted prose-code:rounded prose-code:px-1.5 prose-code:py-0.5 prose-code:text-[0.8em]",
        "prose-pre:bg-transparent prose-pre:p-0",
        "prose-img:rounded-lg prose-img:max-w-full",
        "prose-table:border-collapse",
        "prose-th:border prose-th:border-border prose-th:bg-muted/50 prose-th:px-3 prose-th:py-1.5 prose-th:text-left prose-th:text-xs prose-th:font-semibold",
        "prose-td:border prose-td:border-border prose-td:px-3 prose-td:py-1.5 prose-td:text-xs",
        "prose-blockquote:border-l-blue-500 prose-blockquote:bg-muted/20 prose-blockquote:py-1 prose-blockquote:not-italic",
        "prose-hr:border-border",
        "prose-li:marker:text-muted-foreground",
        className,
      )}
    >
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        rehypePlugins={[
          rehypeSlug,
          [rehypeAutolinkHeadings, { behavior: "wrap" }],
        ]}
        components={{
          // Fenced code blocks with syntax highlighting
          code({ className: codeClassName, children, ...props }) {
            const match = /language-(\w+)/.exec(codeClassName || "");
            const codeStr = String(children).replace(/\n$/, "");

            if (match) {
              return (
                <div className="relative group">
                  <SyntaxHighlighter
                    style={vscDarkPlus}
                    language={match[1]}
                    customStyle={{
                      margin: 0,
                      borderRadius: "0.375rem",
                      fontSize: "0.75rem",
                      lineHeight: "1.6",
                    }}
                    showLineNumbers
                    wrapLongLines={false}
                  >
                    {codeStr}
                  </SyntaxHighlighter>
                  <button
                    onClick={() => navigator.clipboard.writeText(codeStr)}
                    className="absolute right-2 top-2 rounded bg-muted/80 px-1.5 py-0.5 text-[10px] text-muted-foreground opacity-0 transition-opacity group-hover:opacity-100 hover:text-foreground"
                    aria-label="Copy code"
                  >
                    Copy
                  </button>
                </div>
              );
            }

            // Inline code
            return (
              <code className={codeClassName} {...props}>
                {children}
              </code>
            );
          },

          // Task list items (GFM checkboxes)
          input({ type, checked, ...props }) {
            if (type === "checkbox") {
              return (
                <input
                  type="checkbox"
                  checked={checked}
                  disabled
                  className="mr-1.5 rounded border-border accent-primary"
                  {...props}
                />
              );
            }
            return <input type={type} {...props} />;
          },

          // Tables — add horizontal scroll wrapper
          table({ children }) {
            return (
              <div className="overflow-x-auto">
                <table>{children}</table>
              </div>
            );
          },

          // Images — responsive with alt text caption
          img({ src, alt, ...props }) {
            return (
              <figure className="my-4">
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img
                  src={src}
                  alt={alt || ""}
                  className="rounded-lg max-w-full"
                  loading="lazy"
                  {...props}
                />
                {alt && (
                  <figcaption className="mt-1 text-center text-xs text-muted-foreground">
                    {alt}
                  </figcaption>
                )}
              </figure>
            );
          },

          // Merge any extra components (e.g., wiki-link handlers from note-editor)
          ...extraComponents,
        }}
      >
        {children}
      </ReactMarkdown>
    </article>
  );
}
