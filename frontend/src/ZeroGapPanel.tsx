import { useState } from 'react'
import {
  AlertTriangle,
  ArrowRight,
  CheckCircle2,
  Code2,
  Cpu,
  FileCode,
  FileSpreadsheet,
  Flame,
  Layers,
  ListChecks,
  LoaderCircle,
  RefreshCw,
  ShieldAlert,
  ShieldCheck,
  Sparkles,
  Zap,
} from 'lucide-react'
import { api } from './api'
import type {
  CanonicalTestContract,
  DetailedTestCase,
  GapForQA,
  Workspace,
  ZeroGapSuiteResponse,
} from './types'

export function ZeroGapPanel({
  workspace,
  busy,
  setBusy,
}: {
  workspace: Workspace
  busy: string
  setBusy: (v: string) => void
}) {
  const [mode, setMode] = useState<'2-way' | '3-way'>('2-way')
  const [sourceCode, setSourceCode] = useState('')
  const [contract, setContract] = useState<CanonicalTestContract | null>(null)
  const [suite, setSuite] = useState<ZeroGapSuiteResponse | null>(null)
  const [error, setError] = useState('')
  const [selectedCase, setSelectedCase] = useState<DetailedTestCase | null>(null)
  const [exportingExcel, setExportingExcel] = useState(false)

  async function handleExtractContract() {
    setError('')
    setBusy('zero-gap-contract')
    try {
      const res = await api.getZeroGapContract(
        workspace.id,
        mode === '3-way' ? sourceCode : undefined
      )
      setContract(res)
    } catch (e: any) {
      setError(e.message || String(e))
    } finally {
      setBusy('')
    }
  }

  async function handleGenerateSuite() {
    setError('')
    setBusy('zero-gap-generate')
    try {
      const res = await api.generateZeroGapSuite(
        workspace.id,
        mode === '3-way' ? sourceCode : undefined
      )
      setSuite(res)
      if (res.test_cases.length > 0) {
        setSelectedCase(res.test_cases[0])
      }
    } catch (e: any) {
      setError(e.message || String(e))
    } finally {
      setBusy('')
    }
  }

  async function handleExportExcel() {
    if (!suite) return
    setExportingExcel(true)
    setError('')
    try {
      await api.exportZeroGapSuiteExcel(workspace.id, suite)
    } catch (e: any) {
      setError(e.message || String(e))
    } finally {
      setExportingExcel(false)
    }
  }

  function handleFileUpload(event: React.ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0]
    if (file) {
      const reader = new FileReader()
      reader.onload = e => {
        setSourceCode(String(e.target?.result || ''))
        setMode('3-way')
      }
      reader.readAsText(file)
    }
  }

  return (
    <div className="card zero-gap-panel">
      <div className="card-heading">
        <div>
          <span className="eyebrow">Zero-Gap v2.0 Engine · Mathematical Coverage Gate</span>
          <h2>Zero-Gap 100% Test Generation</h2>
        </div>
        <span className="badge badge-approved">
          <Zap size={12} /> Adaptive {mode.toUpperCase()}
        </span>
      </div>

      <p className="coverage">
        Bộ xử lý tất định kết hợp <b>Atomic Requirement Decomposer</b>,{' '}
        <b>8-Partition BVA Matrix</b>, <b>AST Control-Flow Graph V(G)</b> và{' '}
        <b>Circuit Breaker Human-in-the-Loop</b>. Đảm bảo triệt tiêu hoàn toàn hiện tượng ảo giác và bỏ sót test case.
      </p>

      {error && (
        <div className="notice" role="alert">
          <AlertTriangle size={18} />
          <span>{error}</span>
          <button onClick={() => setError('')}>×</button>
        </div>
      )}

      {/* Mode Selection */}
      <div className="zg-mode-selector">
        <button
          type="button"
          className={`zg-mode-btn ${mode === '2-way' ? 'active' : ''}`}
          onClick={() => setMode('2-way')}
        >
          <Layers size={16} />
          <div>
            <strong>Adaptive 2-Way (Mặc định)</strong>
            <small>Story (Atomic REQ) ↔ OpenAPI (8 Phân vùng BVA)</small>
          </div>
        </button>

        <button
          type="button"
          className={`zg-mode-btn ${mode === '3-way' ? 'active' : ''}`}
          onClick={() => setMode('3-way')}
        >
          <Code2 size={16} />
          <div>
            <strong>Adaptive 3-Way (+ AST Codebase)</strong>
            <small>Story ↔ OpenAPI ↔ Source Code AST CFG V(G)</small>
          </div>
        </button>
      </div>

      {/* 3-Way Mode Source Code Input */}
      {mode === '3-way' && (
        <div className="zg-source-box">
          <div className="zg-source-header">
            <label>
              <FileCode size={15} /> <b>Mã nguồn hàm/module backend cần kiểm thử (Python, TS, Java):</b>
            </label>
            <label className="button button-ghost zg-upload-btn">
              <span>Tải file mã nguồn (.py)</span>
              <input type="file" accept=".py,.txt,.ts,.js,.java" onChange={handleFileUpload} style={{ display: 'none' }} />
            </label>
          </div>
          <textarea
            rows={7}
            value={sourceCode}
            onChange={e => setSourceCode(e.target.value)}
            placeholder="Dán mã nguồn hàm backend vào đây (ví dụ hàm xử lý request, service logic với các nhánh if/else/try-except)..."
          />
        </div>
      )}

      {/* Action Buttons */}
      <div className="actions split zg-actions">
        <div>
          <button
            type="button"
            className="button button-ghost"
            disabled={Boolean(busy)}
            onClick={handleExtractContract}
          >
            {busy === 'zero-gap-contract' ? <LoaderCircle className="spin" size={16} /> : <Cpu size={16} />}
            Trích xuất Canonical Contract
          </button>
        </div>

        <div>
          <button
            type="button"
            className="button button-primary zg-generate-btn"
            disabled={Boolean(busy)}
            onClick={handleGenerateSuite}
          >
            {busy === 'zero-gap-generate' ? <LoaderCircle className="spin" size={17} /> : <Sparkles size={17} />}
            Sinh Zero-Gap Suite (100% Phủ)
          </button>
        </div>
      </div>

      {/* Contract Preview (if extracted) */}
      {contract && !suite && (
        <div className="zg-contract-summary">
          <div className="section-title">
            <h3>Mẫu số Hợp đồng Cần Phủ (Canonical Test Contract)</h3>
            <span>Chế độ: {contract.mode}</span>
          </div>
          <div className="zg-metric-grid">
            <div className="zg-metric-card">
              <span className="num">{contract.requirements.length}</span>
              <span className="lbl">Mệnh đề Atomic REQ</span>
            </div>
            <div className="zg-metric-card">
              <span className="num">{contract.bva_matrix.length}</span>
              <span className="lbl">Mốc biên BVA (8 phân vùng)</span>
            </div>
            <div className="zg-metric-card">
              <span className="num">{contract.ast_branches.length}</span>
              <span className="lbl">Nhánh AST Code</span>
            </div>
            <div className="zg-metric-card">
              <span className="num">V(G) = {contract.cyclomatic_complexity}</span>
              <span className="lbl">Độ phức tạp chu trình</span>
            </div>
          </div>
          {contract.spec_conflicts.length > 0 && (
            <div className="zg-conflicts">
              <h4>
                <ShieldAlert size={16} /> Xung đột Spec / Shadow Logic phát hiện ({contract.spec_conflicts.length})
              </h4>
              <ul>
                {contract.spec_conflicts.map((c, i) => (
                  <li key={i}>{c}</li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}

      {/* Generated Zero-Gap Suite Results */}
      {suite && (
        <div className="zg-suite-results">
          {/* Coverage Gate Banner */}
          <div className="zg-coverage-banner">
            <div className="zg-banner-left">
              <ShieldCheck size={36} className="zg-banner-icon" />
              <div>
                <h3>
                  {suite.effective_coverage_pct.toFixed(1)}% Mathematical Coverage Gate
                </h3>
                <p>
                  Đã kiểm chứng toán học qua ma trận 2 Pha (Skeleton Matrix & Batch Expansion).
                  Vòng lặp bù đắp (Self-Healing): {suite.retries_used} lượt retry.
                </p>
              </div>
            </div>
            <div className="zg-banner-stat">
              <span className="stat-count">{suite.test_cases.length}</span>
              <span className="stat-label">Zero-Gap Test Cases</span>
              <button
                type="button"
                className="button zg-excel-btn"
                disabled={exportingExcel}
                onClick={handleExportExcel}
                title="Xuất kịch bản test case và ma trận độ phủ ra Excel (.xlsx)"
              >
                {exportingExcel ? <LoaderCircle className="spin" size={14} /> : <FileSpreadsheet size={14} />}
                Xuất Excel
              </button>
            </div>
          </div>

          {/* Gaps for QA / Circuit Breaker Banner (if any) */}
          {suite.gaps_for_qa.length > 0 && (
            <div className="zg-gaps-card">
              <h4>
                <AlertTriangle size={17} /> Điểm nghẽn bàn giao cho QA / Circuit Breaker ({suite.gaps_for_qa.length})
              </h4>
              <p className="muted">
                Các mục xung đột hoặc chưa thể tự động hóa đã được Circuit Breaker ngắt an toàn và chuyển sang Human-in-the-Loop:
              </p>
              <div className="zg-gaps-list">
                {suite.gaps_for_qa.map((gap, idx) => (
                  <div key={idx} className="zg-gap-row">
                    <span className="badge badge-draft">{gap.gap_type}</span>
                    <code>{gap.target_id}</code>
                    <span className="reason">{gap.reason}</span>
                    <span className="clarify">Cần QA làm rõ</span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Detailed Test Cases Explorer */}
          <div className="zg-test-explorer">
            <div className="zg-cases-sidebar">
              <h4>Danh sách Test Cases ({suite.test_cases.length})</h4>
              <div className="zg-cases-scroll">
                {suite.test_cases.map(tc => (
                  <button
                    key={tc.test_case_id}
                    type="button"
                    className={`zg-case-item ${selectedCase?.test_case_id === tc.test_case_id ? 'active' : ''}`}
                    onClick={() => setSelectedCase(tc)}
                  >
                    <div>
                      <code>{tc.test_case_id}</code>
                      <span className={`type type-${tc.category.toLowerCase()}`}>{tc.category}</span>
                    </div>
                    <strong>{tc.title}</strong>
                  </button>
                ))}
              </div>
            </div>

            {selectedCase && (
              <div className="zg-case-detail">
                <div className="zg-case-detail-header">
                  <div>
                    <code>{selectedCase.test_case_id}</code>
                    <span className={`type type-${selectedCase.category.toLowerCase()}`}>{selectedCase.category}</span>
                    <span className="ready">{selectedCase.resolution_status}</span>
                  </div>
                  <h3>{selectedCase.title}</h3>
                </div>

                <div className="zg-detail-section">
                  <h4>Mục tiêu đã phủ (Traceability)</h4>
                  <div className="zg-trace-badges">
                    {selectedCase.covered_req_ids.map(id => (
                      <span key={id} className="badge badge-approved">REQ: {id}</span>
                    ))}
                    {selectedCase.covered_bva_ids.map(id => (
                      <span key={id} className="badge badge-draft">BVA: {id}</span>
                    ))}
                    {selectedCase.covered_ast_ids.map(id => (
                      <span key={id} className="badge badge-stale">AST: {id}</span>
                    ))}
                  </div>
                </div>

                <div className="zg-detail-section">
                  <h4>Các bước thực hiện (Test Steps)</h4>
                  <ol className="step-list">
                    {selectedCase.test_steps.map((step, idx) => (
                      <li key={idx}>
                        <div><p>{step}</p></div>
                      </li>
                    ))}
                  </ol>
                </div>

                {Object.keys(selectedCase.test_data_payload).length > 0 && (
                  <div className="zg-detail-section">
                    <h4>Test Data Payload</h4>
                    <pre className="zg-code-block">
                      {JSON.stringify(selectedCase.test_data_payload, null, 2)}
                    </pre>
                  </div>
                )}

                <div className="zg-detail-section">
                  <h4>Kết quả mong đợi (Expected Result)</h4>
                  <blockquote>
                    <b>HTTP Status: {selectedCase.expected_http_status}</b>
                    <p>{selectedCase.expected_result}</p>
                  </blockquote>
                </div>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
