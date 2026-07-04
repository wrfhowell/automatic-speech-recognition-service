import { useEffect, useRef } from "react";

/** Invisible row that fires when scrolled into view — drives infinite pages. */
export function InfiniteSentinel({
  onVisible,
  disabled,
}: {
  onVisible: () => void;
  disabled: boolean;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const callback = useRef(onVisible);
  callback.current = onVisible;

  useEffect(() => {
    if (disabled || !ref.current) return;
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((e) => e.isIntersecting)) callback.current();
      },
      { rootMargin: "200px" },
    );
    observer.observe(ref.current);
    return () => observer.disconnect();
  }, [disabled]);

  return <div ref={ref} className="h-px" aria-hidden />;
}
