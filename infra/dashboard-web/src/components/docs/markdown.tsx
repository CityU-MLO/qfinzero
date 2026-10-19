"use client";

// Markdown of the guides: anchored headings, in-hub links, and blockquotes
// that start with **Note**, **Warning**, **Tip** (or GitHub's [!NOTE]) as callouts.

import * as React from "react";
import Link from "next/link";
import { Streamdown } from "streamdown";
import "streamdown/styles.css";
import { AlertTriangle, Info, Lightbulb, Link2 } from "lucide-react";

import { slugify } from "@/lib/docs";
import { cn } from "@/lib/utils";

export function textOf(node: React.ReactNode): string {
  if (typeof node === "string" || typeof node === "number") return String(node);
  if (Array.isArray(node)) return node.map(textOf).join("");
  if (React.isValidElement<{ children?: React.ReactNode }>(node)) return textOf(node.props.children);
  return "";
}

function heading(Tag: "h2" | "h3" | "h4") {
  return function H({ children, className }: { children?: React.ReactNode; className?: string }) {
    const id = slugify(textOf(children));
    return (
      <Tag id={id} className={cn("group scroll-mt-28", className)}>
        {children}
        <a href={`#${id}`} className="ml-2 inline-flex align-middle text-muted-foreground/0 transition-colors group-hover:text-muted-foreground hover:!text-primary" aria-label="link">
          <Link2 className="h-3.5 w-3.5" />
        </a>
      </Tag>
    );
  };
}

function DocLink({ href, children }: { href?: string; children?: React.ReactNode }) {
  if (href && (href.startsWith("/docs") || href.startsWith("#"))) return <Link href={href}>{children}</Link>;
  return <a href={href} target="_blank" rel="noopener noreferrer">{children}</a>;
}

const CALLOUT = {
  note: { icon: Info, cls: "border-primary/30 bg-primary/[0.05]", title: "text-primary" },
  tip: { icon: Lightbulb, cls: "border-success/30 bg-success/[0.06]", title: "text-success" },
  warning: { icon: AlertTriangle, cls: "border-warning/40 bg-warning/[0.07]", title: "text-warning" },
} as const;

function Quote({ children }: { children?: React.ReactNode }) {
  const text = textOf(children).trim();
  const m = /^\[?!?(note|tip|warning|important|caution|注意|提示|警告)\]?\s*[:：]?/i.exec(text);
  if (!m) return <blockquote>{children}</blockquote>;
  const word = m[1].toLowerCase();
  const kind = word === "tip" || word === "提示" ? "tip" : word === "note" || word === "注意" || word === "important" ? "note" : "warning";
  const c = CALLOUT[kind];
  const Icon = c.icon;
  return (
    <div className={cn("callout my-5 flex gap-3 rounded-lg border px-4 py-3 text-[14px]", c.cls)}>
      <Icon className={cn("mt-0.5 h-4 w-4 shrink-0", c.title)} />
      <div className="min-w-0 [&>p:last-child]:mb-0">{children}</div>
    </div>
  );
}

const COMPONENTS = { h2: heading("h2"), h3: heading("h3"), h4: heading("h4"), a: DocLink, blockquote: Quote };

export function DocMarkdown({ children }: { children: string }) {
  return (
    <div className="doc-body">
      <Streamdown mode="static" components={COMPONENTS} controls={{ table: false, code: true, mermaid: false }}
                  linkSafety={{ enabled: false }}>
        {children}
      </Streamdown>
    </div>
  );
}

/** "On this page" with the heading in view highlighted. */
export function Toc({ items, title }: { items: { level: 2 | 3; text: string; id: string }[]; title: string }) {
  const [active, setActive] = React.useState<string>("");
  React.useEffect(() => {
    const els = items.map((h) => document.getElementById(h.id)).filter(Boolean) as HTMLElement[];
    if (!els.length) return;
    const onScroll = () => {
      const top = 140;
      let cur = els[0].id;
      for (const el of els) {
        if (el.getBoundingClientRect().top - top <= 0) cur = el.id;
        else break;
      }
      setActive(cur);
    };
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, [items]);
  if (items.length < 2) return null;
  return (
    <div>
      <p className="mb-3 text-[12px] font-semibold uppercase tracking-wide text-muted-foreground">{title}</p>
      <ul className="space-y-0.5 border-l text-[13px]">
        {items.map((h, i) => (
          <li key={`${h.id}-${i}`}>
            <a href={`#${h.id}`}
               className={cn("-ml-px block border-l py-1 leading-snug transition-colors",
                 h.level === 3 ? "pl-6" : "pl-3",
                 active === h.id ? "border-primary font-medium text-primary" : "border-transparent text-muted-foreground hover:text-foreground")}>
              {h.text}
            </a>
          </li>
        ))}
      </ul>
    </div>
  );
}
