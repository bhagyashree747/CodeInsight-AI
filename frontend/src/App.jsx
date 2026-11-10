import { useEffect, useMemo, useState } from "react";
import {
  Activity, AlertCircle, ArrowRight, ArrowUpRight, Bug,
  CheckCircle2, Code2, FileCode2, GitBranch, LayoutDashboard,
  LoaderCircle, RefreshCw, Search, ShieldCheck, Sparkles,
  Terminal, WandSparkles, XCircle, Zap
} from "lucide-react";
import "./App.css";

const API_URL = "http://127.0.0.1:8000";

const NAV_ITEMS = [
  { id: "overview", label: "Overview", icon: LayoutDashboard },
  { id: "review", label: "Code Review", icon: Code2 },
  { id: "repairs", label: "AI Repairs", icon: WandSparkles },
  { id: "verification", label: "Verification", icon: ShieldCheck },
];

const SAMPLE_CODE = `def divide(a, b):
    return a / b

print(divide(10, 0))`;

function App() {
  const [activePage, setActivePage] = useState("overview");
  const [apiStatus, setApiStatus] = useState("checking");
  const [code, setCode] = useState(SAMPLE_CODE);
  const [filename, setFilename] = useState("sample.py");
  const [maxAttempts, setMaxAttempts] = useState(2);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [result, setResult] = useState(null);
  const [lastRun, setLastRun] = useState(null);

  const data = result?.data;
  const counts = data?.counts || {};
  const summary = data?.summary || {};
  const findings = data?.findings || [];
  const repairs = data?.repairs || [];

  const stats = useMemo(() => [
    {
      label: "Issues detected",
      value: counts.issues_detected ?? "—",
      icon: Bug,
      color: "purple",
    },
    {
      label: "Actionable findings",
      value: counts.kept ?? "—",
      icon: AlertCircle,
      color: "orange",
    },
    {
      label: "Verified repairs",
      value: summary.verified ?? "—",
      icon: CheckCircle2,
      color: "green",
    },
    {
      label: "Failed repairs",
      value: summary.failed ?? "—",
      icon: XCircle,
      color: "red",
    },
  ], [counts, summary]);

  async function checkHealth() {
    try {
      const response = await fetch(`${API_URL}/api/health`);
      if (!response.ok) throw new Error("Backend unavailable");
      await response.json();
      setApiStatus("online");
    } catch {
      setApiStatus("offline");
    }
  }

  useEffect(() => {
    checkHealth();
    const interval = setInterval(checkHealth, 10000);
    return () => clearInterval(interval);
  }, []);

  async function runReview(event) {
    event.preventDefault();
    setError("");
    setLoading(true);
    setActivePage("review");

    try {
      const response = await fetch(`${API_URL}/api/review`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          code,
          filename,
          max_attempts: Number(maxAttempts),
        }),
      });

      const payload = await response.json();

      if (!response.ok) {
        throw new Error(
          payload.detail || `Request failed with status ${response.status}`
        );
      }

      setResult(payload);
      setLastRun(new Date().toLocaleString());
    } catch (err) {
      setError(
        err.message === "Failed to fetch"
          ? "Cannot reach the backend. Check that FastAPI is running on port 8000."
          : err.message
      );
    } finally {
      setLoading(false);
      checkHealth();
    }
  }

  function pageTitle() {
    return NAV_ITEMS.find((item) => item.id === activePage)?.label || "Overview";
  }

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <div className="brand-mark"><Code2 size={23} /></div>
          <div>
            <div className="brand-name">CodeInsight<span>AI</span></div>
            <div className="brand-caption">INTELLIGENT CODE ANALYSIS</div>
          </div>
        </div>

        <div className="nav-label">WORKSPACE</div>
        <nav className="navigation">
          {NAV_ITEMS.map(({ id, label, icon: Icon }) => (
            <button
              key={id}
              className={`nav-item ${activePage === id ? "active" : ""}`}
              onClick={() => setActivePage(id)}
            >
              <Icon size={18} />
              <span>{label}</span>
              {activePage === id && <span className="active-dot" />}
            </button>
          ))}
        </nav>

        <div className="sidebar-bottom">
          <div className="backend-card">
            <div className="backend-heading">
              <Activity size={16} />
              <span>Backend connection</span>
            </div>
            <div className="backend-status">
              <span className={`status-dot ${apiStatus}`} />
              {apiStatus === "checking"
                ? "Checking..."
                : apiStatus === "online"
                  ? "API connected"
                  : "API offline"}
            </div>
            <div className="backend-url">localhost:8000</div>
            <button className="refresh-button" onClick={checkHealth}>
              <RefreshCw size={13} /> Check connection
            </button>
          </div>
          <div className="sidebar-footer">CodeInsight AI · Development build</div>
        </div>
      </aside>

      <main className="main-area">
        <header className="topbar">
          <div className="breadcrumb">
            <span>Workspace</span><span className="slash">/</span>
            <strong>{pageTitle()}</strong>
          </div>
          <div className="topbar-right">
            <span className="environment"><span /> LOCAL ENVIRONMENT</span>
            <div className="avatar">B</div>
          </div>
        </header>

        <div className="page-content">
          <section className="welcome-row">
            <div>
              <div className="eyebrow"><Sparkles size={14} /> AI-POWERED DEVELOPMENT</div>
              <h1>{activePage === "overview" ? "Code intelligence, at a glance." : pageTitle()}</h1>
              <p>
                {activePage === "overview"
                  ? "Review, repair and verify your code from one workspace."
                  : "Work with your CodeInsight analysis pipeline and real backend results."}
              </p>
            </div>
            <button className="primary-button" onClick={() => setActivePage("review")}>
              <Code2 size={17} /> New code review <ArrowRight size={16} />
            </button>
          </section>

          <section className="stats-grid">
            {stats.map(({ label, value, icon: Icon, color }) => (
              <div className="stat-card" key={label}>
                <div className={`stat-icon ${color}`}><Icon size={19} /></div>
                <div className="stat-label">{label}</div>
                <div className="stat-value">{value}</div>
                <div className="stat-note">
                  {result ? "Latest review result" : "Awaiting first review"}
                </div>
              </div>
            ))}
          </section>

          {activePage === "overview" && (
            <div className="content-grid">
              <section className="panel editor-panel">
                <div className="panel-heading">
                  <div>
                    <div className="panel-title"><Terminal size={18} /> Quick code review</div>
                    <div className="panel-subtitle">Submit Python code to your review pipeline</div>
                  </div>
                  <span className="language-tag">PYTHON</span>
                </div>
                <form onSubmit={runReview}>
                  <div className="input-row">
                    <label className="field-label">
                      Filename
                      <input
                        value={filename}
                        onChange={(e) => setFilename(e.target.value)}
                        placeholder="main.py"
                        required
                      />
                    </label>
                    <label className="field-label attempts-field">
                      Repair attempts
                      <select
                        value={maxAttempts}
                        onChange={(e) => setMaxAttempts(e.target.value)}
                      >
                        <option value={1}>1 attempt</option>
                        <option value={2}>2 attempts</option>
                        <option value={3}>3 attempts</option>
                      </select>
                    </label>
                  </div>
                  <div className="code-editor">
                    <div className="editor-toolbar">
                      <div><span className="editor-dot" /> {filename || "untitled.py"}</div>
                      <span>Python source</span>
                    </div>
                    <textarea
                      spellCheck="false"
                      value={code}
                      onChange={(e) => setCode(e.target.value)}
                      aria-label="Python source code"
                      required
                    />
                  </div>
                  {error && <div className="error-message"><AlertCircle size={16} />{error}</div>}
                  <div className="editor-actions">
                    <span className="helper-text">Results come from your connected backend.</span>
                    <button className="primary-button" type="submit" disabled={loading || !code.trim()}>
                      {loading
                        ? <><LoaderCircle className="spin" size={17} /> Analyzing...</>
                        : <><Zap size={17} /> Run analysis</>}
                    </button>
                  </div>
                </form>
              </section>

              <section className="panel pipeline-panel">
                <div className="panel-heading">
                  <div>
                    <div className="panel-title"><GitBranch size={18} /> Analysis pipeline</div>
                    <div className="panel-subtitle">Your review workflow</div>
                  </div>
                </div>
                <div className="pipeline-list">
                  {[
                    ["01", "Code input", "Submit source code", Code2],
                    ["02", "Review & filtering", "Detect and prioritize issues", Search],
                    ["03", "AI repair", "Generate candidate patches", WandSparkles],
                    ["04", "Verification", "Validate generated changes", ShieldCheck],
                  ].map(([number, title, description, Icon], index) => (
                    <div className="pipeline-step" key={number}>
                      <div className="pipeline-number">{number}</div>
                      <div className="pipeline-icon"><Icon size={17} /></div>
                      <div className="pipeline-copy">
                        <strong>{title}</strong><span>{description}</span>
                      </div>
                      <span className="pipeline-state">
                        {result ? "Run" : index === 0 ? "Ready" : "Waiting"}
                      </span>
                    </div>
                  ))}
                </div>
                <div className="pipeline-footer">
                  <span className={`status-dot ${apiStatus}`} />
                  {apiStatus === "online" ? "Connected to FastAPI" : apiStatus === "offline" ? "Backend disconnected" : "Checking backend"}
                </div>
              </section>

              <section className="panel recent-panel">
                <div className="panel-heading">
                  <div>
                    <div className="panel-title"><FileCode2 size={18} /> Latest review</div>
                    <div className="panel-subtitle">Most recent response from the pipeline</div>
                  </div>
                  <button className="text-button" onClick={() => setActivePage("review")}>
                    View details <ArrowUpRight size={15} />
                  </button>
                </div>
                {result ? (
                  <div className="latest-result">
                    <div className="result-file"><FileCode2 size={17} /> {data?.file || filename}</div>
                    <div className="result-metrics">
                      <span><strong>{counts.issues_detected ?? 0}</strong> issues</span>
                      <span><strong>{repairs.length}</strong> repair records</span>
                      <span><strong>{summary.verified ?? 0}</strong> verified</span>
                    </div>
                    <div className="result-time">Last run: {lastRun}</div>
                  </div>
                ) : (
                  <div className="empty-state">
                    <div className="empty-icon"><Code2 size={23} /></div>
                    <strong>No review runs yet</strong>
                    <span>Submit your first code sample to see actual pipeline results here.</span>
                    <button className="subtle-button" onClick={() => setActivePage("review")}>Start a review <ArrowRight size={15} /></button>
                  </div>
                )}
              </section>
            </div>
          )}

          {activePage === "review" && (
            <div className="single-column">
              <section className="panel">
                <div className="panel-heading">
                  <div>
                    <div className="panel-title"><Code2 size={18} /> Submit source code</div>
                    <div className="panel-subtitle">The request is sent to POST /api/review</div>
                  </div>
                  <span className="language-tag">PYTHON</span>
                </div>
                <form onSubmit={runReview}>
                  <div className="input-row">
                    <label className="field-label">Filename
                      <input value={filename} onChange={(e) => setFilename(e.target.value)} required />
                    </label>
                    <label className="field-label attempts-field">Maximum attempts
                      <select value={maxAttempts} onChange={(e) => setMaxAttempts(e.target.value)}>
                        <option value={1}>1</option><option value={2}>2</option><option value={3}>3</option>
                      </select>
                    </label>
                  </div>
                  <div className="code-editor large-editor">
                    <div className="editor-toolbar"><div><span className="editor-dot" /> {filename}</div><span>Editable source</span></div>
                    <textarea spellCheck="false" value={code} onChange={(e) => setCode(e.target.value)} required />
                  </div>
                  {error && <div className="error-message"><AlertCircle size={16} />{error}</div>}
                  <div className="editor-actions">
                    <span className="helper-text">Python files only · Up to 100 KB</span>
                    <button className="primary-button" disabled={loading || !code.trim()}>
                      {loading ? <><LoaderCircle className="spin" size={17} /> Running pipeline...</> : <><Zap size={17} /> Analyze code</>}
                    </button>
                  </div>
                </form>
              </section>
              <section className="panel">
                <div className="panel-heading">
                  <div><div className="panel-title"><Search size={18} /> Review findings</div><div className="panel-subtitle">Findings returned by the actual pipeline</div></div>
                  <span className="count-tag">{findings.length} findings</span>
                </div>
                {findings.length ? (
                  <div className="findings-list">
                    {findings.map((finding, index) => (
                      <div className="finding" key={`${finding.file}-${finding.line}-${index}`}>
                        <div className={`severity ${finding.severity || "low"}`}>{finding.severity || "unknown"}</div>
                        <div className="finding-body">
                          <strong>{finding.description || "Finding description unavailable"}</strong>
                          <span>{finding.file || filename} · Line {finding.line ?? "—"} · {finding.category || "general"}</span>
                          {finding.suggested_fix_hint && <p>{finding.suggested_fix_hint}</p>}
                        </div>
                        <span className="confidence">{finding.confidence != null ? `${Math.round(finding.confidence * 100)}%` : "—"}</span>
                      </div>
                    ))}
                  </div>
                ) : (
                  <div className="empty-state compact">
                    <div className="empty-icon"><Search size={22} /></div>
                    <strong>{result ? "No findings returned" : "Waiting for a review"}</strong>
                    <span>{result ? "The pipeline completed but did not return actionable findings for this input." : "Run an analysis to populate this section."}</span>
                  </div>
                )}
                {data?.discarded?.length > 0 && <p className="muted-note">{data.discarded.length} additional finding(s) were filtered as noise.</p>}
              </section>
            </div>
          )}

          {activePage === "repairs" && (
            <section className="panel">
              <div className="panel-heading">
                <div><div className="panel-title"><WandSparkles size={18} /> AI-generated repairs</div><div className="panel-subtitle">Patch suggestions returned by the repair pipeline</div></div>
                <span className="count-tag">{repairs.length} repairs</span>
              </div>
              {repairs.length ? (
                <div className="repair-list">
                  {repairs.map((repair, index) => (
                    <article className="repair-card" key={index}>
                      <div className="repair-heading">
                        <strong>Repair {index + 1}</strong>
                        <span className={`repair-status ${repair.status}`}>{repair.status || "unknown"}</span>
                      </div>
                      <p>{repair.explanation || "No explanation supplied."}</p>
                      <div className="repair-meta">Attempts: {repair.attempts ?? "—"} · Verification: {repair.verification_stage || "—"}</div>
                      {repair.diff && <pre className="diff-block">{repair.diff}</pre>}
                      {repair.patched_code && <details><summary>View patched code</summary><pre className="diff-block">{repair.patched_code}</pre></details>}
                    </article>
                  ))}
                </div>
              ) : (
                <div className="empty-state">
                  <div className="empty-icon"><WandSparkles size={23} /></div>
                  <strong>{result ? "No repairs generated" : "No repair results yet"}</strong>
                  <span>Run a code review first. Any generated repair patches will appear here.</span>
                  <button className="subtle-button" onClick={() => setActivePage("review")}>Go to code review <ArrowRight size={15} /></button>
                </div>
              )}
            </section>
          )}

          {activePage === "verification" && (
            <section className="panel">
              <div className="panel-heading">
                <div><div className="panel-title"><ShieldCheck size={18} /> Verification results</div><div className="panel-subtitle">Verification summary from the pipeline response</div></div>
              </div>
              {result ? (
                <>
                  <div className="verification-grid">
                    <div className="verification-stat"><CheckCircle2 size={20} /><span>Verified</span><strong>{summary.verified ?? 0}</strong></div>
                    <div className="verification-stat"><XCircle size={20} /><span>Failed</span><strong>{summary.failed ?? 0}</strong></div>
                    <div className="verification-stat"><RefreshCw size={20} /><span>Retried</span><strong>{summary.retried ?? 0}</strong></div>
                  </div>
                  {repairs.length ? repairs.map((repair, index) => (
                    <div className="verification-row" key={index}>
                      <span>
                        {typeof repair.finding === "string"
                          ? repair.finding
                          : repair.finding?.description || `Repair ${index + 1}`}
                      </span>
                      <span className={`repair-status ${repair.status}`}>{repair.status || "unknown"}</span>
                      <span>Stage: {repair.verification_stage || "not reported"}</span>
                    </div>
                  )) : <div className="empty-state compact"><strong>No repair verification records</strong><span>The latest run returned no repair attempts to verify.</span></div>}
                </>
              ) : (
                <div className="empty-state">
                  <div className="empty-icon"><ShieldCheck size={23} /></div>
                  <strong>Verification has not run yet</strong>
                  <span>Run a code review to display the verification summary.</span>
                  <button className="subtle-button" onClick={() => setActivePage("review")}>Start a review <ArrowRight size={15} /></button>
                </div>
              )}
            </section>
          )}

          {result && (
            <div className={`response-banner ${result.success ? "success" : "warning"}`}>
              {result.success ? <CheckCircle2 size={16} /> : <AlertCircle size={16} />}
              <span>Latest API request {result.success ? "completed without reported pipeline errors" : "completed with pipeline errors"}.</span>
              {data?.pipeline_errors?.length > 0 && <span>{data.pipeline_errors.length} pipeline error(s)</span>}
            </div>
          )}

          <footer className="page-footer">
            <span>CodeInsight AI</span><span>AI-powered code review, repair & verification</span>
            <span>API: {apiStatus === "online" ? "Connected" : apiStatus === "offline" ? "Offline" : "Checking"}</span>
          </footer>
        </div>
      </main>
    </div>
  );
}

export default App;
