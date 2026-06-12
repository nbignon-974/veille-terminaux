import { ScrapeHealth } from "../api";
import { OPERATOR_BADGE } from "../operatorColors";

interface Props {
  issues: ScrapeHealth[];
  onRefresh?: () => void;
}

/**
 * Persistent alert surface: stays visible as long as a scraper's last run
 * errored, returned 0, or collected far fewer products than before. Meant to be
 * impossible to miss — a broken scraper must trigger an analysis, not be ignored.
 */
export function ScrapeHealthBanner({ issues, onRefresh }: Props) {
  if (issues.length === 0) return null;

  const koCount = issues.filter((i) => i.state === "ko").length;
  const warnCount = issues.length - koCount;

  return (
    <div className="health-banner" role="alert">
      <div className="health-banner-head">
        <span className="health-banner-title">
          ⚠️ {issues.length} scraper{issues.length > 1 ? "s" : ""} à analyser
          {koCount > 0 && <span className="health-pill health-pill-ko">{koCount} KO</span>}
          {warnCount > 0 && <span className="health-pill health-pill-warning">{warnCount} suspect{warnCount > 1 ? "s" : ""}</span>}
        </span>
        {onRefresh && (
          <button className="health-refresh" onClick={onRefresh} title="Rafraîchir l'état">
            ↻
          </button>
        )}
      </div>
      <ul className="health-list">
        {issues.map((i) => {
          const badge = OPERATOR_BADGE[i.operator];
          const when = i.last_at ? new Date(i.last_at).toLocaleString("fr-FR") : "";
          return (
            <li key={i.operator} className={`health-item health-item-${i.state}`}>
              <span
                className="health-badge"
                style={{ backgroundColor: badge?.color ?? "#666" }}
              >
                {badge?.label ?? i.label}
              </span>
              <span className="health-reason">{i.reason}</span>
              {when && <span className="health-when">· {when}</span>}
            </li>
          );
        })}
      </ul>
    </div>
  );
}
