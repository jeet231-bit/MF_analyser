/** Quiet top-of-page progress affordance for work in flight (runs, uploads). */
export function ProgressBar({ active, label }: { active: boolean; label?: string }) {
  if (!active) return null;
  return (
    <div role="progressbar" aria-label={label ?? "Working"} aria-busy="true" className="fixed inset-x-0 top-0 z-40 h-0.5 overflow-hidden bg-accent-soft">
      <div className="h-full w-1/3 animate-[progress_1.2s_ease-in-out_infinite] bg-accent" />
      <style>{`@keyframes progress { 0% { transform: translateX(-100%); } 100% { transform: translateX(300%); } }`}</style>
    </div>
  );
}
