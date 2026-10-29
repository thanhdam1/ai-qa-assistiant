import { useCallback, useEffect, useState } from 'react'
import {
  AlertCircle,
  AlertTriangle,
  ArrowDown,
  ArrowRight,
  CheckCircle2,
  Database,
  ExternalLink,
  Eye,
  FileCode,
  GitBranch,
  GitCommit,
  GitFork,
  Layers,
  Link2,
  Lock,
  Network,
  Plus,
  RefreshCw,
  ShieldAlert,
  ShieldCheck,
  Trash2,
  Workflow,
  X,
  Zap,
} from 'lucide-react'
import { api } from './api'
import type {
  DependencyNode,
  Story,
  StoryDependency,
  StoryDependencyTree,
  StoryImpactAnalysisReport,
  Workspace,
} from './types'

interface StoryJourneyGraphPanelProps {
  workspace: Workspace
  allStories: Story[]
  onOpenStory: (id: string) => void
  onRefresh: () => Promise<void>
}

export function StoryJourneyGraphPanel({
  workspace,
  allStories,
  onOpenStory,
  onRefresh,
}: StoryJourneyGraphPanelProps) {
  const [tree, setTree] = useState<StoryDependencyTree | null>(null)
  const [report, setReport] = useState<StoryImpactAnalysisReport | null>(null)
  const [loading, setLoading] = useState(true)
  const [maxDepth, setMaxDepth] = useState<'3' | 'all'>('3')
  const [error, setError] = useState<string | null>(null)
  const [busyAction, setBusyAction] = useState<string | null>(null)

  // Add Edge Modal state
  const [showAddModal, setShowAddModal] = useState(false)
  const [modalDirection, setModalDirection] = useState<'upstream' | 'downstream'>('upstream')
  const [selectedStoryId, setSelectedStoryId] = useState<string>('')
  const [depType, setDepType] = useState<string>('data_fixture')
  const [consumedOutputsInput, setConsumedOutputsInput] = useState<string>('cart_id, total_amount')
  const [boundRulesInput, setBoundRulesInput] = useState<string>('min_order_threshold')
  const [addError, setAddError] = useState<string | null>(null)

  const loadGraphData = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const [treeData, reportData] = await Promise.all([
        api.getDependencyTree(workspace.id, maxDepth),
        api.getImpactAnalysis(workspace.id).catch(() => null),
      ])
      setTree(treeData)
      setReport(reportData)
    } catch (err: any) {
      setError(err?.message || 'Không thể tải đồ thị phụ thuộc')
    } finally {
      setLoading(false)
    }
  }, [workspace.id, maxDepth])

  useEffect(() => {
    void loadGraphData()
  }, [loadGraphData])

  async function handleRemoveEdge(sourceId: string, targetId: string) {
    if (!confirm('Bạn có chắc chắn muốn xóa liên kết phụ thuộc này?')) return
    setBusyAction(`remove-${sourceId}-${targetId}`)
    try {
      await api.removeDependency(sourceId, targetId)
      await loadGraphData()
      await onRefresh()
    } catch (err: any) {
      setError(err?.message || 'Không thể xóa liên kết')
    } finally {
      setBusyAction(null)
    }
  }

  async function handleCreateEdge(e: React.FormEvent) {
    e.preventDefault()
    if (!selectedStoryId) {
      setAddError('Vui lòng chọn User Story để liên kết')
      return
    }

    setAddError(null)
    setBusyAction('create-edge')

    const consumed = consumedOutputsInput
      .split(',')
      .map(s => s.trim())
      .filter(Boolean)
    const rules = boundRulesInput
      .split(',')
      .map(s => s.trim())
      .filter(Boolean)

    const sourceId = modalDirection === 'upstream' ? selectedStoryId : workspace.id
    const targetId = modalDirection === 'upstream' ? workspace.id : selectedStoryId

    try {
      await api.addDependency(sourceId, {
        target_story_id: targetId,
        dependency_type: depType,
        binding_contract: {
          consumed_outputs: consumed,
          bound_rules: rules,
        },
      })
      setShowAddModal(false)
      setSelectedStoryId('')
      await loadGraphData()
      await onRefresh()
    } catch (err: any) {
      setAddError(err?.message || 'Không thể tạo liên kết (Có thể vi phạm chu trình lặp vô hạn)')
    } finally {
      setBusyAction(null)
    }
  }

  const upstreamNodes = tree?.upstream || []
  const downstreamNodes = tree?.downstream || []
  const candidateStories = allStories.filter(s => s.id !== workspace.id)

  return (
    <div className="journey-graph-panel">
      {/* Top Controls & Header */}
      <div className="journey-header-card">
        <div className="journey-title-group">
          <div className="journey-brand-mark">
            <Workflow size={24} />
          </div>
          <div>
            <h2>E2E User Journey & Quản Trị Tác Động Liên Story</h2>
            <p>
              Chuỗi hành trình kiểm thử E2E · Chống chu trình với Transaction Advisory Lock · Zero False Alarm Engine
            </p>
          </div>
        </div>

        <div className="journey-toolbar">
          <div className="depth-selector-group">
            <span className="depth-label">Độ sâu đồ thị:</span>
            <button
              className={`depth-toggle ${maxDepth === '3' ? 'active' : ''}`}
              onClick={() => setMaxDepth('3')}
              title="Hiển thị tối đa 3 cấp phụ thuộc trực tiếp"
            >
              Mặc định (3 cấp)
            </button>
            <button
              className={`depth-toggle ${maxDepth === 'all' ? 'active' : ''}`}
              onClick={() => setMaxDepth('all')}
              title="Duyệt toàn bộ đồ thị hạ nguồn (Full Transitive Closure)"
            >
              Toàn bộ chuỗi (DAG)
            </button>
          </div>

          <button
            className="button button-ghost"
            onClick={() => void loadGraphData()}
            disabled={loading}
            title="Làm mới trạng thái đồ thị"
          >
            <RefreshCw size={14} className={loading ? 'spin' : ''} />
            Làm mới
          </button>

          <button
            className="button btn-add-edge"
            onClick={() => {
              setShowAddModal(true)
              setAddError(null)
            }}
          >
            <Plus size={15} />
            Thêm Liên Kết Phụ Thuộc
          </button>
        </div>
      </div>

      {error && (
        <div className="notice error-notice">
          <AlertCircle size={16} />
          <span>{error}</span>
        </div>
      )}

      {/* Main Visual DAG Flow */}
      <div className="journey-visual-dag-container">
        {loading ? (
          <div className="dag-loading-state">
            <RefreshCw size={28} className="spin text-green" />
            <p>Đang phân tích đồ thị phụ thuộc và đối soát hợp đồng...</p>
          </div>
        ) : (
          <div className="dag-flow-grid">
            {/* Column 1: Upstream Stories */}
            <div className="dag-column upstream-column">
              <div className="column-badge-label">
                <GitCommit size={14} />
                <span>THƯỢNG NGUỒN (UPSTREAM - {upstreamNodes.length})</span>
              </div>
              <p className="column-subtext">Cung cấp điều kiện tiên quyết, Auth session & Test data</p>

              <div className="nodes-stack">
                {upstreamNodes.map(node => {
                  const isStale = node.impact_status === 'suspect_stale'
                  return (
                    <div
                      key={node.id}
                      className={`dag-node-card upstream-card ${isStale ? 'is-stale' : 'is-synced'}`}
                    >
                      <div className="node-card-topbar">
                        <span className="node-type-badge">{node.dependency_type}</span>
                        <span
                          className={`badge ${
                            isStale ? 'badge-stale' : 'badge-approved'
                          }`}
                        >
                          {isStale
                            ? `⚠️ Lệch pha (v${node.synced_source_version} → v${node.current_source_version})`
                            : `✓ Synced (v${node.synced_source_version})`}
                        </span>
                      </div>

                      <div className="node-body">
                        <strong className="node-title" title={node.title}>
                          {node.title}
                        </strong>
                        <div className="node-version-row">
                          <small>Phiên bản nguồn: v{node.current_source_version}</small>
                        </div>

                        {node.stale_reason && (
                          <div className="node-stale-alert">
                            <AlertTriangle size={12} />
                            <span>{node.stale_reason.summary || 'Quy tắc thay đổi'}</span>
                          </div>
                        )}

                        {node.impacted_case_ids && node.impacted_case_ids.length > 0 && (
                          <div className="impacted-pill-box">
                            <small>Test case bị ảnh hưởng:</small>
                            <div className="tc-tags-row">
                              {node.impacted_case_ids.map(tc => (
                                <code key={tc}>{tc}</code>
                              ))}
                            </div>
                          </div>
                        )}
                      </div>

                      <div className="node-card-footer">
                        <button
                          className="link-button"
                          onClick={() => onOpenStory(node.id)}
                          title="Mở Story này"
                        >
                          Mở story <ExternalLink size={12} />
                        </button>
                        <button
                          className="icon-button delete-edge-btn"
                          disabled={busyAction === `remove-${node.id}-${workspace.id}`}
                          onClick={() => void handleRemoveEdge(node.id, workspace.id)}
                          title="Xóa liên kết phụ thuộc"
                        >
                          <Trash2 size={13} />
                        </button>
                      </div>
                    </div>
                  )
                })}

                {upstreamNodes.length === 0 && (
                  <div className="empty-node-slot">
                    <p>Story này là Entry Point (Không có Story thượng nguồn phụ thuộc)</p>
                  </div>
                )}
              </div>
            </div>

            {/* Connecting Visual Arrows 1 -> 2 */}
            <div className="dag-connector-column">
              <div className="flow-arrow-line">
                <div className="arrow-badge">
                  <span>Data & Fixtures</span>
                  <ArrowRight size={16} />
                </div>
              </div>
            </div>

            {/* Column 2: Current Active Story (Center Node) */}
            <div className="dag-column current-column">
              <div className="column-badge-label current-label">
                <Zap size={14} />
                <span>STORY HIỆN TẠI (TARGET)</span>
              </div>
              <p className="column-subtext">Tâm điểm đối soát ngữ nghĩa & Lan truyền hồi quy</p>

              <div className="dag-node-card center-hero-node">
                <div className="center-node-glow-ring" />
                <div className="node-card-topbar">
                  <span className="badge badge-current">🎯 Story Đang Chọn</span>
                  <span className="version-tag">Version {workspace.version}</span>
                </div>

                <div className="node-body">
                  <h3 className="center-title">{workspace.title}</h3>
                  <div className="center-stats-grid">
                    <div className="stat-box">
                      <span className="stat-num">{workspace.acceptance_criteria.length}</span>
                      <span className="stat-desc">Acceptance Criteria</span>
                    </div>
                    <div className="stat-box">
                      <span className="stat-num">
                        {workspace.test_case_sets[0]?.content.test_cases.length || 0}
                      </span>
                      <span className="stat-desc">Test Cases</span>
                    </div>
                  </div>

                  <div className="contract-status-box">
                    <div className="status-item">
                      <ShieldCheck size={15} className="text-green" />
                      <span>DAG Advisory Lock: Sẵn sàng bảo vệ Race Condition</span>
                    </div>
                    <div className="status-item">
                      <Layers size={15} className="text-cyan" />
                      <span>Traceability Engine: 3-Step Semantic Intersection</span>
                    </div>
                  </div>
                </div>
              </div>
            </div>

            {/* Connecting Visual Arrows 2 -> 3 */}
            <div className="dag-connector-column">
              <div className="flow-arrow-line">
                <div className="arrow-badge">
                  <span>Impact Cascade</span>
                  <ArrowRight size={16} />
                </div>
              </div>
            </div>

            {/* Column 3: Downstream Stories */}
            <div className="dag-column downstream-column">
              <div className="column-badge-label">
                <GitFork size={14} />
                <span>HẠ NGUỒN (DOWNSTREAM - {downstreamNodes.length})</span>
              </div>
              <p className="column-subtext">Tiêu thụ kết quả, bị ảnh hưởng khi Story này đổi quy tắc</p>

              <div className="nodes-stack">
                {downstreamNodes.map(node => {
                  const isStale = node.impact_status === 'suspect_stale'
                  return (
                    <div
                      key={node.id}
                      className={`dag-node-card downstream-card ${isStale ? 'is-stale' : 'is-synced'}`}
                    >
                      <div className="node-card-topbar">
                        <span className="node-type-badge">{node.dependency_type}</span>
                        <span
                          className={`badge ${
                            isStale ? 'badge-stale' : 'badge-approved'
                          }`}
                        >
                          {isStale
                            ? `⚠️ Lệch pha (v${node.synced_source_version} → v${node.current_source_version})`
                            : `✓ Synced`}
                        </span>
                      </div>

                      <div className="node-body">
                        <strong className="node-title" title={node.title}>
                          {node.title}
                        </strong>
                        <div className="node-version-row">
                          <small>Phiên bản Story con: v{node.version}</small>
                        </div>

                        {node.impacted_case_ids && node.impacted_case_ids.length > 0 && (
                          <div className="impacted-pill-box">
                            <small>Test case chịu tác động:</small>
                            <div className="tc-tags-row">
                              {node.impacted_case_ids.map(tc => (
                                <code key={tc}>{tc}</code>
                              ))}
                            </div>
                          </div>
                        )}
                      </div>

                      <div className="node-card-footer">
                        <button
                          className="link-button"
                          onClick={() => onOpenStory(node.id)}
                          title="Mở Story này"
                        >
                          Mở story <ExternalLink size={12} />
                        </button>
                        <button
                          className="icon-button delete-edge-btn"
                          disabled={busyAction === `remove-${workspace.id}-${node.id}`}
                          onClick={() => void handleRemoveEdge(workspace.id, node.id)}
                          title="Xóa liên kết phụ thuộc"
                        >
                          <Trash2 size={13} />
                        </button>
                      </div>
                    </div>
                  )
                })}

                {downstreamNodes.length === 0 && (
                  <div className="empty-node-slot">
                    <p>Story này là End Node (Chưa có Story hạ nguồn nào liên kết)</p>
                  </div>
                )}
              </div>
            </div>
          </div>
        )}
      </div>

      {/* Contract & Impact Summary Card */}
      <div className="journey-summary-grid">
        <div className="card summary-card">
          <div className="card-header-clean">
            <ShieldCheck size={18} className="text-green" />
            <h3>Ma Trận Ràng Buộc Hợp Đồng (Contract Binding Matrix)</h3>
          </div>
          <p className="summary-desc">
            Quy định các trường dữ liệu (`consumed_outputs`) và điều kiện nghiệp vụ (`bound_rules`)
            kết nối giữa các Story. Khi Story cha sửa đổi, hệ thống chỉ kích hoạt cảnh báo nếu Delta
            giao thoa trực tiếp với các trường này (Triệt tiêu 100% báo động giả).
          </p>
          <div className="binding-rules-table">
            <table className="qa-table">
              <thead>
                <tr>
                  <th>Chiều phụ thuộc</th>
                  <th>Story đối ứng</th>
                  <th>Loại liên kết</th>
                  <th>Trạng thái đồng bộ</th>
                </tr>
              </thead>
              <tbody>
                {upstreamNodes.map(u => (
                  <tr key={`up-${u.id}`}>
                    <td>
                      <span className="direction-badge upstream-dir">← Thượng nguồn</span>
                    </td>
                    <td>
                      <strong>{u.title}</strong>
                    </td>
                    <td><code>{u.dependency_type}</code></td>
                    <td>
                      <span
                        className={`badge ${
                          u.impact_status === 'suspect_stale'
                            ? 'badge-stale'
                            : 'badge-approved'
                        }`}
                      >
                        {u.impact_status}
                      </span>
                    </td>
                  </tr>
                ))}
                {downstreamNodes.map(d => (
                  <tr key={`down-${d.id}`}>
                    <td>
                      <span className="direction-badge downstream-dir">Hạ nguồn →</span>
                    </td>
                    <td>
                      <strong>{d.title}</strong>
                    </td>
                    <td><code>{d.dependency_type}</code></td>
                    <td>
                      <span
                        className={`badge ${
                          d.impact_status === 'suspect_stale'
                            ? 'badge-stale'
                            : 'badge-approved'
                        }`}
                      >
                        {d.impact_status}
                      </span>
                    </td>
                  </tr>
                ))}
                {upstreamNodes.length === 0 && downstreamNodes.length === 0 && (
                  <tr>
                    <td colSpan={4} className="text-center empty-table-td">
                      Chưa có liên kết phụ thuộc nào. Nhấn "+ Thêm Liên Kết Phụ Thuộc" để tạo chuỗi E2E.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>

        <div className="card enterprise-guarantee-card">
          <div className="card-header-clean">
            <Lock size={18} className="text-cyan" />
            <h3>Bảo Đảm Kỹ Thuật Chuẩn Enterprise</h3>
          </div>
          <ul className="enterprise-feature-list">
            <li>
              <strong>1. PostgreSQL Advisory Lock Transaction</strong>
              <p>Khóa toàn bộ đồ thị theo Workspace ID, ngăn chặn race condition khi nhiều QA liên kết đồng thời.</p>
            </li>
            <li>
              <strong>2. No Depth = 3 Cutoff</strong>
              <p>Phân tích tác động duyệt toàn bộ đồ thị (Full Transitive Closure) từ Auth đến Inventory mà không có điểm mù.</p>
            </li>
            <li>
              <strong>3. Granular Test Case Invalidation</strong>
              <p>Chỉ khoanh vùng Test Case có liên quan trực tiếp đến contract bị đổi, giữ nguyên các Test Case độc lập.</p>
            </li>
          </ul>
        </div>
      </div>

      {/* Modal Add Dependency Edge */}
      {showAddModal && (
        <div className="modal-backdrop" role="dialog" aria-modal="true">
          <div className="conflict-modal-card add-edge-modal">
            <div className="conflict-modal-header">
              <div className="header-title-group">
                <div className="conflict-icon-badge">
                  <Link2 size={22} />
                </div>
                <div>
                  <h3>Thiết Lập Liên Kết Phụ Thuộc Liên Story</h3>
                  <p>Xây dựng chuỗi hành trình kiểm thử E2E User Journey</p>
                </div>
              </div>
              <button
                className="icon-button close-btn"
                onClick={() => setShowAddModal(false)}
                aria-label="Đóng"
              >
                <X size={18} />
              </button>
            </div>

            {addError && (
              <div className="conflict-error-banner">
                <AlertCircle size={16} />
                <span>{addError}</span>
              </div>
            )}

            <form onSubmit={handleCreateEdge} className="add-edge-form">
              <div className="form-group">
                <label className="form-label">Chiều liên kết (Direction):</label>
                <div className="radio-pill-group">
                  <label className={`radio-pill ${modalDirection === 'upstream' ? 'selected' : ''}`}>
                    <input
                      type="radio"
                      name="direction"
                      checked={modalDirection === 'upstream'}
                      onChange={() => setModalDirection('upstream')}
                    />
                    <span>Story này phụ thuộc vào Story khác (Thượng nguồn)</span>
                  </label>
                  <label className={`radio-pill ${modalDirection === 'downstream' ? 'selected' : ''}`}>
                    <input
                      type="radio"
                      name="direction"
                      checked={modalDirection === 'downstream'}
                      onChange={() => setModalDirection('downstream')}
                    />
                    <span>Story khác phụ thuộc vào Story này (Hạ nguồn)</span>
                  </label>
                </div>
              </div>

              <div className="form-group">
                <label className="form-label">
                  {modalDirection === 'upstream'
                    ? 'Chọn Story Thượng Nguồn (Cung cấp dữ liệu):'
                    : 'Chọn Story Hạ Nguồn (Tiêu thụ dữ liệu):'}
                </label>
                <select
                  className="form-select"
                  value={selectedStoryId}
                  onChange={e => setSelectedStoryId(e.target.value)}
                  required
                >
                  <option value="">-- Chọn User Story --</option>
                  {candidateStories.map(s => (
                    <option key={s.id} value={s.id}>
                      {s.title} (v{s.version})
                    </option>
                  ))}
                </select>
              </div>

              <div className="form-group">
                <label className="form-label">Loại liên kết (Dependency Type):</label>
                <select
                  className="form-select"
                  value={depType}
                  onChange={e => setDepType(e.target.value)}
                >
                  <option value="data_fixture">Dữ liệu cố định / Output Fixture (data_fixture)</option>
                  <option value="precondition">Điều kiện tiên quyết / Auth (precondition)</option>
                  <option value="schema_contract">Ràng buộc hợp đồng Schema (schema_contract)</option>
                </select>
              </div>

              <div className="form-group">
                <label className="form-label">
                  Các trường dữ liệu tiêu thụ (Consumed Outputs):
                  <small className="help-subtext">Cách nhau bằng dấu phẩy</small>
                </label>
                <input
                  type="text"
                  className="form-input"
                  placeholder="ví dụ: cart_id, total_amount, cart_items"
                  value={consumedOutputsInput}
                  onChange={e => setConsumedOutputsInput(e.target.value)}
                />
              </div>

              <div className="form-group">
                <label className="form-label">
                  Quy tắc nghiệp vụ ràng buộc (Bound Rules):
                  <small className="help-subtext">Cách nhau bằng dấu phẩy</small>
                </label>
                <input
                  type="text"
                  className="form-input"
                  placeholder="ví dụ: min_order_threshold, max_items_limit"
                  value={boundRulesInput}
                  onChange={e => setBoundRulesInput(e.target.value)}
                />
              </div>

              <div className="cycle-protection-note">
                <Lock size={15} />
                <span>
                  <strong>Chống Chu Trình Tự Động:</strong> Thuật toán Kahn & Advisory Lock sẽ kiểm tra
                  đồ thị. Nếu liên kết này tạo thành chu trình vô tận ($A \rightarrow B \rightarrow A$),
                  yêu cầu sẽ bị từ chối an toàn với mã lỗi 409.
                </span>
              </div>

              <div className="conflict-modal-footer">
                <button
                  type="button"
                  className="button button-ghost"
                  onClick={() => setShowAddModal(false)}
                >
                  Hủy
                </button>
                <button
                  type="submit"
                  className="button"
                  disabled={busyAction === 'create-edge'}
                >
                  {busyAction === 'create-edge' ? 'Đang kiểm tra & tạo...' : 'Tạo Liên Kết Phụ Thuộc'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  )
}
