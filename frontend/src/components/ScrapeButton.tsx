import { useEffect, useRef, useState } from "react";
import { api, Operator, ScrapeRun, ScrapeStatus } from "../api";

const OPERATOR_SHORT: Record<string, string> = {
  sfr_re: "SFR",
  zeop: "Zeop",
  orange_re: "Orange",
};

interface Props {
  onScrapeComplete: () => void;
  operators: Operator[];
}

interface BatchState {
  ids: number[];
  total: number;
}

interface BatchStatus {
  finished: number;
  failed: number;
  running: string | null;
}

export function ScrapeButton({ onScrapeComplete, operators }: Props) {
  const [selectedOperator, setSelectedOperator] = useState("sfr_re");
  const [activeRun, setActiveRun] = useState<ScrapeStatus | null>(null);
  const [runs, setRuns] = useState<ScrapeRun[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [orangeImporting, setOrangeImporting] = useState(false);
  const [batch, setBatch] = useState<BatchState | null>(null);
  const [batchStatus, setBatchStatus] = useState<BatchStatus | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const batchPollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const historyRef = useRef<HTMLDetailsElement>(null);

  useEffect(() => {
    api.getScrapeRuns().then(setRuns).catch(() => {});
  }, []);

  // Close the runs-history <details> when clicking anywhere outside it.
  useEffect(() => {
    const onDocClick = (e: MouseEvent) => {
      const el = historyRef.current;
      if (el && el.open && !el.contains(e.target as Node)) {
        el.open = false;
      }
    };
    document.addEventListener("mousedown", onDocClick);
    return () => document.removeEventListener("mousedown", onDocClick);
  }, []);

  const opLabel = (id: string) =>
    operators.find((o) => o.id === id)?.label ?? OPERATOR_SHORT[id] ?? id;

  const stopPolling = () => {
    if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
  };

  const stopBatchPolling = () => {
    if (batchPollRef.current) {
      clearInterval(batchPollRef.current);
      batchPollRef.current = null;
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
          if (status.status === "error") setError(status.error_message ?? "Erreur inconnue");
          // Refresh catalogue + health banner whether the run succeeded or failed.
          onScrapeComplete();
        }
      } catch (e) {
        stopPolling();
        setError(String(e));
      }
    }, 2000);
  };

  const startBatchPolling = (ids: number[]) => {
    stopBatchPolling();
    batchPollRef.current = setInterval(async () => {
      try {
        const allRuns = await api.getScrapeRuns();
        setRuns(allRuns);
        const mine = allRuns.filter((r) => ids.includes(r.id));
        const finished = mine.filter((r) => r.status === "done" || r.status === "error");
        const failed = mine.filter((r) => r.status === "error");
        const running = mine.find((r) => r.status === "running");
        setBatchStatus({
          finished: finished.length,
          failed: failed.length,
          running: running ? running.operator : null,
        });
        if (finished.length >= ids.length) {
          stopBatchPolling();
          setBatch(null);
          setBatchStatus(null);
          onScrapeComplete();
          if (failed.length > 0) {
            setError(
              `Collecte globale terminée — ${failed.length} vendeur(s) en erreur (voir le bandeau d'alerte).`
            );
          }
        }
      } catch (e) {
        stopBatchPolling();
        setBatch(null);
        setBatchStatus(null);
        setError(String(e));
      }
    }, 2500);
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

  const handleScrapeAll = async () => {
    setError(null);
    try {
      const created = await api.startScrapeAll();
      const ids = created.map((r) => r.id);
      setBatch({ ids, total: ids.length });
      setBatchStatus({ finished: 0, failed: 0, running: null });
      startBatchPolling(ids);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  useEffect(() => () => {
    stopPolling();
    stopBatchPolling();
  }, []);

  const handleOrangeImport = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    // Reset input so the same file can be re-imported
    e.target.value = "";
    setError(null);
    setOrangeImporting(true);
    try {
      await api.importOrangeCsv(file);
      await api.getScrapeRuns().then(setRuns).catch(() => {});
      onScrapeComplete();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setOrangeImporting(false);
    }
  };

  const singleRunning =
    activeRun !== null && (activeRun.status === "pending" || activeRun.status === "running");
  const batchRunning = batch !== null;
  const busy = singleRunning || batchRunning;
  const pct = activeRun && activeRun.phones_found > 0
    ? Math.round((activeRun.phones_scraped / activeRun.phones_found) * 100)
    : 0;
  const batchPct = batch && batchStatus
    ? Math.round((batchStatus.finished / batch.total) * 100)
    : 0;

  return (
    <div className="scrape-panel">
      <div className="scrape-controls">
        <select
          className="operator-select"
          value={selectedOperator}
          onChange={(e) => setSelectedOperator(e.target.value)}
          disabled={busy}
        >
          {operators.filter((op) => op.id !== "orange_re").map((op) => (
            <option key={op.id} value={op.id}>{op.label}</option>
          ))}
        </select>
        <button
          className="scrape-btn"
          onClick={handleClick}
          disabled={busy}
        >
          {singleRunning ? "Collecte en cours…" : "Lancer une collecte"}
        </button>
        <button
          className="scrape-btn scrape-btn-all"
          onClick={handleScrapeAll}
          disabled={busy}
          title="Lancer une collecte pour tous les vendeurs, l'un après l'autre"
        >
          {batchRunning ? "Collecte globale…" : "Tout collecter"}
        </button>
        <input
          ref={fileInputRef}
          type="file"
          accept=".csv"
          style={{ display: "none" }}
          onChange={handleOrangeImport}
        />
        <button
          className="scrape-btn scrape-btn-orange"
          onClick={() => fileInputRef.current?.click()}
          disabled={orangeImporting || busy}
        >
          {orangeImporting ? "Import Orange…" : "Importer CSV Orange"}
        </button>
      </div>

      {singleRunning && activeRun && (
        <div className="progress-block">
          <div className="progress-bar">
            <div className="progress-fill" style={{ width: `${pct}%` }} />
          </div>
          <span className="progress-label">
            {activeRun.phones_scraped} / {activeRun.phones_found || "?"} terminaux
          </span>
        </div>
      )}

      {batchRunning && batch && batchStatus && (
        <div className="progress-block">
          <div className="progress-bar">
            <div className="progress-fill" style={{ width: `${batchPct}%` }} />
          </div>
          <span className="progress-label">
            Collecte globale : {batchStatus.finished}/{batch.total} vendeurs
            {batchStatus.running ? ` · en cours : ${opLabel(batchStatus.running)}` : ""}
            {batchStatus.failed > 0 ? ` · ${batchStatus.failed} en erreur` : ""}
          </span>
        </div>
      )}

      {error && <p className="error-msg">{error}</p>}

      {runs.length > 0 && (
        <details ref={historyRef} className="runs-history">
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
