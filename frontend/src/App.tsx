import { useCallback, useEffect, useMemo, useState } from 'react'
import { ArrowUpRight, Braces, CheckCircle2, ChevronRight, ClipboardCheck, ClipboardList, Clock3, FilePlus2, History, ListChecks, Menu, Pencil, RefreshCw, Search, ShieldCheck, Sparkles } from 'lucide-react'
import { api, ApiError } from './api'
import { ApiContractPanel, Button, Notice, ReviewPanel, StatusBadge, StoryForm } from './ReviewPanels'
import { TestWorkbench } from './TestWorkbench'
import { currentDecisions, hasDesignEvidence, isCaseReady } from './qaView'
import type { Story, Workspace } from './types'

type View = 'tests' | 'coverage' | 'requirements' | 'api' | 'history'
const tabs = [
  { id: 'tests', label: 'Test cases', icon: ListChecks },
  { id: 'coverage', label: 'Coverage & bằng chứng', icon: ShieldCheck },
  { id: 'requirements', label: 'Yêu cầu', icon: ClipboardList },
  { id: 'api', label: 'API contract', icon: Braces },
  { id: 'history', label: 'Lịch sử', icon: History },
] as const

export default function App() {
  const [stories, setStories] = useState<Story[]>([])
  const [workspace, setWorkspace] = useState<Workspace | null>(null)
  const [loading, setLoading] = useState(true)
  const [showForm, setShowForm] = useState(false)
  const [editingStory, setEditingStory] = useState(false)
  const [busy, setBusy] = useState('')
  const [error, setError] = useState('')
  const [view, setView] = useState<View>('tests')
  const [storyQuery, setStoryQuery] = useState('')
  const [mobileNavOpen, setMobileNavOpen] = useState(false)
  const [selectedSuiteId, setSelectedSuiteId] = useState('')
  const loadStories = useCallback(async () => { setStories(await api.listStories()) }, [])
  const openStory = useCallback(async (id: string) => {
    setLoading(true); setError('')
    try {
      const data = await api.getStory(id)
      setWorkspace(data); setShowForm(false); setEditingStory(false); setSelectedSuiteId('')
      setMobileNavOpen(false); localStorage.setItem('qa-compass-story', id)
      if (!data.test_case_sets.length) setView('requirements')
    } catch (e) { setError(message(e)) } finally { setLoading(false) }
  }, [])
  const refresh = useCallback(async () => {
    if (workspace) setWorkspace(await api.getStory(workspace.id))
    await loadStories()
  }, [workspace, loadStories])
  useEffect(() => {
    let active = true
    async function hydrate() {
      try {
        const data = await api.listStories()
        if (!active) return
        setStories(data)
        const savedId = localStorage.getItem('qa-compass-story')
        const story = data.find(item => item.id === savedId) ?? data[0]
        if (story) {
          const selected = await api.getStory(story.id)
          if (!active) return
          setWorkspace(selected)
          if (!selected.test_case_sets.length) setView('requirements')
        }
      } catch (e) { if (active) setError(message(e)) } finally { if (active) setLoading(false) }
    }
    void hydrate()
    return () => { active = false }
  }, [])

  const latestReview = workspace?.reviews[0]
  const suite = workspace?.test_case_sets.find(item => item.id === selectedSuiteId) ?? workspace?.test_case_sets[0]
  const approvedApiReview = workspace?.api_contract_reviews.find(item => item.status === 'approved' && !item.stale)
  const requiresApiReview = workspace?.api_specifications.some(spec => !spec.stale) ?? false
  const targets = (suite?.content.coverage_matrix ?? []).filter(row => row.target_type !== 'category')
  const evidenceCount = suite?.stale ? 0 : targets.filter(hasDesignEvidence).length
  const decisions = suite ? currentDecisions(suite) : []
  const undecided = targets.filter(row => !decisions.some(item => item.target_type === row.target_type && item.target_id === row.target_id)).length
  const readyCount = suite?.content.test_cases.filter(test => isCaseReady(suite, test)).length ?? 0
  const history = useMemo(() => [
    ...(workspace?.reviews ?? []).map(item => ({ ...item, kind: 'Requirement review' })),
    ...(workspace?.api_contract_reviews ?? []).map(item => ({ ...item, kind: 'API contract' })),
    ...(workspace?.test_case_sets ?? []).map(item => ({ ...item, kind: 'Test suite' })),
  ].sort((a, b) => b.created_at.localeCompare(a.created_at)), [workspace])
  async function run(name: string, task: () => Promise<unknown>) {
    setBusy(name); setError('')
    try { await task(); await refresh() } catch (e) { setError(message(e)) } finally { setBusy('') }
  }
  async function save(name: string, task: () => Promise<unknown>) {
    setBusy(name); setError('')
    try { await task(); await refresh() } catch (e) { setError(message(e)); throw e } finally { setBusy('') }
  }
  const visibleStories = stories.filter(story => story.title.toLocaleLowerCase().includes(storyQuery.toLocaleLowerCase()))
  return <div className="shell">
    <a className="skip-link" href="#workspace-main">Đến nội dung</a>
    <aside className="sidebar">
      <div className="brand"><div className="brand-mark"><ClipboardCheck size={25} /></div><div><strong>QA Compass</strong><span>Quality workspace</span></div><button className="mobile-menu icon-button" aria-label="Danh sách story" aria-expanded={mobileNavOpen} onClick={() => setMobileNavOpen(!mobileNavOpen)}><Menu size={21} /></button></div>
      <button className="button new-story" onClick={() => { setShowForm(true); setEditingStory(false); setMobileNavOpen(false) }}><FilePlus2 size={17} /> Story mới</button>
      <div className={`sidebar-content ${mobileNavOpen ? 'mobile-open' : ''}`}>
        <div className="sidebar-section-label"><span>User stories</span><span>{stories.length}</span></div>
        <label className="sidebar-search"><Search size={15} /><input aria-label="Tìm story" placeholder="Tìm story…" value={storyQuery} onChange={event => setStoryQuery(event.target.value)} /></label>
        <nav aria-label="User stories">{visibleStories.map(story => <button className={workspace?.id === story.id ? 'selected' : ''} onClick={() => void openStory(story.id)} key={story.id} aria-current={workspace?.id === story.id ? 'page' : undefined}><span>{story.title}</span><small>Story v{story.version}</small><ChevronRight size={15} /></button>)}{!visibleStories.length && <p className="nav-empty">{storyQuery ? 'Không tìm thấy story.' : 'Tạo story để bắt đầu.'}</p>}</nav>
      </div>
      <footer><div className="qa-avatar">QA</div><div><strong>Không gian nội bộ</strong><span>AI hỗ trợ. QA quyết định.</span></div></footer>
    </aside>
    <main id="workspace-main">
      <div className="workspace-topbar"><span><ClipboardCheck size={15} /> Không gian kiểm thử <ChevronRight size={13} /> <b>{showForm ? 'Story mới' : 'Dashboard QA'}</b></span><span className="human-review-tag"><CheckCircle2 size={14} /> Human review</span></div>
      <header className="page-header">
        <div><div className="story-kicker">{workspace && !showForm ? <><span>Story v{workspace.version}</span><span>{workspace.acceptance_criteria.length} acceptance criteria</span></> : <span>QA Compass</span>}</div><h1 title={workspace?.title}>{showForm ? 'Tạo user story' : workspace?.title ?? 'Bàn làm việc của QA'}</h1></div>
        {workspace && !showForm && <div className="header-actions"><button className="icon-button" aria-label="Làm mới dữ liệu" disabled={Boolean(busy)} onClick={() => void run('refresh', refresh)}><RefreshCw size={17} /></button><Button variant="ghost" onClick={() => setEditingStory(true)}><Pencil size={15} /> Sửa story</Button></div>}
      </header>
      {error && <Notice error={error} clear={() => setError('')} />}
      {busy && <div className="progress-note" role="status"><RefreshCw size={14} className="spin" /> Đang xử lý…</div>}
      {showForm || editingStory ? <StoryForm key={editingStory ? workspace?.id : 'new'} initial={editingStory ? workspace ?? undefined : undefined} busy={busy === 'story'} onCancel={() => { setShowForm(false); setEditingStory(false) }} onSave={async data => {
        setBusy('story'); setError('')
        try { const saved = editingStory && workspace ? await api.updateStory(workspace.id, data) : await api.createStory(data); await loadStories(); await openStory(saved.id) } catch (e) { setError(message(e)) } finally { setBusy('') }
      }} /> : loading ? <div className="loading-state" role="status"><RefreshCw className="spin" /><p>Đang tải workspace…</p></div> : !workspace ? <div className="empty-workspace"><ClipboardList size={42} /><h2>Bắt đầu từ một user story</h2><p>Nhập yêu cầu, review các điểm chưa rõ và tạo test suite để QA kiểm tra.</p><Button onClick={() => setShowForm(true)}><FilePlus2 size={17} /> Tạo story đầu tiên</Button></div> : <>
        {suite && <section className="quality-strip" aria-label="Tình trạng kiểm thử">
          <button onClick={() => setView('tests')}><span><ClipboardCheck size={15} /> Review nội dung</span><strong>{suite.stale ? 'Nguồn đã thay đổi' : suite.review_status === 'approved' ? 'Đã duyệt' : 'Chờ QA review'}</strong><small>{suite.stale ? 'Cần sinh lại suite' : 'Quyết định về nội dung test'}</small></button>
          <button className="coverage-metric" onClick={() => setView('coverage')}><span><ShieldCheck size={15} /> Coverage thiết kế</span><strong>{evidenceCount}<em> / {targets.length}</em><small>mục tiêu</small></strong><div className="coverage-meter" aria-hidden="true"><i style={{ width: `${targets.length ? evidenceCount / targets.length * 100 : 0}%` }} /></div><small>Có assertion liên kết</small></button>
          <button onClick={() => setView('coverage')}><span><Clock3 size={15} /> Quyết định coverage</span><strong className={undecided ? 'amber-text' : ''}>{undecided}<em> còn chờ</em></strong><small>{decisions.filter(item => item.disposition === 'confirmed').length} QA xác nhận · {decisions.filter(item => item.disposition !== 'confirmed').length} gap decisions</small></button>
          <button onClick={() => setView('tests')}><span><ListChecks size={15} /> Điều kiện thực thi</span><strong>{readyCount}<em> / {suite.content.test_cases.length}</em><small>case sẵn sàng</small></strong><small>Chưa có kết quả chạy test</small></button>
        </section>}
        <div className="workspace-navigation">
          <nav className="workspace-tabs" aria-label="Các phần của story">{tabs.map(tab => { const Icon = tab.icon; return <button key={tab.id} className={view === tab.id ? 'active' : ''} aria-current={view === tab.id ? 'page' : undefined} onClick={() => setView(tab.id)}><Icon size={16} />{tab.label}{tab.id === 'tests' && suite && <span>{suite.content.test_cases.length}</span>}{tab.id === 'coverage' && undecided > 0 && <span className="gap-count">{undecided}</span>}</button> })}</nav>
          {suite && (view === 'tests' || view === 'coverage') && <label className="suite-selector"><span>Suite</span><select aria-label="Chọn phiên bản suite" value={suite.id} onChange={event => setSelectedSuiteId(event.target.value)}>{workspace.test_case_sets.map((item, index) => <option value={item.id} key={item.id}>{index === 0 ? 'Mới nhất' : `Bản ${workspace.test_case_sets.length - index}`} · {new Date(item.created_at).toLocaleString('vi-VN', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' })}{item.stale ? ' · Cũ' : ''}</option>)}</select></label>}
        </div>
        {(view === 'tests' || view === 'coverage') && (suite ? <TestWorkbench key={suite.id} testSet={suite} workspace={workspace} view={view} busy={busy} onViewChange={setView} onSave={content => save('save-tests', () => api.updateTests(suite.id, content))} onApprove={() => run('approve-tests', () => api.approveTests(suite.id))} onDecide={input => run('coverage-decision', () => api.decideCoverage(suite.id, input))} onAccept={actor => run('accept-coverage', () => api.acceptCoverage(suite.id, actor))} onAssess={(caseId, input) => run('case-readiness', () => api.assessCaseReadiness(suite.id, caseId, input))} /> : <div className="empty-stage"><ListChecks size={32} /><h2>Story chưa có test suite</h2><p>Duyệt requirement review trước khi sinh test cases.</p><Button onClick={() => setView('requirements')}>Mở requirement review <ArrowUpRight size={15} /></Button></div>)}
        {view === 'requirements' && <>
          <details className="story-source"><summary><ClipboardList size={17} /> Story gốc & acceptance criteria <span>v{workspace.version}</span></summary><div><p>{workspace.description}</p>{workspace.business_context && <><h3>Business context</h3><p>{workspace.business_context}</p></>}<h3>Acceptance criteria</h3><ol>{workspace.acceptance_criteria.map((item, index) => <li key={index}>{item}</li>)}</ol>{workspace.dependencies.length > 0 && <><h3>Dependencies</h3><ul>{workspace.dependencies.map((item, index) => <li key={index}>{item}</li>)}</ul></>}</div></details>
          {!latestReview ? <div className="empty-stage"><Sparkles size={32} /><h2>Review yêu cầu trước khi viết test</h2><p>AI phân tích story và đề xuất các câu hỏi cần xác nhận.</p><Button busy={busy === 'generate-review'} onClick={() => void run('generate-review', () => api.generateReview(workspace.id))}>Phân tích yêu cầu</Button></div> : <ReviewPanel key={latestReview.id} review={latestReview} sourceCriteria={workspace.acceptance_criteria} busy={busy} apiReviewId={approvedApiReview?.id} requiresApiReview={requiresApiReview} onSave={content => save('save-review', () => api.updateReview(latestReview.id, content))} onApprove={() => run('approve-review', () => api.approveReview(latestReview.id))} onGenerateTests={async () => { await run('generate-tests', () => api.generateTests(workspace.id, latestReview.id, approvedApiReview?.id)); setSelectedSuiteId(''); setView('tests') }} onRegenerate={() => run('generate-review', () => api.generateReview(workspace.id))} />}
        </>}
        {view === 'api' && <ApiContractPanel specs={workspace.api_specifications} reviews={workspace.api_contract_reviews} busy={busy} onUpload={file => run('upload-api', () => api.uploadApiSpecification(workspace.id, file))} onGenerate={id => run('generate-api-review', () => api.generateApiContractReview(id))} onSave={(id, content) => save('save-api-review', () => api.updateApiContractReview(id, content))} onApprove={id => run('approve-api-review', () => api.approveApiContractReview(id))} />}
        {view === 'history' && <section className="card history"><div className="workbench-heading"><div><h2>Lịch sử review & test suite</h2><p>Đối chiếu phiên bản nguồn và trạng thái phê duyệt.</p></div></div><div className="table-scroll"><table className="qa-table"><thead><tr><th>Loại</th><th>Story</th><th>Trạng thái</th><th>Thời gian tạo</th><th /></tr></thead><tbody>{history.map(item => <tr key={`${item.kind}-${item.id}`}><td>{item.kind}</td><td>v{item.story_version}</td><td><StatusBadge status={item.status} stale={item.stale} /></td><td>{new Date(item.created_at).toLocaleString('vi-VN')}</td><td>{item.kind === 'Test suite' && <button className="text-button" onClick={() => { setSelectedSuiteId(item.id); setView('tests') }}>Xem suite <ArrowUpRight size={15} /></button>}</td></tr>)}</tbody></table></div></section>}
      </>}
      <div className="workspace-footer"><span>QA Compass</span><span>Coverage thiết kế không thay thế kết quả thực thi.</span></div>
    </main>
  </div>
}

function message(error: unknown) {
  return error instanceof ApiError ? `${error.message} (${error.code})` : error instanceof Error ? error.message : 'Không tải được dữ liệu. Thử làm mới workspace.'
}

