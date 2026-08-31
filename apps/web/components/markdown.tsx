"use client";

import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

export function Markdown({ children }: { children: string }) {
  return (
    <ReactMarkdown
      remarkPlugins={[remarkGfm]}
      components={{
        table: ({ children }) => (
          <div className="rounded border border-border overflow-hidden my-1">
            <table className="w-full text-[11px]">{children}</table>
          </div>
        ),
        thead: ({ children }) => (
          <thead className="border-b border-border bg-muted/50">{children}</thead>
        ),
        th: ({ children }) => (
          <th className="text-left px-2 py-1 font-medium text-muted-foreground">{children}</th>
        ),
        td: ({ children }) => (
          <td className="px-2 py-1 border-b border-border/50">{children}</td>
        ),
        h1: ({ children }) => (
          <h1 className="text-base font-semibold my-1">{children}</h1>
        ),
        h2: ({ children }) => (
          <h2 className="text-sm font-semibold my-1">{children}</h2>
        ),
        h3: ({ children }) => (
          <h3 className="text-sm font-medium my-1">{children}</h3>
        ),
        h4: ({ children }) => (
          <h4 className="text-xs font-medium my-1">{children}</h4>
        ),
        h5: ({ children }) => (
          <h5 className="text-xs font-medium my-1">{children}</h5>
        ),
        h6: ({ children }) => (
          <h6 className="text-xs font-medium my-1">{children}</h6>
        ),
        p: ({ children }) => (
          <p className="my-1">{children}</p>
        ),
        strong: ({ children }) => (
          <strong className="font-semibold">{children}</strong>
        ),
        em: ({ children }) => (
          <em className="italic">{children}</em>
        ),
        code: ({ children, className }) => {
          const isInline = !className?.includes("language-");
          return isInline ? (
            <code className="bg-muted/50 rounded px-1 py-0.5 font-mono text-[10px]">
              {children}
            </code>
          ) : (
            <code className="block bg-muted/30 rounded p-2 font-mono text-[10px] whitespace-pre-wrap my-1">
              {children}
            </code>
          );
        },
        pre: ({ children }) => <>{children}</>,
        ul: ({ children }) => (
          <ul className="list-disc pl-4 my-1 space-y-0.5">{children}</ul>
        ),
        ol: ({ children }) => (
          <ol className="list-decimal pl-4 my-1 space-y-0.5">{children}</ol>
        ),
        a: ({ children, href }) => (
          <a href={href} className="underline text-muted-foreground hover:text-foreground">
            {children}
          </a>
        ),
        blockquote: ({ children }) => (
          <blockquote className="border-l-2 border-border pl-3 my-1 text-muted-foreground">
            {children}
          </blockquote>
        ),
        hr: () => <hr className="border-border my-1" />,
      }}
    >
      {children}
    </ReactMarkdown>
  );
}
