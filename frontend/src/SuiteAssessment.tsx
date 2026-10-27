import { useState } from 'react'
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
  const choice = evidence[Number(selected)]
  const canConfirm = row.status === 'covered' && evidence.length > 0 && !row.unverified_aspects?.length
  return <div className="assessment-target">
    <div><strong>{row.target_type} · {row.target_id}</strong><span>{decision ? ` · ${decision.disposition} (${decision.decided_by})` : ' · Chưa có quyết định'}</span></div>
    <small>{row.explanation}</small>
    <div className="assessment-controls">
      <select value={disposition} onChange={event => setDisposition(event.target.value as GapDisposition)} disabled={disabled} aria-label={`Quyết định ${row.target_id}`}>
        {canConfirm && <option value="confirmed">Xác nhận assertion</option>}
        <option value="blocked">Bị chặn — blocked</option><option value="deferred">Bổ sung sau — deferred</option>
        <option value="accepted_risk">Chấp nhận rủi ro</option><option value="not_applicable">Không áp dụng</option>
      </select>
      {disposition === 'confirmed' && <select value={selected} onChange={event => setSelected(event.target.value)} disabled={disabled} aria-label={`Assertion ${row.target_id}`}>
        {evidence.map((item, index) => <option key={`${item.test_case_id}-${index}`} value={String(index)}>{item.test_case_id}: {item.assertion}</option>)}
      </select>}
      {disposition !== 'confirmed' && <input value={reason} onChange={event => setReason(event.target.value)} disabled={disabled} placeholder="Lý do xử lý gap" aria-label={`Lý do ${row.target_id}`} />}
      {disposition === 'deferred' && <input value={owner} onChange={event => setOwner(event.target.value)} disabled={disabled} placeholder="Người phụ trách" aria-label={`Owner ${row.target_id}`} />}
      <button type="button" disabled={disabled || !actor.trim() || (disposition === 'confirmed' ? !canConfirm || !choice : !reason.trim() || (disposition === 'deferred' && !owner.trim()))} onClick={() => void onDecide({
        target_type: row.target_type, target_id: row.target_id, disposition, decided_by: actor.trim(),
        assertion_case_id: disposition === 'confirmed' ? choice.test_case_id : null,
        assertion: disposition === 'confirmed' ? choice.assertion : null,
        reason: disposition === 'confirmed' ? null : reason.trim(), owner: disposition === 'deferred' ? owner.trim() : null,
      })}>Lưu quyết định</button>
    </div>
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
  const ready = Boolean(current?.environment_ready && current?.test_data_ready && current?.verification_ready && !test.needs_clarification)
  return <div className="assessment-target">
    <strong>{test.id} · {ready ? 'Sẵn sàng chạy' : test.needs_clarification ? 'Cần làm rõ' : 'Chưa xác nhận điều kiện chạy'}</strong>
    <div className="assessment-controls">
      <label><input type="checkbox" checked={environment} onChange={event => setEnvironment(event.target.checked)} disabled={disabled} /> Môi trường</label>
      <label><input type="checkbox" checked={data} onChange={event => setData(event.target.checked)} disabled={disabled} /> Test data</label>
      <label><input type="checkbox" checked={verification} onChange={event => setVerification(event.target.checked)} disabled={disabled} /> Cách xác minh</label>
      <input value={note} onChange={event => setNote(event.target.value)} disabled={disabled} placeholder="Ghi chú điều kiện chạy" aria-label={`Ghi chú ${test.id}`} />
      <button type="button" disabled={disabled || !actor.trim() || (test.needs_clarification && environment && data && verification)} onClick={() => void onAssess(test.id, { assessed_by: actor.trim(), environment_ready: environment, test_data_ready: data, verification_ready: verification, note: note.trim() || null })}>Lưu</button>
    </div>
  </div>
}

export function SuiteAssessment({ testSet, busy, onDecide, onAccept, onAssess }: {
  testSet: TestSet; busy: boolean; onDecide: (input: DecisionInput) => Promise<void>
  onAccept: (actor: string) => Promise<void>; onAssess: (caseId: string, input: ReadinessInput) => Promise<void>
}) {
  const [actor, setActor] = useState('')
  const targets = (testSet.content.coverage_matrix ?? []).filter(item => item.target_type !== 'category')
  const decisions = (testSet.coverage_decisions ?? []).filter(item => item.story_version === testSet.story_version && item.content_version === testSet.content_version)
  const resolved = targets.filter(item => decisions.some(decision => decision.target_type === item.target_type && decision.target_id === item.target_id))
  const runnable = (testSet.case_readiness ?? []).filter(item => item.story_version === testSet.story_version && item.content_version === testSet.content_version && item.environment_ready && item.test_data_ready && item.verification_ready && testSet.content.test_cases.some(test => test.id === item.case_id && !test.needs_clarification))
  return <section className="suite-assessment">
    <h3>Quyết định QA cho suite</h3>
    <p><b>Nội dung:</b> {testSet.review_status === 'approved' ? 'Đã duyệt' : 'Bản nháp'} · <b>Coverage thiết kế:</b> {testSet.coverage_status} · <b>Chấp nhận phạm vi:</b> {testSet.coverage_acceptance_status} · <b>Khả năng chạy:</b> {testSet.execution_readiness}</p>
    <p>{testSet.candidate_coverage_count}/{testSet.coverage_target_count} mục tiêu có assertion liên kết trong bản thiết kế; QA xác nhận {testSet.qa_confirmed_target_count}; {testSet.gap_decision_count} quyết định gap. Liên kết assertion chưa chứng minh hệ thống đáp ứng yêu cầu; công cụ chưa chạy test.</p>
    <label>Người quyết định (tự khai; MVP chưa xác minh danh tính) <input value={actor} onChange={event => setActor(event.target.value)} placeholder="Tên QA" /></label>
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
