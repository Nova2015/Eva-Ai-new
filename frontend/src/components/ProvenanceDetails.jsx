// The RAG audit panel — retrieval mode, confidence, sources, audit id.
//
// Extracted from Chat.js so the provenance rule is enforceable by a test.
// Inline in a four-thousand-line page component it could only be checked by
// reading the code or by loading a signed-in browser session; here a future
// refactor that un-gates it fails the build instead of shipping.
//
// The rule: never rendered by default. `show` is set on a single message, the
// one the user asked about, and nothing else turns it on.
export default function ProvenanceDetails({ show, ragAudit }) {
  if (!show || !ragAudit) return null;

  const sourceIds = Array.isArray(ragAudit.sourceIds) ? ragAudit.sourceIds : [];

  return (
    <details className="eva-rag-audit-panel" open>
      <summary>
        <span>RAG audit</span>
        <span>{ragAudit.mode}</span>
        <span>{Math.round((Number(ragAudit.confidence) || 0) * 100)}% confidence</span>
        <span>{sourceIds.length} sources</span>
      </summary>
      <div className="eva-rag-audit-grid">
        {ragAudit.rewrittenQuery && (
          <div>
            <strong>Query</strong>
            <span>{ragAudit.rewrittenQuery}</span>
          </div>
        )}
        {ragAudit.auditId && (
          <div>
            <strong>Audit ID</strong>
            <span>{ragAudit.auditId}</span>
          </div>
        )}
        {!!sourceIds.length && (
          <div>
            <strong>Sources</strong>
            <span>{sourceIds.slice(0, 4).join(', ')}</span>
          </div>
        )}
        {ragAudit.channels && Object.keys(ragAudit.channels).length > 0 && (
          <div>
            <strong>Retrieval</strong>
            <span>{Object.entries(ragAudit.channels).map(([key, value]) => `${key}: ${value}`).join(' / ')}</span>
          </div>
        )}
      </div>
    </details>
  );
}
