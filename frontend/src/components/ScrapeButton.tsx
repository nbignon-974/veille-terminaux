import { useEffect, useRef, useState } from "react";
import { api, Operator, ScrapeRun, ScrapeStatus } from "../api";

const OPERATOR_SHORT: Record<string, string> = {
  sfr_re: "SFR",
  zeop: "Zeop",
};

interface Props {
  onScrapeComplete: () => void;
  operators: Operator[];
}

export function ScrapeButton({ onScrapeComplete, operators }: Props) {
  const [selectedOperator, setSelectedOperator] = useState("sfr_re");
  const [activeRun, setActiveRun] = useState<ScrapeStatus | null>(null);
  const [runs, setRuns] = useState<ScrapeRun[]>([]);
  const [error, setError] = useState<string | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    api.getScrapeRuns().then(setRuns).catch(() => {});
  }, []);

  const stopPolling = () => {
    if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
  };

  const startPolling = (runId: number) => {
    stopPolling();
    pollRef.current = setInterval(async () => {
      try {
        const status = await api.getScrapeStatus(runId);
        setActiveRun(status);
        if (status.status === "done" || status.status === "error") {
          stopPolling();
          setActiveRun(null);
          api.getScrapeRuns().then(setRuns).catch(() => {});
          if (status.status === "done") onScrapeComplete();
          if (status.status === "error") setError(status.error_message ?? "Erreur inconnue");
        }
      } catch (e) {
        stopPolling();
        setError(String(e));
      }
    }, 2000);
  };

  const handleClick = async () => {
    setError(null);
    try {
      const run = await api.startScrape(selectedOperator);
      setActiveRun({
        run_id: run.id,
        status: "pending",
        phones_found: 0,
        phones_scraped: 0,
        finished_at: null,
        error_message: null,
        operator: selectedOperator,
      });
      startPolling(run.id);
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e);
      setError(msg);
    }
  };

  useEffect(() => () => stopPolling(), []);

  const isRunning = activeRun !== null && (activeRun.status === "pending" || activeRun.status === "running");
  const pct = activeRun && activeRun.phones_found > 0
    ? Math.round((activeRun.phones_scraped / activeRun.phones_found) * 100)
    : 0;

  return (
    <div className="scrape-panel">
      <div className="scrape-controls">
        <select
          className="operator-select"
          value={selectedOperator}
          onChange={(e) => setSelectedOperator(e.target.value)}
          disabled={isRunning}
        >
          {operators.map((op) => (
            <option key={op.id} value={op.id}>{op.label}</option>
          ))}
        </select>
        <button
          className="scrape-btn"
          onClick={handleClick}
          disabled={isRunning}
        >
          {isRunning ? "Collecte en cours…" : "Lancer une collecte"}
        </button>
      </div>

      {isRunning && activeRun && (
        <div className="progress-block">
          <div className="progress-bar">
            <div className="progress-fill" style={{ width: `${pct}%` }} />
          </div>
          <span className="progress-label">
            {activeRun.phones_scraped} / {activeRun.phones_found || "?"} terminaux
          </span>
        </div>
      )}

      {error && <p className="error-msg">{error}</p>}

      {runs.length > 0 && (
        <details className="runs-history">
          <summary>Historique des collectes ({runs.length})</summary>
          <table className="runs-table">
            <thead>
              <tr>
                <th>#</th>
                <th>Vendeur</th>
                <th>Démarré</th>
                <th>Statut</th>
                <th>Terminaux</th>
                <th>Durée</th>
              </tr>
            </thead>
            <tbody>
              {runs.map((r) => {
                const start = new Date(r.started_at);
                const end = r.finished_at ? new Date(r.finished_at) : null;
                const duration = end
                  ? `${Math.round((end.getTime() - start.getTime()) / 1000)}s`
                  : "–";
                return (
                  <tr key={r.id} className={`run-${r.status}`}>
                    <td>{r.id}</td>
                    <td>{OPERATOR_SHORT[r.operator] || r.operator}</td>
                    <td>{start.toLocaleString("fr-FR")}</td>
                    <td>
                      <span className={`badge badge-${r.status}`}>{r.status}</span>
                    </td>
                    <td>{r.phones_scraped}</td>
                    <td>{duration}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </details>
      )}
    </div>
  );
}
