import type { ReactNode } from "react";

/** Mono uppercase eyebrow with a hairline extending to fill the row. */
export function SectionLabel({ children, right }: { children: ReactNode; right?: ReactNode }) {
  return (
    <div className="mb-4 flex items-center gap-2 font-mono text-[10px] tracking-[2px] uppercase text-faint">
      <span>{children}</span>
      <span className="h-px flex-1 bg-border" aria-hidden />
      {right}
    </div>
  );
}
