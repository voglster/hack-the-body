import { Fragment } from "react";

import { useNow } from "../lib/useNow";

interface CoachTextProps {
  text: string;
  anchors?: Record<string, string> | null;
}

const PLACEHOLDER_RE = /\{\{([a-zA-Z0-9_]+)\}\}/g;

/** Splits `text` on `{{name}}` placeholders. Each placeholder whose name is in
 *  `anchors` renders as a live <RelativeAnchor>. Unknown names stay literal. */
export function CoachText({ text, anchors }: CoachTextProps) {
  const parts: React.ReactNode[] = [];
  let lastIndex = 0;
  let match: RegExpExecArray | null;
  const re = new RegExp(PLACEHOLDER_RE);
  while ((match = re.exec(text)) !== null) {
    if (match.index > lastIndex) {
      parts.push(text.slice(lastIndex, match.index));
    }
    const name = match[1];
    const iso = anchors?.[name];
    if (iso) {
      parts.push(<RelativeAnchor key={`${name}-${match.index}`} iso={iso} />);
    } else {
      parts.push(match[0]);
    }
    lastIndex = match.index + match[0].length;
  }
  if (lastIndex < text.length) parts.push(text.slice(lastIndex));
  return (
    <>
      {parts.map((p, i) => (
        <Fragment key={i}>{p}</Fragment>
      ))}
    </>
  );
}

function formatClock(d: Date): string {
  return d.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
}

function formatRelative(targetMs: number, nowMs: number): string {
  const diffMs = targetMs - nowMs;
  const ahead = diffMs >= 0;
  const absMs = Math.abs(diffMs);
  const mins = Math.round(absMs / 60_000);
  if (mins < 60) return ahead ? `in ${mins}m` : `${mins}m ago`;
  const hours = Math.floor(mins / 60);
  const rem = mins % 60;
  const tail = rem > 0 ? `${hours}h ${rem}m` : `${hours}h`;
  return ahead ? `in ${tail}` : `${tail} ago`;
}

function RelativeAnchor({ iso }: { iso: string }) {
  const now = useNow(30_000);
  const target = new Date(iso);
  if (Number.isNaN(target.getTime())) return <>{iso}</>;
  return (
    <span className="whitespace-nowrap">
      {formatClock(target)} ({formatRelative(target.getTime(), now.getTime())})
    </span>
  );
}
