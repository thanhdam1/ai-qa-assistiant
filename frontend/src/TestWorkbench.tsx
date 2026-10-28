import { useState } from 'react'
import { AlertTriangle, ArrowUpRight, Check, CheckCircle2, ChevronRight, Download, FileSearch, FileSpreadsheet, Filter, Link2, ListChecks, Pencil, Search, X } from 'lucide-react'
import { api } from './api'
import { ReadinessRow, SuiteAssessment, TargetDecision } from './SuiteAssessment'
import { currentDecisions, hasDesignEvidence, isCaseReady, targetDescription, targetLabels, typeLabels } from './qaView'
import type { CoverageEntry, TestCase, TestContent, TestSet, TestType, Workspace } from './types'

type AssessmentProps = Parameters<typeof SuiteAssessment>[0]
type Props = {
  testSet: TestSet; workspace: Workspace; view: 'tests' | 'coverage'; busy: string
  onViewChange: (view: 'tests' | 'coverage') => void
  onSave: (content: TestContent) => Promise<void>; onApprove: () => Promise<void>
  onDecide: AssessmentProps['onDecide']; onAccept: AssessmentProps['onAccept']; onAssess: AssessmentProps['onAssess']
}

function Basis({ test }: { test: TestCase }) {
  return <span className={`classification classification-${test.basis}`}>{test.basis === 'requirement' ? 'Requirement' : 'Recommendation'}</span>
}

function TextList({ items, empty }: { items: string[]; empty: string }) {
  return items.length ? <ul className="evidence-list">{items.map((item, index) => <li key={index}>{item}</li>)}</ul> : <p className="muted">{empty}</p>
}

export function TestWorkbench({ testSet, workspace, view, busy, onViewChange, onSave, onApprove, onDecide, onAccept, onAssess }: Props) {
  const [query, setQuery] = useState('')
  const [type, setType] = useState<TestType | 'all'>('all')
  const [basis, setBasis] = useState('all')
  const [priority, setPriority] = useState('all')
  const [clarifications, setClarifications] = useState(false)
  const [gapOnly, setGapOnly] = useState(false)
  const [selectedCaseId, setSelectedCaseId] = useState<string | null>(() => window.matchMedia('(min-width: 1100px)').matches ? testSet.content.test_cases[0]?.id ?? null : null)
  const [selectedTarget, setSelectedTarget] = useState<string | null>(null)
  const [actor, setActor] = useState('')
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState('')
  const [editError, setEditError] = useState('')
  const cases = testSet.content.test_cases
  const rows = (testSet.content.coverage_matrix ?? []).filter(row => row.target_type !== 'category')
  const decisions = currentDecisions(testSet)
  const hasDecision = (row: CoverageEntry) => decisions.some(item => item.target_type === row.target_type && item.target_id === row.target_id)
  const unresolved = rows.filter(row => !hasDecision(row))
  const evidenceGaps = rows.filter(row => !hasDesignEvidence(row))
  const normalizedQuery = query.toLocaleLowerCase()
  const filteredCases = cases.filter(test => (type === 'all' || test.type === type) &&
    (basis === 'all' || test.basis === basis) && (priority === 'all' || test.priority === priority) &&
    (!clarifications || test.needs_clarification) &&
    [test.id, test.title, test.objective, ...test.requirement_traceability, ...(test.api_traceability ?? [])].join(' ').toLocaleLowerCase().includes(normalizedQuery))
  const filteredRows = rows.filter(row => (!gapOnly || !hasDesignEvidence(row)) &&
    [row.target_id, targetDescription(workspace, testSet, row.target_id), row.explanation, ...row.test_case_ids].join(' ').toLocaleLowerCase().includes(normalizedQuery))
  const selectedCase = filteredCases.find(test => test.id === selectedCaseId)
  const selectedRow = filteredRows.find(row => `${row.target_type}:${row.target_id}` === selectedTarget)
  const inspectorOpen = view === 'tests' ? Boolean(selectedCase) : Boolean(selectedRow)
  const selectedDecision = selectedRow && decisions.find(item => item.target_type === selectedRow.target_type && item.target_id === selectedRow.target_id)

  function focusInspector() {
    requestAnimationFrame(() => {
      const element = document.getElementById('evidence-title')
      element?.focus({ preventScroll: true })
      if (window.innerWidth < 1100) element?.scrollIntoView({ behavior: 'instant', block: 'start' })
    })
  }
  function selectCase(id: string) { setSelectedCaseId(id); focusInspector() }
  function selectTarget(row: CoverageEntry) { setSelectedTarget(`${row.target_type}:${row.target_id}`); focusInspector() }
  function openTarget(id: string) {
    setQuery(''); setGapOnly(false)
    const row = rows.find(item => item.target_id === id)
    setSelectedTarget(row ? `${row.target_type}:${row.target_id}` : null)
    onViewChange('coverage'); focusInspector()
  }
  function openCase(id: string) {
    setQuery(''); setType('all'); setBasis('all'); setPriority('all'); setClarifications(false)
    setSelectedCaseId(id); onViewChange('tests'); focusInspector()
  }
  function clearFilters() { setQuery(''); setType('all'); setBasis('all'); setPriority('all'); setClarifications(false); setGapOnly(false) }

  return <section className="test-workbench">
    <div className="workbench-heading">
      <div><h2>{view === 'tests' ? 'Test cases' : 'Coverage & bằng chứng'}</h2><p>{view === 'tests' ? 'Đọc kịch bản, đối chiếu nguồn và xác nhận điều kiện chạy.' : 'Kiểm tra assertion và quyết định xử lý từng khoảng trống.'}</p></div>
      <div className="toolbar-actions">
        <a className="button button-ghost" href={api.exportUrl('test-case-sets', testSet.id, 'xlsx')}><FileSpreadsheet size={15} /> Xuất Excel</a>
        <a className="button button-ghost" href={api.exportUrl('test-case-sets', testSet.id, 'csv')}><Download size={15} /> CSV</a>
        <a className="button button-ghost" href={api.exportUrl('test-case-sets', testSet.id, 'json')}>JSON</a>
        <button className="button button-ghost" disabled={Boolean(busy) || testSet.stale} onClick={() => { setDraft(JSON.stringify(testSet.content, null, 2)); setEditing(true); setEditError('') }}><Pencil size={15} /> Chỉnh sửa</button>
        {testSet.status !== 'approved' && <button className="button" disabled={Boolean(busy) || testSet.stale} onClick={() => void onApprove()}><Check size={16} /> Duyệt nội dung</button>}
      </div>
    </div>
    {testSet.stale && <div className="notice" role="status"><AlertTriangle size={18} /><span>Suite thuộc phiên bản nguồn cũ. Xem lịch sử hoặc sinh lại từ review hiện tại.</span></div>}
    {editing ? <div className="card json-editor"><h3>Chỉnh sửa test suite</h3><p>Lưu nội dung sẽ đưa suite về bản nháp và yêu cầu đánh giá lại coverage.</p><textarea aria-label="Nội dung test suite JSON" value={draft} rows={24} spellCheck={false} onChange={event => setDraft(event.target.value)} />{editError && <p role="alert" className="field-error">{editError}</p>}<div className="actions"><button className="button button-ghost" onClick={() => setEditing(false)}>Huỷ</button><button className="button" disabled={Boolean(busy)} onClick={async () => { try { const content = JSON.parse(draft) as TestContent; await onSave(content); setEditing(false) } catch (error) { setEditError(error instanceof SyntaxError ? 'JSON chưa hợp lệ. Kiểm tra lại dấu ngoặc và dấu phẩy.' : String(error)) } }}>Lưu nội dung</button></div></div> : <>
      {view === 'tests' && evidenceGaps.length > 0 && <button className="gap-callout" onClick={() => { setQuery(''); setGapOnly(true); onViewChange('coverage') }}>
        <span className="gap-icon"><AlertTriangle size={18} /></span><span><strong>{evidenceGaps.length} mục tiêu chưa có đủ assertion liên kết</strong><small>Xem khoảng trống trước khi chấp nhận phạm vi coverage.</small></span><ArrowUpRight size={18} />
      </button>}
      <div className="table-toolbar">
        <label className="search-field"><Search size={17} /><input value={query} onChange={event => setQuery(event.target.value)} placeholder={view === 'tests' ? 'Tìm test case, tiêu đề, requirement ID…' : 'Tìm mục tiêu, nguồn, test case…'} aria-label="Tìm trong bảng" />{query && <button title="Xoá tìm kiếm" onClick={() => setQuery('')}><X size={15} /></button>}</label>
        {view === 'tests' ? <>
          <label className="select-field"><span>Nguồn</span><select aria-label="Lọc nguồn test" value={basis} onChange={event => setBasis(event.target.value)}><option value="all">Tất cả</option><option value="requirement">Requirement</option><option value="recommendation">Recommendation</option></select></label>
          <label className="select-field"><span>Priority</span><select aria-label="Lọc priority" value={priority} onChange={event => setPriority(event.target.value)}><option value="all">Tất cả</option><option value="critical">Critical</option><option value="high">High</option><option value="medium">Medium</option><option value="low">Low</option></select></label>
          <button className={`filter-toggle ${clarifications ? 'active' : ''}`} aria-pressed={clarifications} onClick={() => setClarifications(!clarifications)}><Filter size={14} /> Cần làm rõ <span>{cases.filter(test => test.needs_clarification).length}</span></button>
        </> : <button className={`filter-toggle ${gapOnly ? 'active' : ''}`} aria-pressed={gapOnly} onClick={() => setGapOnly(!gapOnly)}><Filter size={14} /> Chỉ coverage gap <span>{evidenceGaps.length}</span></button>}
      </div>
      {view === 'tests' && <div className="type-filters" aria-label="Nhóm test">{(['all', 'positive', 'negative', 'boundary', 'integration'] as const).map(value => <button key={value} aria-pressed={type === value} className={type === value ? 'active' : ''} onClick={() => setType(value)}>{value === 'all' ? 'Tất cả test' : typeLabels[value]}<span>{value === 'all' ? cases.length : cases.filter(test => test.type === value).length}</span></button>)}</div>}
      <div className={`workbench-grid ${inspectorOpen ? 'with-inspector' : ''}`}>
        <div className="table-panel">
          <div className="table-scroll" tabIndex={0} aria-label={view === 'tests' ? 'Bảng test cases, cuộn ngang để xem thêm' : 'Bảng coverage'}>
            {view === 'tests' ? <table className="qa-table"><caption className="sr-only">Test cases của story {workspace.title}</caption><thead><tr><th scope="col">Test case</th><th scope="col">Loại / Priority</th><th scope="col">Traceability</th><th scope="col">Trạng thái</th></tr></thead>
              <tbody>{filteredCases.map(test => <tr key={test.id} className={selectedCase?.id === test.id ? 'selected-row' : ''}>
                <td><div className="case-meta"><code>{test.id}</code><Basis test={test} /></div><button className="case-title" onClick={() => selectCase(test.id)} aria-expanded={selectedCase?.id === test.id}>{test.title}<ChevronRight size={15} /></button></td>
                <td><span className={`type type-${test.type}`}>{typeLabels[test.type]}</span><span className={`priority-label priority-${test.priority}`}><i />{test.priority}</span></td>
                <td><button className="trace-count" title={[...test.requirement_traceability, ...(test.api_traceability ?? [])].join(', ')} onClick={() => selectCase(test.id)}><Link2 size={14} /> {test.requirement_traceability.length + (test.api_traceability ?? []).length} nguồn</button><small>{test.requirement_traceability[0] ?? test.api_traceability?.[0] ?? 'Thiếu liên kết'}</small></td>
                <td>{test.needs_clarification ? <span className="clarify">Cần làm rõ</span> : isCaseReady(testSet, test) ? <span className="ready">Sẵn sàng chạy</span> : <span className="neutral-status">Chờ điều kiện chạy</span>}</td>
              </tr>)}</tbody></table> :
              <table className="qa-table coverage-table"><caption className="sr-only">Coverage thiết kế theo từng mục tiêu</caption><thead><tr><th scope="col">Mục tiêu kiểm thử</th><th scope="col">Bằng chứng thiết kế</th><th scope="col">Quyết định QA</th></tr></thead><tbody>{filteredRows.map(row => {
                const decision = decisions.find(item => item.target_type === row.target_type && item.target_id === row.target_id)
                return <tr key={`${row.target_type}:${row.target_id}`} className={selectedRow === row ? 'selected-row' : ''}><td><div className="case-meta"><span className="target-kind">{targetLabels[row.target_type]}</span><code>{row.target_id}</code></div><button className="case-title" onClick={() => selectTarget(row)} aria-expanded={selectedRow === row}>{targetDescription(workspace, testSet, row.target_id) ?? row.explanation}<ChevronRight size={15} /></button></td><td><span className={hasDesignEvidence(row) ? 'ready' : 'clarify'}>{hasDesignEvidence(row) ? 'Có assertion' : 'Coverage gap'}</span><small>{row.test_case_ids.length} test liên kết · {row.assertion_evidence?.length ?? 0} assertion</small></td><td><span className={decision?.disposition === 'confirmed' ? 'ready' : decision ? 'neutral-status' : 'review-pending'}>{decision?.disposition === 'confirmed' ? 'QA xác nhận' : decision ? decision.disposition : 'Chưa quyết định'}</span>{decision && <small>{decision.decided_by}</small>}</td></tr>
              })}</tbody></table>}
          </div>
          {(view === 'tests' ? filteredCases.length : filteredRows.length) === 0 && <div className="table-empty"><Search size={25} /><h3>Không có kết quả phù hợp</h3><p>Thử tìm theo ID hoặc bỏ bớt bộ lọc.</p><button className="button button-ghost" onClick={clearFilters}>Xoá bộ lọc</button></div>}
          <div className="table-footer"><span>{view === 'tests' ? `${filteredCases.length} / ${cases.length} test cases` : `${filteredRows.length} / ${rows.length} mục tiêu`}</span><span>Chọn một hàng để kiểm tra bằng chứng</span></div>
        </div>
        {inspectorOpen && <section className="evidence-panel" aria-labelledby="evidence-title">
          <div className="evidence-heading"><div><FileSearch size={17} /><h3 id="evidence-title" tabIndex={-1}>Kiểm tra bằng chứng</h3></div><button className="icon-button" aria-label="Đóng bằng chứng" onClick={() => { setSelectedCaseId(null); setSelectedTarget(null) }}><X size={18} /></button></div>
          <div className="evidence-body">
            {view === 'tests' && selectedCase ? <>
              <div className="case-meta"><code>{selectedCase.id}</code><Basis test={selectedCase} /></div><h3 className="evidence-case-title">{selectedCase.title}</h3><p className="muted">{selectedCase.objective}</p>
              {selectedCase.needs_clarification && <div className="inline-warning"><AlertTriangle size={16} /><span>Clarification: cần xác nhận thông tin trước khi chạy.</span></div>}
              <section className="expected-result"><h4><CheckCircle2 size={16} /> Expected result</h4><p>{selectedCase.expected_result}</p></section>
              <section><h4><Link2 size={15} /> Traceability</h4>{[...selectedCase.requirement_traceability, ...(selectedCase.api_traceability ?? [])].map(id => <button key={id} className="source-link" onClick={() => openTarget(id)}><code>{id}</code><span>{targetDescription(workspace, testSet, id) ?? 'Không tìm thấy mô tả trong review nguồn'}</span><ArrowUpRight size={14} /></button>)}</section>
              <section><h4><ListChecks size={15} /> Steps & assertions</h4><ol className="step-list">{selectedCase.steps.map(step => <li key={step.order}><span className="step-number">{step.order}</span><div><p>{step.action}</p><blockquote>{step.expected_result}</blockquote></div></li>)}</ol></section>
              <details><summary>Preconditions & test data</summary><h4>Preconditions</h4><TextList items={selectedCase.preconditions} empty="Không yêu cầu." /><h4>Test data</h4><TextList items={selectedCase.test_data} empty="Chưa khai báo dữ liệu." /></details>
              {selectedCase.api_method && <details><summary>API request & response</summary><p><code>{selectedCase.api_method}</code> {selectedCase.api_path}</p><pre>{selectedCase.api_request}</pre><p>Status: {(selectedCase.expected_status_codes ?? []).join(', ') || 'Chưa xác nhận'}</p></details>}
              {selectedCase.assumptions.length > 0 && <details><summary>Assumptions ({selectedCase.assumptions.length})</summary><TextList items={selectedCase.assumptions} empty="" /></details>}
              <details className="decision-section"><summary>Đánh giá điều kiện chạy</summary><label className="actor-field">Người đánh giá<input value={actor} onChange={event => setActor(event.target.value)} placeholder="Tên QA" /><small>Danh tính tự khai trong MVP.</small></label><ReadinessRow key={selectedCase.id} test={selectedCase} current={testSet.stale ? undefined : testSet.case_readiness?.find(item => item.case_id === selectedCase.id && item.content_version === testSet.content_version)} actor={actor} disabled={Boolean(busy) || testSet.stale} onAssess={onAssess} /></details>
            </> : selectedRow ? <>
              <div className="case-meta"><span className="target-kind">{targetLabels[selectedRow.target_type]}</span><code>{selectedRow.target_id}</code></div><h3 className="evidence-case-title">{targetDescription(workspace, testSet, selectedRow.target_id) ?? 'Mục tiêu kiểm thử'}</h3><p className="muted">{selectedRow.explanation}</p>
              {!hasDesignEvidence(selectedRow) && <div className="inline-warning"><AlertTriangle size={16} /><span>Chưa đủ bằng chứng thiết kế. Liên kết ID chưa xác nhận test kiểm tra đầy đủ mục tiêu.</span></div>}
              <section><h4>Assertions được liên kết</h4>{selectedRow.assertion_evidence?.length ? selectedRow.assertion_evidence.map((item, index) => <div className="assertion-proof" key={index}><button className="text-button" onClick={() => openCase(item.test_case_id)}>{item.test_case_id}<ArrowUpRight size={14} /></button><blockquote>{item.assertion}</blockquote><small>{item.verifies_business_outcome ? 'Kỳ vọng kết quả nghiệp vụ' : 'Kiểm tra API / schema'}</small></div>) : <p className="empty-evidence">Chưa có assertion. QA cần kiểm tra traceability và Expected Result của các case liên quan.</p>}</section>
              {selectedRow.unverified_aspects?.length ? <section><h4>Phần chưa kiểm tra</h4><TextList items={selectedRow.unverified_aspects} empty="" /></section> : null}
              <section><h4>Test cases liên quan</h4><div className="linked-cases">{selectedRow.test_case_ids.map(id => <button key={id} className="button button-ghost" onClick={() => openCase(id)}>{id}<ArrowUpRight size={13} /></button>)}</div>{!selectedRow.test_case_ids.length && <p className="muted">Chưa có test liên kết với mục tiêu này.</p>}</section>
              <section className="decision-section"><h4>Quyết định QA</h4><label className="actor-field">Người quyết định<input value={actor} onChange={event => setActor(event.target.value)} placeholder="Tên QA" /><small>Danh tính tự khai. Gap không được tính là covered.</small></label><TargetDecision key={`${selectedRow.target_type}:${selectedRow.target_id}`} row={selectedRow} decision={selectedDecision} actor={actor} disabled={Boolean(busy) || testSet.stale} onDecide={onDecide} /></section>
            </> : null}
          </div>
        </section>}
      </div>
      {view === 'coverage' && <div className="coverage-acceptance">
        <div><strong>{testSet.coverage_acceptance_status === 'accepted' ? 'Phạm vi coverage đã được chấp nhận' : `${unresolved.length} mục tiêu chưa có quyết định QA`}</strong><p>Chấp nhận phạm vi cần nội dung đã duyệt và quyết định cho từng mục tiêu. Đây chưa phải kết quả thực thi.</p></div>
        <div className="acceptance-controls"><input aria-label="Người chấp nhận phạm vi" placeholder="Tên người chấp nhận" value={actor} onChange={event => setActor(event.target.value)} /><button className="button" disabled={Boolean(busy) || testSet.stale || testSet.review_status !== 'approved' || !actor.trim() || unresolved.length > 0 || testSet.coverage_acceptance_status === 'accepted'} onClick={() => void onAccept(actor.trim())}><Check size={15} /> Chấp nhận phạm vi</button></div>
      </div>}
    </>}
  </section>
}
