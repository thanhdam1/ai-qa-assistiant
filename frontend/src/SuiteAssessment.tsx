import { useState, useEffect } from 'react'
import type { CaseReadiness, CoverageDecision, CoverageEntry, GapDisposition, TestCase, TestSet } from './types'

type DecisionInput = Pick<CoverageDecision, 'target_type' | 'target_id' | 'disposition' | 'decided_by' | 'assertion_case_id' | 'assertion' | 'reason' | 'owner'>
type ReadinessInput = Pick<CaseReadiness, 'assessed_by' | 'environment_ready' | 'test_data_ready' | 'verification_ready' | 'note'>

export function TargetDecision({ row, decision, actor, disabled, onDecide }: {
  row: CoverageEntry; decision?: CoverageDecision; actor: string; disabled: boolean
  onDecide: (input: DecisionInput) => Promise<void>
}) {
  const evidence = row.assertion_evidence ?? []
  const [disposition, setDisposition] = useState<GapDisposition>(decision?.disposition ?? (row.status === 'covered' && evidence.length ? 'confirmed' : 'blocked'))
  const [selected, setSelected] = useState(String(Math.max(0, evidence.findIndex(item => item.test_case_id === decision?.assertion_case_id && item.assertion === decision?.assertion))))
  const [reason, setReason] = useState(decision?.reason ?? '')
  const [owner, setOwner] = useState(decision?.owner ?? '')
  const [saving, setSaving] = useState(false)
  const [justSaved, setJustSaved] = useState(false)
  const [errorMsg, setErrorMsg] = useState('')

  useEffect(() => {
    if (decision) {
      setDisposition(decision.disposition)
      setReason(decision.reason ?? '')
      setOwner(decision.owner ?? '')
      if (decision.assertion_case_id) {
        const idx = evidence.findIndex(item => item.test_case_id === decision.assertion_case_id && item.assertion === decision.assertion)
        if (idx >= 0) setSelected(String(idx))
      }
    }
  }, [decision, evidence])

  const choice = evidence[Number(selected)]
  const canConfirm = row.status === 'covered' && evidence.length > 0 && !row.unverified_aspects?.length

  const handleDecide = async () => {
    if (disabled || saving || !actor.trim()) return
    setSaving(true)
    setErrorMsg('')
    try {
      await onDecide({
        target_type: row.target_type, target_id: row.target_id, disposition, decided_by: actor.trim(),
        assertion_case_id: disposition === 'confirmed' ? choice.test_case_id : null,
        assertion: disposition === 'confirmed' ? choice.assertion : null,
        reason: disposition === 'confirmed' ? null : reason.trim(), owner: disposition === 'deferred' ? owner.trim() : null,
      })
      setJustSaved(true)
      setTimeout(() => setJustSaved(false), 3000)
    } catch (err) {
      setErrorMsg(err instanceof Error ? err.message : 'Lỗi khi lưu quyết định')
    } finally {
      setSaving(false)
    }
  }

  const isInvalid = !actor.trim() || (disposition === 'confirmed' ? !canConfirm || !choice : !reason.trim() || (disposition === 'deferred' && !owner.trim()))

  return <div className="assessment-target">
    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '8px', flexWrap: 'wrap' }}>
      <div>
        <strong>{row.target_type} · {row.target_id}</strong>
        <span>{decision ? ` · ${decision.disposition} (${decision.decided_by})` : ' · Chưa có quyết định'}</span>
      </div>
      {justSaved && <span style={{ color: '#16a34a', fontWeight: 600, fontSize: '11.5px' }}>✓ Đã lưu quyết định</span>}
    </div>
    <small>{row.explanation}</small>
    <div className="assessment-controls">
      <select value={disposition} onChange={event => setDisposition(event.target.value as GapDisposition)} disabled={disabled || saving} aria-label={`Quyết định ${row.target_id}`}>
        {canConfirm && <option value="confirmed">Xác nhận assertion</option>}
        <option value="blocked">Bị chặn — blocked</option><option value="deferred">Bổ sung sau — deferred</option>
        <option value="accepted_risk">Chấp nhận rủi ro</option><option value="not_applicable">Không áp dụng</option>
      </select>
      {disposition === 'confirmed' && <select value={selected} onChange={event => setSelected(event.target.value)} disabled={disabled || saving} aria-label={`Assertion ${row.target_id}`}>
        {evidence.map((item, index) => <option key={`${item.test_case_id}-${index}`} value={String(index)}>{item.test_case_id}: {item.assertion}</option>)}
      </select>}
      {disposition !== 'confirmed' && <input value={reason} onChange={event => setReason(event.target.value)} disabled={disabled || saving} placeholder="Lý do xử lý gap" aria-label={`Lý do ${row.target_id}`} />}
      {disposition === 'deferred' && <input value={owner} onChange={event => setOwner(event.target.value)} disabled={disabled || saving} placeholder="Người phụ trách" aria-label={`Owner ${row.target_id}`} />}
      <button
        type="button"
        className={justSaved ? 'button-saved' : ''}
        style={{ minWidth: '100px', cursor: (disabled || saving || isInvalid) ? 'not-allowed' : 'pointer' }}
        disabled={disabled || saving || isInvalid}
        onClick={() => void handleDecide()}
      >
        {saving ? 'Đang lưu...' : justSaved ? '✓ Đã lưu' : 'Lưu quyết định'}
      </button>
    </div>
    {errorMsg && <small style={{ color: '#dc2626', display: 'block', marginTop: '4px' }}>{errorMsg}</small>}
  </div>
}

export function ReadinessRow({ test, current, actor, disabled, onAssess }: {
  test: TestCase; current?: CaseReadiness; actor: string; disabled: boolean
  onAssess: (caseId: string, input: ReadinessInput) => Promise<void>
}) {
  const [environment, setEnvironment] = useState(current?.environment_ready ?? false)
  const [data, setData] = useState(current?.test_data_ready ?? false)
  const [verification, setVerification] = useState(current?.verification_ready ?? false)
  const [note, setNote] = useState(current?.note ?? '')
  const [saving, setSaving] = useState(false)
  const [justSaved, setJustSaved] = useState(false)
  const [errorMsg, setErrorMsg] = useState('')

  useEffect(() => {
    setEnvironment(current?.environment_ready ?? false)
    setData(current?.test_data_ready ?? false)
    setVerification(current?.verification_ready ?? false)
    setNote(current?.note ?? '')
  }, [current])

  const ready = Boolean(current?.environment_ready && current?.test_data_ready && current?.verification_ready && !test.needs_clarification)
  const currentCount = [current?.environment_ready, current?.test_data_ready, current?.verification_ready].filter(Boolean).length
  const isClarificationBlocked = Boolean(test.needs_clarification && environment && data && verification)

  const handleSave = async () => {
    if (disabled || saving || !actor.trim()) return
    setSaving(true)
    setErrorMsg('')
    try {
      await onAssess(test.id, {
        assessed_by: actor.trim(),
        environment_ready: environment,
        test_data_ready: data,
        verification_ready: verification,
        note: note.trim() || null,
      })
      setJustSaved(true)
      setTimeout(() => setJustSaved(false), 3000)
    } catch (err) {
      setErrorMsg(err instanceof Error ? err.message : 'Lỗi khi lưu điều kiện chạy')
    } finally {
      setSaving(false)
    }
  }

  return <div className="assessment-target">
    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '8px', flexWrap: 'wrap' }}>
      <div>
        <strong>
          {test.id} ·{' '}
          {ready ? (
            <span className="badge badge-approved" style={{ fontSize: '11px' }}>🟢 Sẵn sàng chạy (3/3)</span>
          ) : test.needs_clarification ? (
            <span className="badge badge-stale" style={{ fontSize: '11px' }}>⚠ Cần làm rõ test case</span>
          ) : current && (current.environment_ready || current.test_data_ready || current.verification_ready || current.note) ? (
            <span className="badge badge-draft" style={{ fontSize: '11px' }}>🟡 Đang chuẩn bị ({currentCount}/3)</span>
          ) : (
            <span className="badge" style={{ fontSize: '11px', background: '#f1f5f9', color: '#64748b' }}>⚪ Chưa xác nhận điều kiện</span>
          )}
        </strong>
      </div>
      {justSaved && (
        <span style={{ fontSize: '11.5px', fontWeight: 600, color: '#16a34a' }}>
          ✓ Đã lưu thành công!
        </span>
      )}
    </div>

    {current?.assessed_by && (
      <div style={{ margin: '5px 0', fontSize: '11.5px', color: '#166534', background: '#f0fdf4', border: '1px solid #bbf7d0', borderRadius: '6px', padding: '4px 8px' }}>
        ✓ Đã lưu bởi <b>{current.assessed_by}</b>
        {current.assessed_at && ` lúc ${new Date(current.assessed_at).toLocaleTimeString('vi-VN', { hour: '2-digit', minute: '2-digit' })}`}
        {current.note && <span> — Ghi chú: <em>"{current.note}"</em></span>}
        <span style={{ marginLeft: '6px', color: '#15803d' }}>
          ({[current.environment_ready && 'Môi trường', current.test_data_ready && 'Test data', current.verification_ready && 'Cách xác minh'].filter(Boolean).join(', ') || 'Chưa chọn điều kiện'})
        </span>
      </div>
    )}

    <div className="assessment-controls">
      <label><input type="checkbox" checked={environment} onChange={event => setEnvironment(event.target.checked)} disabled={disabled || saving} /> Môi trường</label>
      <label><input type="checkbox" checked={data} onChange={event => setData(event.target.checked)} disabled={disabled || saving} /> Test data</label>
      <label><input type="checkbox" checked={verification} onChange={event => setVerification(event.target.checked)} disabled={disabled || saving} /> Cách xác minh</label>
      <input value={note} onChange={event => setNote(event.target.value)} disabled={disabled || saving} placeholder="Ghi chú điều kiện chạy" aria-label={`Ghi chú ${test.id}`} />
      <button
        type="button"
        className={justSaved ? 'button-saved' : ''}
        style={{ minWidth: '70px', padding: '6px 14px', fontSize: '12px', cursor: (disabled || saving || !actor.trim() || isClarificationBlocked) ? 'not-allowed' : 'pointer' }}
        disabled={disabled || saving || !actor.trim() || isClarificationBlocked}
        onClick={() => void handleSave()}
      >
        {saving ? 'Đang lưu...' : justSaved ? '✓ Đã lưu' : 'Lưu'}
      </button>
    </div>

    {!actor.trim() && (
      <small style={{ color: '#b45309', display: 'block', marginTop: '4px', fontSize: '11px' }}>
        * Vui lòng nhập "Người đánh giá" ở ô phía trên để lưu.
      </small>
    )}
    {isClarificationBlocked && (
      <small style={{ color: '#dc2626', display: 'block', marginTop: '4px', fontSize: '11px' }}>
        * Test case cần làm rõ, không thể đánh giá sẵn sàng cả 3 điều kiện.
      </small>
    )}
    {errorMsg && (
      <small style={{ color: '#dc2626', display: 'block', marginTop: '4px', fontSize: '11px' }}>
        {errorMsg}
      </small>
    )}
  </div>
}

export function SuiteAssessment({ testSet, busy, onDecide, onAccept, onAssess }: {
  testSet: TestSet; busy: boolean; onDecide: (input: DecisionInput) => Promise<void>
  onAccept: (actor: string) => Promise<void>; onAssess: (caseId: string, input: ReadinessInput) => Promise<void>
}) {
  const [actor, setActor] = useState(() => localStorage.getItem('qa-compass-actor') || '')
  const targets = (testSet.content.coverage_matrix ?? []).filter(item => item.target_type !== 'category')
  const decisions = (testSet.coverage_decisions ?? []).filter(item => item.story_version === testSet.story_version && item.content_version === testSet.content_version)
  const resolved = targets.filter(item => decisions.some(decision => decision.target_type === item.target_type && decision.target_id === item.target_id))
  const runnable = (testSet.case_readiness ?? []).filter(item => item.story_version === testSet.story_version && item.content_version === testSet.content_version && item.environment_ready && item.test_data_ready && item.verification_ready && testSet.content.test_cases.some(test => test.id === item.case_id && !test.needs_clarification))

  const handleActorChange = (val: string) => {
    setActor(val)
    localStorage.setItem('qa-compass-actor', val)
  }

  return <section className="suite-assessment">
    <h3>Quyết định QA cho suite</h3>
    <p><b>Nội dung:</b> {testSet.review_status === 'approved' ? 'Đã duyệt' : 'Bản nháp'} · <b>Coverage thiết kế:</b> {testSet.coverage_status} · <b>Chấp nhận phạm vi:</b> {testSet.coverage_acceptance_status} · <b>Khả năng chạy:</b> {testSet.execution_readiness}</p>
    <p>{testSet.candidate_coverage_count}/{testSet.coverage_target_count} mục tiêu có assertion liên kết trong bản thiết kế; QA xác nhận {testSet.qa_confirmed_target_count}; {testSet.gap_decision_count} quyết định gap. Liên kết assertion chưa chứng minh hệ thống đáp ứng yêu cầu; công cụ chưa chạy test.</p>
    <label>Người quyết định (tự khai; MVP chưa xác minh danh tính) <input value={actor} onChange={event => handleActorChange(event.target.value)} placeholder="Tên QA" /></label>
    <details><summary>Đánh giá từng mục tiêu · {resolved.length}/{targets.length} đã có quyết định</summary>
      {targets.map(row => <TargetDecision key={`${testSet.id}-${testSet.content_version}-${row.target_type}-${row.target_id}`} row={row} decision={decisions.find(item => item.target_type === row.target_type && item.target_id === row.target_id)} actor={actor} disabled={busy || testSet.stale} onDecide={onDecide} />)}
      <button type="button" disabled={busy || testSet.stale || testSet.review_status !== 'approved' || !actor.trim() || resolved.length !== targets.length || testSet.coverage_acceptance_status === 'accepted'} onClick={() => void onAccept(actor.trim())}>Chấp nhận phạm vi coverage</button>
      {resolved.length < targets.length && <p>Còn {targets.length - resolved.length} mục tiêu chưa xác nhận assertion hoặc quyết định gap. Các gap không được tính là covered.</p>}
    </details>
    <details><summary>Điều kiện chạy từng case · {runnable.length}/{testSet.content.test_cases.length} sẵn sàng</summary>
      {testSet.content.test_cases.map(test => <ReadinessRow key={`${testSet.id}-${testSet.content_version}-${test.id}`} test={test} current={(testSet.case_readiness ?? []).find(item => item.case_id === test.id && item.content_version === testSet.content_version)} actor={actor} disabled={busy || testSet.stale} onAssess={onAssess} />)}
    </details>
  </section>
}

