import { ButtonRow, NumberInput, Panel, Select, SettingRow, Toggle, settingsRequest, useRemoteSettings } from './SettingsPanelPrimitives';
import './KnowledgeBaseSettingsPanel.css';

const defaults = {
  embedding_provider: 'OpenAI',
  vector_db: 'FAISS',
  chunk_size: 900,
  chunk_overlap: 120,
  retrieval_mode: 'Hybrid',
  retrieval_top_k: 5,
  reranker: true,
  citations: true,
  citation_strict_mode: false,
  minimum_confidence_threshold: 0.2,
  auto_reindex: true,
};

export default function KnowledgeBaseSettingsPanel({ API }) {
  const { settings, update, loading, status, setStatus, save } = useRemoteSettings(API, '/settings/knowledge-base', defaults);

  const rebuildIndex = async () => {
    try {
      const data = await settingsRequest(API, '/settings/knowledge-base/rebuild-index', { method: 'POST', body: JSON.stringify({}) });
      setStatus(data.message || 'Rebuild queued');
    } catch (error) {
      setStatus(error.message || 'Rebuild failed');
    }
  };

  const deleteIndexedDocs = async () => {
    if (!window.confirm('Delete indexed documents for this workspace?')) return;
    try {
      const data = await settingsRequest(API, '/settings/knowledge-base/indexed-docs', { method: 'DELETE' });
      setStatus(data.message || 'Delete queued');
    } catch (error) {
      setStatus(error.message || 'Delete failed');
    }
  };

  return (
    <>
      <Panel title="Retrieval Defaults" subtitle="These settings control future indexing and retrieval behavior.">
        <SettingRow title="Embedding provider" detail="Provider for embedding generation.">
          <Select value={settings.embedding_provider} options={['OpenAI', 'HuggingFace', 'Local']} onChange={(value) => update('embedding_provider', value)} />
        </SettingRow>
        <SettingRow title="Vector DB" detail="Storage backend for chunk vectors.">
          <Select value={settings.vector_db} options={['FAISS', 'Chroma', 'Pinecone', 'Qdrant']} onChange={(value) => update('vector_db', value)} />
        </SettingRow>
        <SettingRow title="Chunk size" detail="Characters per chunk.">
          <NumberInput value={settings.chunk_size} min={128} max={8000} onChange={(value) => update('chunk_size', value)} />
        </SettingRow>
        <SettingRow title="Chunk overlap" detail="Characters repeated between adjacent chunks.">
          <NumberInput value={settings.chunk_overlap} min={0} max={2000} onChange={(value) => update('chunk_overlap', value)} />
        </SettingRow>
        <SettingRow title="Retrieval mode" detail="Choose vectorless keyword search, vector search, or hybrid retrieval.">
          <Select value={settings.retrieval_mode} options={['Vectorless', 'Vector', 'Hybrid']} onChange={(value) => update('retrieval_mode', value)} />
        </SettingRow>
        <SettingRow title="Retrieval top-k" detail="Number of chunks retrieved for each answer.">
          <NumberInput value={settings.retrieval_top_k} min={1} max={50} onChange={(value) => update('retrieval_top_k', value)} />
        </SettingRow>
        <SettingRow title="Reranker" detail="Run a second ranking pass over retrieved chunks.">
          <Toggle checked={!!settings.reranker} onChange={(value) => update('reranker', value)} />
        </SettingRow>
        <SettingRow title="Citation strict mode" detail="Require stronger evidence before retrieved chunks can be cited.">
          <Toggle checked={!!settings.citation_strict_mode} onChange={(value) => update('citation_strict_mode', value)} />
        </SettingRow>
        <SettingRow title="Minimum confidence" detail="Discard chunks below this source confidence score.">
          <NumberInput value={settings.minimum_confidence_threshold} min={0} max={1} step={0.05} onChange={(value) => update('minimum_confidence_threshold', value)} />
        </SettingRow>
        <SettingRow title="Citations" detail="Show source references when answers use RAG context.">
          <Toggle checked={!!settings.citations} onChange={(value) => update('citations', value)} />
        </SettingRow>
        <SettingRow title="Auto-reindex" detail="Rebuild affected indexes after content updates.">
          <Toggle checked={!!settings.auto_reindex} onChange={(value) => update('auto_reindex', value)} />
        </SettingRow>
      </Panel>

      <ButtonRow status={loading ? 'Working...' : status}>
        <button type="button" className="eva-settings-button danger" onClick={deleteIndexedDocs}>Delete indexed docs</button>
        <button type="button" className="eva-settings-button" onClick={rebuildIndex}>Rebuild index</button>
        <button type="button" className="eva-settings-button primary" onClick={() => save(settings)}>Save knowledge base</button>
      </ButtonRow>
    </>
  );
}
