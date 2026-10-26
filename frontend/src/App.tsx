import { useCallback, useEffect, useMemo, useState } from 'react'
import { AlertTriangle, Check, ChevronRight, ClipboardCheck, Download, FilePlus2, FlaskConical, LoaderCircle, Pencil, RefreshCw, Save, Sparkles } from 'lucide-react'
import { api, ApiError } from './api'
import type { ApiContractReview, ApiContractReviewContent, ApiSpecification, Review, ReviewContent, ReviewItem, Story, TestContent, TestSet, TestType, Workspace } from './types'

type StoryDraft = {
  title: string; description: string; acceptance_criteria: string[]; business_context: string
  dependencies: string[]; language: 'auto' | 'vi' | 'en'
}
const emptyStory: StoryDraft = { title: '', description: '', acceptance_criteria: [], business_context: '', dependencies: [], language: 'auto' }
const sectionLabels: [keyof ReviewContent, string][] = [
  ['missing_acceptance_criteria', 'Acceptance criteria còn thiếu'], ['ambiguities_and_conflicts', 'Điểm chưa rõ & mâu thuẫn'],
  ['stakeholder_questions', 'Câu hỏi cho PO / BA'], ['edge_cases', 'Edge cases'], ['assumptions', 'Giả định'], ['risks', 'Rủi ro'],
]

function StatusBadge({ status, stale }: { status: string; stale: boolean }) {
  if (stale) return <span className="badge badge-stale">Stale</span>
  return <span className={`badge badge-${status}`}>{status === 'approved' ? 'Đã duyệt' : 'Bản nháp'}</span>
}

function Button({ children, busy, variant = 'primary', ...props }: React.ButtonHTMLAttributes<HTMLButtonElement> & { busy?: boolean; variant?: string }) {
  return <button className={`button button-${variant}`} disabled={busy || props.disabled} {...props}>{busy ? <LoaderCircle className="spin" size={17} /> : children}</button>
}

function Notice({ error, clear }: { error: string; clear: () => void }) {
  return <div className="notice"><AlertTriangle size={18} /><span>{error}</span><button onClick={clear}>×</button></div>
}

function StoryForm({ initial, onSave, onCancel, busy }: { initial?: Story; onSave: (data: StoryDraft) => Promise<void>; onCancel: () => void; busy: boolean }) {
  const [form, setForm] = useState(() => initial ? { title: initial.title, description: initial.description, acceptance_criteria: initial.acceptance_criteria, business_context: initial.business_context ?? '', dependencies: initial.dependencies, language: initial.language } : emptyStory)
  const [criteria, setCriteria] = useState(form.acceptance_criteria.join('\n'))
  const [dependencies, setDependencies] = useState(form.dependencies.join('\n'))
  return <div className="card form-card">
    <div className="card-heading"><div><span className="eyebrow">User story</span><h2>{initial ? 'Cập nhật story' : 'Tạo story mới'}</h2></div></div>
    <label>Tiêu đề<input value={form.title} maxLength={240} required onChange={e => setForm({ ...form, title: e.target.value })} placeholder="Ví dụ: Đăng nhập bằng email" /></label>
    <label>Mô tả<textarea value={form.description} required rows={7} onChange={e => setForm({ ...form, description: e.target.value })} placeholder="As a… I want… so that…" /></label>
    <div className="form-grid">
      <label>Acceptance criteria hiện có<textarea rows={5} value={criteria} onChange={e => setCriteria(e.target.value)} placeholder="Mỗi dòng là một tiêu chí" /></label>
      <label>Business context<textarea rows={5} value={form.business_context} onChange={e => setForm({ ...form, business_context: e.target.value })} /></label>
      <label>Dependencies<textarea rows={4} value={dependencies} onChange={e => setDependencies(e.target.value)} placeholder="Mỗi dòng là một dependency" /></label>
      <label>Ngôn ngữ<select value={form.language} onChange={e => setForm({ ...form, language: e.target.value as 'auto' | 'vi' | 'en' })}><option value="auto">Tự nhận diện</option><option value="vi">Tiếng Việt</option><option value="en">English</option></select></label>
    </div>
    <div className="actions"><Button variant="ghost" onClick={onCancel}>Huỷ</Button><Button busy={busy} disabled={!form.title.trim() || !form.description.trim()} onClick={() => onSave({ ...form, acceptance_criteria: criteria.split('\n').map(x => x.trim()).filter(Boolean), dependencies: dependencies.split('\n').map(x => x.trim()).filter(Boolean) })}><Save size={17} /> Lưu story</Button></div>
  </div>
}

function FindingList({ title, items }: { title: string; items: ReviewItem[] }) {
  return <section className="finding-section"><div className="section-title"><h3>{title}</h3><span>{items.length}</span></div>{items.length === 0 ? <p className="empty">Không có phát hiện.</p> : <div className="finding-grid">{items.map(item => <article className="finding" key={item.id}><div><span className={`severity severity-${item.severity}`}>{item.severity}</span><code>{item.id}</code><span className={`classification classification-${item.classification}`}>{item.classification === 'requirement' ? 'Requirement' : item.classification === 'recommendation' ? 'Đề xuất AI' : 'Cần xác nhận'}</span></div><h4>{item.title}</h4><p>{item.detail}</p><small>Nguồn: {item.source_reference}</small></article>)}</div>}</section>
}

function JsonEditor<T>({ value, onSave, onCancel, busy }: { value: T; onSave: (value: T) => Promise<void>; onCancel: () => void; busy: boolean }) {
  const [text, setText] = useState(JSON.stringify(value, null, 2)); const [error, setError] = useState('')
  return <div className="json-editor"><p>Chỉnh sửa dữ liệu có cấu trúc. API sẽ kiểm tra schema trước khi lưu.</p><textarea value={text} rows={26} spellCheck={false} onChange={e => setText(e.target.value)} />{error && <small className="field-error">{error}</small>}<div className="actions"><Button variant="ghost" onClick={onCancel}>Huỷ</Button><Button busy={busy} onClick={async () => { try { await onSave(JSON.parse(text) as T) } catch (e) { setError(e instanceof SyntaxError ? 'JSON không hợp lệ.' : String(e)) } }}><Save size={17} /> Lưu thay đổi</Button></div></div>
}

function ReviewPanel({ review, onApprove, onSave, onGenerateTests, onRegenerate, apiReviewId, requiresApiReview, busy }: { review: Review; onApprove: () => Promise<void>; onSave: (c: ReviewContent) => Promise<void>; onGenerateTests: () => Promise<void>; onRegenerate: () => Promise<void>; apiReviewId?: string; requiresApiReview: boolean; busy: string }) {
  const [editing, setEditing] = useState(false)
  return <div className="card"><div className="card-heading"><div><span className="eyebrow">Requirement review · v{review.story_version}</span><h2>Phân tích yêu cầu</h2></div><StatusBadge status={review.status} stale={review.stale} /></div>
    {editing ? <JsonEditor value={review.content} busy={busy === 'save-review'} onCancel={() => setEditing(false)} onSave={async c => { await onSave(c); setEditing(false) }} /> : <>
      <div className="summary"><Sparkles size={20} /><div><strong>Tóm tắt nghiệp vụ</strong><p>{review.content.business_summary}</p></div></div>
      <p className="human-review-note">AC hiện có là requirement từ story. Các AC còn thiếu chỉ là recommendation của AI; mục <b>needs_clarification</b> cần PO/BA xác nhận trước khi coi là quy tắc nghiệp vụ.</p>
      {apiReviewId && <p className="coverage">Bộ test tiếp theo sẽ kết hợp API Contract Review đã duyệt.</p>}
      {requiresApiReview && !apiReviewId && <p className="notice">Duyệt API Contract Review hiện tại trước khi sinh test cho story này.</p>}
      <section className="finding-section"><div className="section-title"><h3>Acceptance criteria hiện có</h3><span>{review.content.existing_acceptance_criteria.length}</span></div><div className="criteria-list">{review.content.existing_acceptance_criteria.map(x => <div key={x.id}><code>{x.id}</code><span>{x.criterion}</span><small>{(x.obligations ?? []).map(item => item.text).join(' · ')}</small></div>)}</div></section>
      {sectionLabels.map(([key, label]) => <FindingList key={key} title={label} items={review.content[key] as ReviewItem[]} />)}
      <div className="actions split"><div><a className="button button-ghost" href={api.exportUrl('requirement-reviews', review.id, 'json')}><Download size={16} /> JSON</a><a className="button button-ghost" href={api.exportUrl('requirement-reviews', review.id, 'csv')}><Download size={16} /> CSV</a></div><div>{review.stale ? <Button busy={busy === 'generate-review'} onClick={onRegenerate}><RefreshCw size={16} /> Phân tích version hiện tại</Button> : <><Button variant="ghost" onClick={() => setEditing(true)}><Pencil size={16} /> Chỉnh sửa</Button>{review.status !== 'approved' && <Button busy={busy === 'approve-review'} onClick={onApprove}><Check size={17} /> Phê duyệt</Button>}{review.status === 'approved' && <Button busy={busy === 'generate-tests'} disabled={requiresApiReview && !apiReviewId} onClick={onGenerateTests}><FlaskConical size={17} /> Sinh test case</Button>}</>}</div></div>
    </>}
  </div>
}

function ApiContractPanel({ specs, reviews, onUpload, onGenerate, onSave, onApprove, busy }: {
  specs: ApiSpecification[]; reviews: ApiContractReview[]
  onUpload: (file: File) => Promise<void>; onGenerate: (specId: string) => Promise<void>
  onSave: (reviewId: string, content: ApiContractReviewContent) => Promise<void>
  onApprove: (reviewId: string) => Promise<void>; busy: string
}) {
  const [file, setFile] = useState<File | null>(null)
  const [editing, setEditing] = useState(false)
  const currentSpec = specs.find(spec => !spec.stale) ?? specs[0]
  const review = currentSpec && reviews.find(item => item.specification_id === currentSpec.id)
  return <div className="card api-contract-panel">
    <div className="card-heading"><div><span className="eyebrow">API Contract Agent · {review?.model_name ?? 'AI provider'}</span><h2>OpenAPI contract</h2></div>{currentSpec && <StatusBadge status={review?.status ?? 'draft'} stale={currentSpec.stale || !!review?.stale} />}</div>
    <p className="coverage">Tải OpenAPI 3.x JSON/YAML để phân tích endpoint, request, response và schema. QA cần duyệt contract review trước khi dùng để sinh test.</p>
    <div className="api-upload"><input type="file" accept=".json,.yaml,.yml,application/json,text/yaml" onChange={event => setFile(event.target.files?.[0] ?? null)} /><Button busy={busy === 'upload-api'} disabled={!file} onClick={async () => { if (file) { await onUpload(file); setFile(null) } }}><FilePlus2 size={16} /> Tải OpenAPI</Button><small>JSON/YAML · tối đa 1 MB · chỉ hỗ trợ $ref nội bộ</small></div>
    {specs.filter(spec => spec.stale).length > 0 && <details className="api-history"><summary>Spec cũ ({specs.filter(spec => spec.stale).length})</summary>{specs.filter(spec => spec.stale).map(spec => <p key={spec.id}>{spec.title} · v{spec.version} · stale</p>)}</details>}
    {!currentSpec ? <p className="empty">Chưa có OpenAPI spec gắn với story này.</p> : <>
      <div className="api-spec-meta"><div><strong>{currentSpec.title}</strong><small>{currentSpec.file_name} · OpenAPI {currentSpec.openapi_version} · v{currentSpec.version}</small></div><span>{currentSpec.operations.length} operations</span></div>
      {!review || review.stale ? <div className="actions"><Button busy={busy === 'generate-api-review'} disabled={currentSpec.stale} onClick={() => onGenerate(currentSpec.id)}><Sparkles size={16} /> {review ? 'Phân tích lại API Contract' : 'Chạy API Contract Agent'}</Button></div> : editing ? <JsonEditor value={review.content} busy={busy === 'save-api-review'} onCancel={() => setEditing(false)} onSave={async content => { await onSave(review.id, content); setEditing(false) }} /> : <>
        <div className="summary"><Sparkles size={20} /><div><strong>Phân tích contract</strong><p>{review.content.summary}</p></div></div>
        <div className="api-operations"><div className="section-title"><h3>Operations</h3><span>{review.content.operations.length}</span></div>{review.content.operations.map(operation => <div key={operation.operation_id}><code>{operation.method}</code><b>{operation.path}</b><small>{operation.summary || operation.operation_id}</small></div>)}</div>
        <div className="api-findings"><div className="section-title"><h3>Checks và điểm cần làm rõ</h3><span>{review.content.findings.length}</span></div>{review.content.findings.length === 0 ? <p className="empty">Không có phát hiện.</p> : review.content.findings.map(finding => <article className="finding" key={finding.id}><div><span className={`type type-${finding.type === 'schema' || finding.type === 'security' ? 'boundary' : finding.type === 'conflict' ? 'gap' : finding.type}`}>{finding.type}</span><span className={`severity severity-${finding.severity}`}>{finding.severity}</span><code>{finding.id}</code></div><h4>{finding.method} {finding.path} · {finding.title}</h4><p>{finding.detail}</p><small>Nguồn OpenAPI: {finding.source_reference}{finding.story_reference && ` · Story: ${finding.story_reference}`} · {finding.classification}</small>{finding.expected_status_codes.length > 0 && <p>Status theo spec: {finding.expected_status_codes.join(', ')}</p>}</article>)}</div>
        <div className="actions split"><div><a className="button button-ghost" href={api.exportUrl('api-contract-reviews', review.id, 'json')}><Download size={16} /> JSON</a><a className="button button-ghost" href={api.exportUrl('api-contract-reviews', review.id, 'csv')}><Download size={16} /> CSV</a></div><div><Button variant="ghost" disabled={review.stale} onClick={() => setEditing(true)}><Pencil size={16} /> Chỉnh sửa</Button>{review.status !== 'approved' && <Button busy={busy === 'approve-api-review'} disabled={review.stale} onClick={() => onApprove(review.id)}><Check size={17} /> Duyệt API review</Button>}</div></div>
      </>}
    </>}
  </div>
}

function TestPanel({ testSet, onSave, onApprove, busy }: { testSet: TestSet; onSave: (c: TestContent) => Promise<void>; onApprove: () => Promise<void>; busy: string }) {
  const [filter, setFilter] = useState<TestType | 'all'>('all'); const [editing, setEditing] = useState(false)
  const cases = testSet.content.test_cases.filter(test => filter === 'all' || test.type === filter)
  const coverageMatrix = testSet.content.coverage_matrix ?? []
  return <div className="card"><div className="card-heading"><div><span className="eyebrow">Test suite · v{testSet.story_version}</span><h2>Test cases ban đầu</h2></div><StatusBadge status={testSet.status} stale={testSet.stale} /></div>
    {editing ? <JsonEditor value={testSet.content} busy={busy === 'save-tests'} onCancel={() => setEditing(false)} onSave={async c => { await onSave(c); setEditing(false) }} /> : <>
      <p className="coverage">{testSet.content.coverage_summary}</p>
      {coverageMatrix.length > 0 && <section className="coverage-matrix"><div className="section-title"><h3>Coverage và điểm cần xác nhận</h3><span>{coverageMatrix.length}</span></div><div className="coverage-rows">{coverageMatrix.map(entry => <div key={`${entry.target_type}-${entry.target_id}`}><span className={entry.status === 'covered' ? 'ready' : 'clarify'}>{entry.status === 'covered' ? 'Đã bao phủ' : 'Cần làm rõ'}</span><b>{(entry.target_type === 'acceptance_criterion' || entry.target_type === 'requirement_obligation') ? 'Requirement' : entry.target_type === 'risk' ? 'Rủi ro' : entry.target_type === 'api_check' ? 'API check' : 'Nhóm'} · {entry.target_id}</b><small>{entry.test_case_ids.length ? `Test: ${entry.test_case_ids.join(', ')}` : entry.explanation}</small></div>)}</div></section>}
      <div className="filters">{(['all', 'positive', 'negative', 'boundary', 'integration'] as const).map(type => <button className={filter === type ? 'active' : ''} onClick={() => setFilter(type)} key={type}>{type}<span>{type === 'all' ? testSet.content.test_cases.length : testSet.content.test_cases.filter(t => t.type === type).length}</span></button>)}</div>
      <div className="table-wrap"><table><thead><tr><th>ID</th><th>Loại</th><th>Test case</th><th>Priority</th><th>Traceability</th><th>Trạng thái</th></tr></thead><tbody>{cases.map(test => <tr key={test.id}><td><code>{test.id}</code></td><td><span className={`type type-${test.type}`}>{test.type}</span></td><td><span className={`classification classification-${test.basis}`}>{test.basis === 'requirement' ? 'Requirement' : 'Recommendation'}</span><strong>{test.title}</strong><small>{test.objective}</small><details><summary>Preconditions, data, steps & expected result</summary>{test.api_method && <p><b>API:</b> {test.api_method} {test.api_path}</p>}{test.api_request && <p><b>Request:</b> {test.api_request}</p>}{(test.expected_status_codes ?? []).length > 0 && <p><b>Status:</b> {test.expected_status_codes.join(', ')}</p>}<p><b>Preconditions:</b> {test.preconditions.join('; ') || 'Không yêu cầu'}</p><p><b>Test data:</b> {test.test_data.join('; ') || 'Không yêu cầu'}</p><ol>{test.steps.map(step => <li key={step.order}>{step.action}<em>{step.expected_result}</em></li>)}</ol><p><b>Kết quả:</b> {test.expected_result}</p>{test.assumptions.length > 0 && <p><b>Giả định:</b> {test.assumptions.join('; ')}</p>}</details></td><td><span className={`severity severity-${test.priority}`}>{test.priority}</span></td><td>{test.requirement_traceability.map(x => <code key={x}>{x}</code>)}{(test.api_traceability ?? []).map(x => <code key={x}>{x}</code>)}</td><td>{test.needs_clarification ? <span className="clarify">Cần làm rõ</span> : <span className="ready">Chờ QA review</span>}</td></tr>)}</tbody></table></div>
      <div className="actions split"><div><a className="button button-ghost" href={api.exportUrl('test-case-sets', testSet.id, 'json')}><Download size={16} /> JSON</a><a className="button button-ghost" href={api.exportUrl('test-case-sets', testSet.id, 'csv')}><Download size={16} /> CSV</a></div><div><Button variant="ghost" disabled={testSet.stale} onClick={() => setEditing(true)}><Pencil size={16} /> Chỉnh sửa</Button>{testSet.status !== 'approved' && <Button busy={busy === 'approve-tests'} disabled={testSet.stale} onClick={onApprove}><Check size={17} /> Phê duyệt</Button>}</div></div>
    </>}
  </div>
}

export default function App() {
  const [stories, setStories] = useState<Story[]>([]); const [workspace, setWorkspace] = useState<Workspace | null>(null)
  const [showForm, setShowForm] = useState(false); const [editingStory, setEditingStory] = useState(false); const [busy, setBusy] = useState(''); const [error, setError] = useState('')
  const loadStories = useCallback(async () => { try { setStories(await api.listStories()) } catch (e) { setError(message(e)) } }, [])
  const openStory = useCallback(async (id: string) => { try { setWorkspace(await api.getStory(id)); setShowForm(false); setEditingStory(false) } catch (e) { setError(message(e)) } }, [])
  const refresh = useCallback(async () => { if (workspace) { await openStory(workspace.id); await loadStories() } }, [workspace, openStory, loadStories])
  // Initial remote data hydration is the only mount effect in this application shell.
  // eslint-disable-next-line react-hooks/set-state-in-effect
  useEffect(() => { void loadStories() }, [loadStories])
  const latestReview = workspace?.reviews[0]; const latestTests = workspace?.test_case_sets[0]
  const approvedApiReview = workspace?.api_contract_reviews?.find(item => item.status === 'approved' && !item.stale)
  const requiresApiReview = (workspace?.api_specifications ?? []).some(spec => !spec.stale)
  const history = useMemo(() => [...(workspace?.reviews ?? []).map(x => ({ ...x, kind: 'Review' })), ...(workspace?.api_contract_reviews ?? []).map(x => ({ ...x, kind: 'API Contract' })), ...(workspace?.test_case_sets ?? []).map(x => ({ ...x, kind: 'Test suite' }))].sort((a, b) => b.created_at.localeCompare(a.created_at)), [workspace])
  async function run(name: string, task: () => Promise<unknown>) { setBusy(name); setError(''); try { await task(); await refresh() } catch (e) { setError(message(e)) } finally { setBusy('') } }
  return <div className="shell"><aside><div className="brand"><div className="brand-mark"><ClipboardCheck /></div><div><strong>QA Compass</strong><span>Human-led AI review</span></div></div><Button onClick={() => { setShowForm(true); setEditingStory(false) }}><FilePlus2 size={17} /> Story mới</Button><nav><p>USER STORIES</p>{stories.length === 0 && <span className="nav-empty">Chưa có story</span>}{stories.map(story => <button className={workspace?.id === story.id ? 'selected' : ''} onClick={() => void openStory(story.id)} key={story.id}><span>{story.title}</span><small>Version {story.version}</small><ChevronRight size={16} /></button>)}</nav><footer><span className="pulse" /> AI hỗ trợ · QA quyết định</footer></aside>
    <main><header><div><span className="eyebrow">Workspace</span><h1>{workspace?.title ?? (showForm ? 'Story mới' : 'Requirement intelligence')}</h1></div>{workspace && !showForm && <div className="header-actions"><button title="Làm mới" onClick={() => void refresh()}><RefreshCw size={18} /></button><Button variant="ghost" onClick={() => setEditingStory(true)}><Pencil size={16} /> Sửa story</Button></div>}</header>{error && <Notice error={error} clear={() => setError('')} />}
      {showForm || editingStory ? <StoryForm initial={editingStory ? workspace ?? undefined : undefined} busy={busy === 'story'} onCancel={() => { setShowForm(false); setEditingStory(false) }} onSave={async data => run('story', async () => { const saved = editingStory && workspace ? await api.updateStory(workspace.id, data) : await api.createStory(data); setShowForm(false); setEditingStory(false); await loadStories(); await openStory(saved.id) })} /> : !workspace ? <div className="hero"><div className="hero-icon"><Sparkles /></div><span className="eyebrow">AI × QA judgement</span><h2>Biến user story thành<br />quyết định kiểm thử rõ ràng.</h2><p>Phát hiện khoảng trống trong requirement, để con người duyệt, rồi tạo test suite có traceability.</p><Button onClick={() => setShowForm(true)}><FilePlus2 size={18} /> Tạo story đầu tiên</Button><div className="flow"><span>01 · Nhập story</span><ChevronRight /><span>02 · AI phân tích</span><ChevronRight /><span>03 · QA duyệt</span><ChevronRight /><span>04 · Sinh test</span></div></div> : <div className="workspace"><section className="story-overview"><div><span>STORY v{workspace.version}</span><p>{workspace.description}</p></div><dl><div><dt>Acceptance criteria</dt><dd>{workspace.acceptance_criteria.length}</dd></div><div><dt>Dependencies</dt><dd>{workspace.dependencies.length}</dd></div><div><dt>Ngôn ngữ</dt><dd>{workspace.language.toUpperCase()}</dd></div></dl></section>
      <ApiContractPanel specs={workspace.api_specifications ?? []} reviews={workspace.api_contract_reviews ?? []} busy={busy}
        onUpload={file => run('upload-api', () => api.uploadApiSpecification(workspace.id, file))}
        onGenerate={specId => run('generate-api-review', () => api.generateApiContractReview(specId))}
        onSave={(id, content) => run('save-api-review', () => api.updateApiContractReview(id, content))}
        onApprove={id => run('approve-api-review', () => api.approveApiContractReview(id))} />
      {!latestReview ? <div className="empty-stage"><Sparkles /><h2>Sẵn sàng phân tích requirement</h2><p>AI sẽ tạo bản nháp. QA vẫn là người xác nhận mọi phát hiện.</p><Button busy={busy === 'generate-review'} onClick={() => run('generate-review', () => api.generateReview(workspace.id))}><Sparkles size={17} /> Chạy Requirement Review Agent</Button></div> : <ReviewPanel review={latestReview} busy={busy} apiReviewId={approvedApiReview?.id} requiresApiReview={requiresApiReview} onSave={c => run('save-review', () => api.updateReview(latestReview.id, c))} onApprove={() => run('approve-review', () => api.approveReview(latestReview.id))} onGenerateTests={() => run('generate-tests', () => api.generateTests(workspace.id, latestReview.id, approvedApiReview?.id))} onRegenerate={() => run('generate-review', () => api.generateReview(workspace.id))} />}
        {latestTests && <TestPanel testSet={latestTests} busy={busy} onSave={c => run('save-tests', () => api.updateTests(latestTests.id, c))} onApprove={() => run('approve-tests', () => api.approveTests(latestTests.id))} />}
        {history.length > 0 && <div className="card history"><div className="card-heading"><div><span className="eyebrow">Audit trail</span><h2>Lịch sử phiên bản</h2></div></div>{history.map(item => <div className="history-row" key={`${item.kind}-${item.id}`}><span>{item.kind}</span><b>Story v{item.story_version}</b><StatusBadge status={item.status} stale={item.stale} /><small>{new Date(item.created_at).toLocaleString('vi-VN')}</small></div>)}</div>}
      </div>}</main></div>
}

function message(error: unknown) { return error instanceof ApiError ? `${error.message} (${error.code})` : error instanceof Error ? error.message : 'Có lỗi không xác định.' }

