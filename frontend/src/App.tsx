import { HealthPage } from "@/modules/system/HealthPage";
import { useTheme } from "@/theme";

export default function App() {
  const { theme, toggle } = useTheme();
  return (
    <div className="mx-auto max-w-[1200px] px-4 py-6">
      <header className="mb-6 flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold text-ink">MF Analyser</h1>
          <p className="text-sm text-muted">Excel-driven research analytics · phase 0 scaffold</p>
        </div>
        <button
          type="button"
          onClick={toggle}
          aria-label={`Switch to ${theme === "dark" ? "light" : "dark"} theme`}
          className="rounded-sm border border-hairline bg-surface px-2 py-1 font-heading text-xs font-medium text-ink hover:border-accent"
        >
          {theme === "dark" ? "Light" : "Dark"} theme
        </button>
      </header>
      <main className="grid gap-3 md:grid-cols-2">
        <HealthPage />
      </main>
    </div>
  );
}
