import { NavLink, Outlet } from "react-router-dom";

const navLinkClass = ({ isActive }: { isActive: boolean }) =>
  [
    "flex items-center gap-2.5 rounded px-2.5 py-1.5 font-mono text-[11px] tracking-[2px] uppercase transition-colors duration-200",
    isActive
      ? "text-ink bg-surface/80"
      : "text-muted hover:text-ink hover:bg-surface/50",
  ].join(" ");

function QuillIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 16 16" fill="none" aria-hidden>
      <path
        d="M13.5 2.5c-4 .5-7.5 2.5-9.5 6.5L2.5 13.5l4.5-1.5c4-2 6-5.5 6.5-9.5z"
        stroke="currentColor"
        strokeWidth="1.25"
        strokeLinejoin="round"
      />
      <path d="M3.5 12.5l6-6" stroke="currentColor" strokeWidth="1.25" />
    </svg>
  );
}

function LedgerIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 16 16" fill="none" aria-hidden>
      <circle cx="7" cy="7" r="4.5" stroke="currentColor" strokeWidth="1.25" />
      <path d="M10.5 10.5l3 3" stroke="currentColor" strokeWidth="1.25" strokeLinecap="round" />
    </svg>
  );
}

export function AppShell() {
  return (
    <div className="mx-auto max-w-[1320px] px-8 py-10 md:px-16">
      <div className="grid grid-cols-[11.5rem_minmax(0,1fr)] gap-x-10">
        <aside className="sticky top-10 self-start">
          <header className="mb-8 border-b border-border pb-4">
            <div className="font-mono text-[10px] tracking-[3px] uppercase text-faint">
              Field Console
            </div>
            <h1 className="font-serif text-[1.4rem] leading-tight tracking-wide">
              Transcription
              <br />
              Service
            </h1>
          </header>
          <nav className="flex flex-col gap-1" aria-label="Primary">
            <NavLink to="/" end className={navLinkClass}>
              <QuillIcon /> Submit
            </NavLink>
            <NavLink to="/search" className={navLinkClass}>
              <LedgerIcon /> Records
            </NavLink>
          </nav>
          <footer className="mt-10 border-t border-border pt-4 font-mono text-[9px] tracking-widest uppercase text-faint leading-relaxed">
            ASR ledger
            <br />
            de-identified by default
          </footer>
        </aside>
        <main className="min-w-0 border-l border-border pl-10">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
