/**
 * Obsidian markdown utilities for the BMT AI OS dashboard.
 *
 * Provides client-side parsing of Obsidian-format markdown including
 * wiki-links ([[Target]]), frontmatter (YAML between --- delimiters),
 * and inline #tags.
 */

// ---------------------------------------------------------------------------
// Regex patterns (mirrors the Python implementation in bmt_ai_os/rag/obsidian.py)
// ---------------------------------------------------------------------------

const EMBED_RE = /!\[\[([^\]]+)\]\]/g;
const WIKI_LINK_RE = /(?<!!)(\[\[([^\]]+)\]\])/g;
const TAG_RE = /(?:^|\s)#([a-zA-Z0-9_/-]+)/gm;
const FRONTMATTER_RE = /^---\n([\s\S]*?)\n---\n/;
const CODE_FENCE_RE = /```[\s\S]*?```/g;
const INLINE_CODE_RE = /`[^`\n]+`/g;

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function stripCodeBlocks(text: string): string {
  return text.replace(CODE_FENCE_RE, "").replace(INLINE_CODE_RE, "");
}

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------

/**
 * Replace ``[[wiki-links]]`` in *markdown* with anchor tags whose ``href``
 * values are the encoded link target.  Embed references (``![[...]]``) are
 * left untouched.
 *
 * The *onNavigate* callback receives the raw link target string (e.g.
 * ``"My Note#Heading"``) whenever the user clicks a rendered wiki-link.
 * The callback is wired via an ``onclick`` attribute on the generated
 * ``<a>`` element so it works in contexts where ``dangerouslySetInnerHTML``
 * is used.
 *
 * @param markdown   Raw markdown string that may contain ``[[...]]`` links.
 * @param onNavigate Callback invoked with the link target on click.  Pass a
 *                   no-op (``() => {}``) when navigation is handled by the
 *                   ``href`` alone.
 * @returns Modified markdown string with wiki-links replaced by HTML anchors.
 */
export function renderWikiLinks(
  markdown: string,
  onNavigate: (target: string) => void,
): string {
  // Register a global handler so onclick attributes can call it.
  // We namespace it to avoid collisions with other code on the page.
  if (typeof window !== "undefined") {
    (window as unknown as Record<string, unknown>).__bmt_wikilink_navigate__ =
      onNavigate;
  }

  return markdown.replace(WIKI_LINK_RE, (_match, _full, target: string) => {
    const encoded = encodeURIComponent(target);
    const safe = target.replace(/\\/g, "\\\\").replace(/"/g, "&quot;");
    return (
      `<a href="/notes/${encoded}" class="wiki-link" ` +
      `onclick="event.preventDefault();` +
      `if(window.__bmt_wikilink_navigate__)` +
      `window.__bmt_wikilink_navigate__('${safe.replace(/'/g, "\\'")}')">` +
      `${target}</a>`
    );
  });
}

/**
 * Parse YAML frontmatter from a markdown string.
 *
 * Frontmatter is expected between two ``---`` lines at the very start of the
 * document (following the Obsidian / Jekyll convention).  The YAML is parsed
 * with a simple key-value tokeniser that handles strings, numbers, booleans,
 * and flat arrays — it does not support nested objects.  For complex
 * frontmatter, use a full YAML library on the server side.
 *
 * @param markdown Raw markdown string (may or may not contain frontmatter).
 * @returns Object with ``frontmatter`` record and ``content`` string
 *          (markdown without the frontmatter block).
 */
export function parseFrontmatter(markdown: string): {
  frontmatter: Record<string, unknown>;
  content: string;
} {
  const match = FRONTMATTER_RE.exec(markdown);
  if (!match) {
    return { frontmatter: {}, content: markdown };
  }

  const yamlBlock = match[1];
  const content = markdown.slice(match[0].length);
  const frontmatter: Record<string, unknown> = _parseSimpleYaml(yamlBlock);

  return { frontmatter, content };
}

/**
 * Extract all ``#tag`` references from *markdown*.
 *
 * Tags inside fenced code blocks and inline code spans are excluded.
 * Duplicate tags are removed; order of first occurrence is preserved.
 *
 * @param markdown Raw markdown string.
 * @returns Deduplicated list of tag names (without the leading ``#``).
 */
export function extractTags(markdown: string): string[] {
  const clean = stripCodeBlocks(markdown);
  const tags: string[] = [];
  const seen = new Set<string>();
  let m: RegExpExecArray | null;

  // Reset lastIndex before iterating
  TAG_RE.lastIndex = 0;
  while ((m = TAG_RE.exec(clean)) !== null) {
    const tag = m[1];
    if (!seen.has(tag)) {
      seen.add(tag);
      tags.push(tag);
    }
  }

  return tags;
}

/**
 * Extract all ``[[wiki-link]]`` targets from *markdown*.
 *
 * Embed references (``![[...]]``) are excluded.  Duplicate targets are
 * removed; order of first occurrence is preserved.
 *
 * @param markdown Raw markdown string.
 * @returns Deduplicated list of link target strings (without ``[[ ]]``).
 */
export function extractWikiLinks(markdown: string): string[] {
  const links: string[] = [];
  const seen = new Set<string>();

  // First strip embed markers so they are not captured as wiki-links
  const noEmbeds = markdown.replace(EMBED_RE, "");

  // Reset and re-apply with a fresh regex to avoid stateful lastIndex
  const re = /(?<!!)(\[\[([^\]]+)\]\])/g;
  let m: RegExpExecArray | null;
  while ((m = re.exec(noEmbeds)) !== null) {
    const target = m[2];
    if (!seen.has(target)) {
      seen.add(target);
      links.push(target);
    }
  }

  return links;
}

// ---------------------------------------------------------------------------
// Internal helpers
// ---------------------------------------------------------------------------

/**
 * Minimal YAML key-value parser that covers the common Obsidian frontmatter
 * subset: scalars (string / number / boolean) and flat lists.
 *
 * Not a full YAML parser — use a library for complex documents.
 */
function _parseSimpleYaml(yaml: string): Record<string, unknown> {
  const result: Record<string, unknown> = {};
  const lines = yaml.split("\n");
  let i = 0;

  while (i < lines.length) {
    const line = lines[i];

    // Skip blank lines and comments
    if (!line.trim() || line.trim().startsWith("#")) {
      i++;
      continue;
    }

    const colonIdx = line.indexOf(":");
    if (colonIdx === -1) {
      i++;
      continue;
    }

    const key = line.slice(0, colonIdx).trim();
    const rest = line.slice(colonIdx + 1).trim();

    if (rest === "" || rest === null) {
      // Possibly a block list follows
      const listItems: unknown[] = [];
      i++;
      while (i < lines.length && lines[i].trimStart().startsWith("-")) {
        listItems.push(_coerce(lines[i].replace(/^\s*-\s*/, "").trim()));
        i++;
      }
      result[key] = listItems.length > 0 ? listItems : null;
      continue;
    }

    // Inline list: key: [a, b, c]
    if (rest.startsWith("[") && rest.endsWith("]")) {
      const inner = rest.slice(1, -1);
      result[key] = inner
        .split(",")
        .map((s) => _coerce(s.trim()))
        .filter((s) => s !== "");
      i++;
      continue;
    }

    result[key] = _coerce(rest);
    i++;
  }

  return result;
}

/** Coerce a raw YAML scalar string to number, boolean, or string. */
function _coerce(value: string): unknown {
  if (value === "true") return true;
  if (value === "false") return false;
  if (value === "null" || value === "~") return null;

  const num = Number(value);
  if (!isNaN(num) && value !== "") return num;

  // Strip surrounding quotes
  if (
    (value.startsWith('"') && value.endsWith('"')) ||
    (value.startsWith("'") && value.endsWith("'"))
  ) {
    return value.slice(1, -1);
  }

  return value;
}
