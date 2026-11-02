import React, { useEffect, useState } from 'react'
import {
  AlertTriangle,
  ArrowRight,
  Boxes,
  Check,
  CheckCircle2,
  ChevronDown,
  ChevronUp,
  Download,
  ExternalLink,
  Layers,
  Pencil,
  RefreshCw,
  Search,
  Sparkles,
  Workflow,
  X,
} from 'lucide-react'
import { api } from './api'
import type { Story, StoryCollection } from './types'

interface StoryCollectionsPanelProps {
  stories: Story[]
  currentStoryId?: string
  onSelectStory: (storyId: string) => void
  onOpenGraph: (storyId: string) => void
}

export const StoryCollectionsPanel: React.FC<StoryCollectionsPanelProps> = ({
  stories,
  currentStoryId,
  onSelectStory,
  onOpenGraph,
}) => {
  const [collections, setCollections] = useState<StoryCollection[]>([])
  const [loading, setLoading] = useState(false)
  const [searchTerm, setSearchTerm] = useState('')
  const [activeTab, setActiveTab] = useState<'collections' | 'standalone'>('collections')
  const [editingColId, setEditingColId] = useState<string | null>(null)
  const [editingName, setEditingName] = useState('')
  const [collapsedCols, setCollapsedCols] = useState<Record<string, boolean>>({})

  const fetchCollections = async () => {
    try {
      setLoading(true)
      const data = await api.listCollections()
      setCollections(data)
    } catch (err) {
      console.error('Lỗi tải collections:', err)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    void fetchCollections()
  }, [])

  const handleAutoDiscover = async () => {
    try {
      setLoading(true)
      const res = await api.autoDiscoverCollections()
      setCollections(res.synced_collections)
    } catch (err) {
      console.error('Lỗi auto-discover:', err)
    } finally {
      setLoading(false)
    }
  }

  const handleUpdateName = async (colId: string) => {
    if (!editingName.trim()) return
    try {
      const updated = await api.updateCollection(colId, { name: editingName.trim() })
      setCollections(prev => prev.map(c => (c.id === colId ? updated : c)))
      setEditingColId(null)
    } catch (err) {
      console.error('Lỗi đổi tên collection:', err)
    }
  }

  const toggleCollapse = (colId: string) => {
    setCollapsedCols(prev => ({ ...prev, [colId]: !prev[colId] }))
  }

  // Calculate Standalone Stories
  const clusteredStoryIds = new Set(
    collections.flatMap(c => c.members.map(m => m.story_id))
  )
  const standaloneStories = stories.filter(s => !clusteredStoryIds.has(s.id))

  const filteredCollections = collections.filter(
    c =>
      c.name.toLowerCase().includes(searchTerm.toLowerCase()) ||
      c.code.toLowerCase().includes(searchTerm.toLowerCase()) ||
      c.members.some(m => m.story_title.toLowerCase().includes(searchTerm.toLowerCase()))
  )

  const filteredStandalone = standaloneStories.filter(
    s =>
      s.title.toLowerCase().includes(searchTerm.toLowerCase()) ||
      s.description?.toLowerCase().includes(searchTerm.toLowerCase())
  )

  const totalStoriesInCollections = collections.reduce((acc, c) => acc + c.total_stories, 0)
  const totalTestCases = collections.reduce((acc, c) => acc + c.total_test_cases, 0)
  const staleCount = collections.filter(c => c.health_status === 'suspect_stale').length

  return (
    <div className="collections-dashboard">
      {/* Sleek Compact Header & KPI Strip */}
      <div className="collections-hero-card">
        <div className="hero-main-row">
          <div className="hero-title-group">
            <div className="hero-tag-badge">
              <span className="dot-live" />
              <span>E2E Journey Orchestration • v3.0</span>
            </div>
            <h2>Story Collections</h2>
            <p>
              Tự động gom cụm các User Story có liên kết DAG thành kịch bản kiểm thử luồng liên hoàn,
              truyền dữ liệu runtime và loại bỏ 100% kịch bản trùng lặp.
            </p>
          </div>

          <div className="hero-action-group">
            <button
              className="sync-action-btn"
              onClick={handleAutoDiscover}
              disabled={loading}
              title="Quét lại đồ thị DAG để tự động đồng bộ"
            >
              <RefreshCw size={14} className={loading ? 'spinning' : ''} />
              <span>{loading ? 'Đang đồng bộ...' : 'Đồng bộ đồ thị'}</span>
            </button>
          </div>
        </div>

        {/* Refined Metric Strip */}
        <div className="hero-metric-strip">
          <div className="metric-item">
            <span className="metric-number">{collections.length}</span>
            <span className="metric-caption">Cụm Luồng (Collections)</span>
          </div>
          <div className="metric-divider" />
          <div className="metric-item">
            <span className="metric-number">{totalStoriesInCollections}</span>
            <span className="metric-caption">Stories trong luồng</span>
          </div>
          <div className="metric-divider" />
          <div className="metric-item">
            <span className="metric-number highlight-green">{totalTestCases}</span>
            <span className="metric-caption">Test Cases E2E</span>
          </div>
          <div className="metric-divider" />
          <div className="metric-item">
            <span className="metric-number">{standaloneStories.length}</span>
            <span className="metric-caption">Stories độc lập</span>
          </div>
          <div className="metric-divider" />
          <div className="metric-item health-item">
            <span className={`health-pill ${staleCount > 0 ? 'health-warning' : 'health-healthy'}`}>
              {staleCount > 0 ? (
                <>
                  <AlertTriangle size={12} /> {staleCount} luồng lệch pha
                </>
              ) : (
                <>
                  <CheckCircle2 size={12} /> 100% Đồng bộ
                </>
              )}
            </span>
            <span className="metric-caption">Trạng thái sức khỏe</span>
          </div>
        </div>
      </div>

      {/* Modern Control Bar: Segmented Tab Switcher + Sleek Search */}
      <div className="collections-control-bar">
        <div className="segmented-pill-tabs">
          <button
            className={`tab-pill ${activeTab === 'collections' ? 'active' : ''}`}
            onClick={() => setActiveTab('collections')}
          >
            <Boxes size={14} />
            <span>Cụm Luồng E2E</span>
            <span className="counter-bubble">{collections.length}</span>
          </button>

          <button
            className={`tab-pill ${activeTab === 'standalone' ? 'active' : ''}`}
            onClick={() => setActiveTab('standalone')}
          >
            <Layers size={14} />
            <span>Story Độc Lập</span>
            <span className="counter-bubble">{standaloneStories.length}</span>
          </button>
        </div>

        <div className="sleek-search-wrapper">
          <Search size={14} className="search-icon" />
          <input
            type="text"
            placeholder={
              activeTab === 'collections'
                ? 'Tìm theo tên luồng, mã COL hoặc Story...'
                : 'Tìm theo tiêu đề Story độc lập...'
            }
            value={searchTerm}
            onChange={e => setSearchTerm(e.target.value)}
          />
          {searchTerm && (
            <button className="clear-search-btn" onClick={() => setSearchTerm('')}>
              <X size={12} />
            </button>
          )}
        </div>
      </div>

      {/* Main Content Area */}
      {activeTab === 'collections' ? (
        <div className="collections-feed">
          {filteredCollections.length === 0 ? (
            <div className="empty-slate-card">
              <Boxes size={40} className="slate-icon" />
              <h3>Chưa có cụm luồng nào phù hợp</h3>
              <p>
                {searchTerm
                  ? 'Thử thay đổi từ khóa tìm kiếm.'
                  : 'Hãy liên kết các Story qua Đồ thị luồng DAG để hệ thống tự động gom thành Collection.'}
              </p>
              <button className="sync-action-btn" onClick={handleAutoDiscover}>
                <Sparkles size={14} /> Quét lại đồ thị
              </button>
            </div>
          ) : (
            filteredCollections.map(col => {
              const isStale = col.health_status === 'suspect_stale'
              const isCollapsed = collapsedCols[col.id] ?? false

              return (
                <div
                  key={col.id}
                  className={`streamlined-collection-card ${isStale ? 'border-stale' : 'border-synced'}`}
                >
                  {/* Card Header */}
                  <div className="card-top-row">
                    <div className="col-info-col">
                      <div className="col-badges-row">
                        <span className="col-code-tag">{col.code}</span>
                        <span className={`status-pill ${isStale ? 'pill-stale' : 'pill-synced'}`}>
                          {isStale ? (
                            <>
                              <AlertTriangle size={11} /> Cần Re-Sync
                            </>
                          ) : (
                            <>
                              <CheckCircle2 size={11} /> Đã đồng bộ
                            </>
                          )}
                        </span>
                        <span className="meta-text-muted">
                          {col.total_stories} Stories • {col.total_test_cases} Test Cases
                        </span>
                      </div>

                      {editingColId === col.id ? (
                        <div className="inline-title-editor">
                          <input
                            type="text"
                            value={editingName}
                            onChange={e => setEditingName(e.target.value)}
                            onKeyDown={e => {
                              if (e.key === 'Enter') void handleUpdateName(col.id)
                              if (e.key === 'Escape') setEditingColId(null)
                            }}
                            autoFocus
                          />
                          <button
                            className="editor-btn save"
                            onClick={() => void handleUpdateName(col.id)}
                            title="Lưu"
                          >
                            <Check size={13} />
                          </button>
                          <button
                            className="editor-btn cancel"
                            onClick={() => setEditingColId(null)}
                            title="Hủy"
                          >
                            <X size={13} />
                          </button>
                        </div>
                      ) : (
                        <div className="title-with-edit">
                          <h3
                            className="col-display-title"
                            onClick={() => {
                              setEditingColId(col.id)
                              setEditingName(col.name)
                            }}
                            title="Bấm để chỉnh sửa tên luồng"
                          >
                            {col.name}
                          </h3>
                          <button
                            className="mini-edit-btn"
                            onClick={() => {
                              setEditingColId(col.id)
                              setEditingName(col.name)
                            }}
                            title="Đổi tên luồng"
                          >
                            <Pencil size={12} />
                          </button>
                        </div>
                      )}

                      {col.description && (
                        <p className="col-brief-desc">{col.description}</p>
                      )}
                    </div>

                    <div className="col-actions-col">
                      <a
                        href={api.getCollectionExportUrl(col.id)}
                        className="export-postman-btn"
                        download
                        title="Xuất Postman Collection v2.1 với Test Scripts tự động"
                      >
                        <Download size={13} />
                        <span>Xuất Postman</span>
                      </a>

                      <button
                        className="collapse-toggle-btn"
                        onClick={() => toggleCollapse(col.id)}
                        title={isCollapsed ? 'Mở rộng chi tiết' : 'Thu gọn chi tiết'}
                      >
                        {isCollapsed ? <ChevronDown size={16} /> : <ChevronUp size={16} />}
                      </button>
                    </div>
                  </div>

                  {/* Collapsible Pipeline Timeline */}
                  {!isCollapsed && (
                    <div className="stepper-pipeline-section">
                      <div className="stepper-header-label">
                        <span>HÀNH TRÌNH KIỂM THỬ TUẦN TỰ (TOPOLOGICAL E2E PIPELINE)</span>
                      </div>

                      <div className="stepper-scroll-track">
                        {col.members.map((member, index) => {
                          const isCurrent = member.story_id === currentStoryId
                          const isFirst = index === 0
                          const isLast = index === col.members.length - 1

                          return (
                            <React.Fragment key={member.id}>
                              <div
                                className={`step-flow-node ${isCurrent ? 'is-active-focus' : ''}`}
                              >
                                <div className="step-node-header">
                                  <span className="step-order-badge">#{member.sequence_order}</span>
                                  <span className={`step-role-pill role-${member.role_in_flow}`}>
                                    {isFirst ? 'Entry' : isLast ? 'Terminal' : 'Step'}
                                  </span>
                                </div>

                                <div className="step-node-body">
                                  <h4
                                    className="node-story-title"
                                    onClick={() => onSelectStory(member.story_id)}
                                    title={member.story_title}
                                  >
                                    {member.story_title}
                                  </h4>
                                  <div className="node-meta-row">
                                    <span>v{member.story_version}</span>
                                    <span>•</span>
                                    <span>{member.test_cases_count} cases</span>
                                  </div>

                                  <div className="node-footer-links">
                                    <button
                                      className="text-link"
                                      onClick={() => onSelectStory(member.story_id)}
                                    >
                                      <span>Mở Story</span>
                                      <ExternalLink size={10} />
                                    </button>
                                    <button
                                      className="text-link secondary"
                                      onClick={() => onOpenGraph(member.story_id)}
                                      title="Xem Đồ thị DAG của Story này"
                                    >
                                      <Workflow size={11} />
                                      <span>DAG</span>
                                    </button>
                                  </div>
                                </div>
                              </div>

                              {!isLast && (
                                <div className="pipe-arrow-bridge">
                                  <div className="pipe-line" />
                                  <div
                                    className="pipe-token-badge"
                                    title="Kênh truyền biến tự động (Data Pipe)"
                                  >
                                    <span>Data Pipe</span>
                                    <ArrowRight size={11} />
                                  </div>
                                </div>
                              )}
                            </React.Fragment>
                          )
                        })}
                      </div>
                    </div>
                  )}
                </div>
              )
            })
          )}
        </div>
      ) : (
        /* Standalone Stories View */
        <div className="standalone-feed">
          <div className="standalone-helper-bar">
            <span>
              Các Story dưới đây đang hoạt động độc lập (chưa liên kết Thượng nguồn / Hạ nguồn).
              Bạn có thể mở đồ thị DAG của từng Story để kết nối vào một Luồng E2E.
            </span>
          </div>

          <div className="standalone-cards-grid">
            {filteredStandalone.map(story => (
              <div key={story.id} className="standalone-item-card">
                <div className="standalone-item-top">
                  <span className="standalone-version-tag">Story v{story.version}</span>
                  <span className="criteria-count">
                    {story.acceptance_criteria?.length ?? 0} ACs
                  </span>
                </div>

                <h4
                  className="standalone-item-title"
                  onClick={() => onSelectStory(story.id)}
                  title={story.title}
                >
                  {story.title}
                </h4>

                <p className="standalone-item-desc">
                  {story.description?.slice(0, 110)}
                  {(story.description?.length ?? 0) > 110 ? '...' : ''}
                </p>

                <div className="standalone-item-actions">
                  <button
                    className="button-ghost-small"
                    onClick={() => onSelectStory(story.id)}
                  >
                    Mở Story
                  </button>
                  <button
                    className="button-connect-small"
                    onClick={() => onOpenGraph(story.id)}
                    title="Mở Đồ thị DAG để liên kết Thượng nguồn / Hạ nguồn"
                  >
                    <Workflow size={12} />
                    <span>Ghép vào Luồng</span>
                  </button>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
