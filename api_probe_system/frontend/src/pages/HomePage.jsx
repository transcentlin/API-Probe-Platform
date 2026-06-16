// 修改历史 (Revision History)
// ==================================
// 版本: v1.0.11
// 日期: 2026-06-16
// 修改说明: 重构搜索动作栏为与卡片网格完全对齐的 Grid 响应式布局，解决在宽屏模式下搜索框宽度与卡片宽度失衡的问题；同时进一步增强过滤条件匹配健壮度，支持无缝名称与 URL 关键字搜索。
// ----------------------------------
// 版本: v1.0.10
// 日期: 2026-06-16
// 修改说明: 将搜索框的容器宽度由 300px 扩大至 350px，与平台卡片的标准最小宽度完美对齐；同时重构过滤逻辑，支持按名称(name) and URL(base_url) 进行双向关键字匹配检索。
// ----------------------------------
// 版本: v1.0.9
// 日期: 2026-06-16
// 修改说明: 优化全选控制栏样式，移除了按钮边框和背景，改写文案为“全选 (x个)”，并通过容器 margin 调整实现与上下组件完美等距。
// ----------------------------------
// 版本: v1.0.8
// 日期: 2026-06-16
// 修改说明: 在搜索过滤框正下方（卡片上方）新增“全选所有平台”常驻勾选控制栏，支持一键批量勾选/清空过滤后的平台卡片，并智能实现卡片多选状态与全选按钮的自动双向联动。
// ----------------------------------
// 版本: v1.0.7
// 日期: 2026-06-16
// 修改说明: 解除卡片“勾选对比”在平台未测试（hasReport为false）时的禁用限制以支持批量探测；优化底部对比栏 show 条件（>=1个即可出现）；调整“一键横向对比”按钮的禁用与 title 条件为已测平台数少于 2 时禁用。
// ----------------------------------
// 版本: v1.0.6
// 日期: 2026-06-16
// 修改说明: 接收 onStartTest 属性；在底部多选浮动对比栏中增加“批量标准探测”和“批量深度探测”按钮，并结合 selectedForCompare 与 runningTests 状态进行防并发多路占位和动态置灰控制。
// ----------------------------------
// 版本: v1.0.5
// 日期: 2026-06-16
// 修改说明: 限制平台过滤搜索只按名称 name 进行，避免因 Base URL 内含 open/api 等通用字符引发无关平台被匹配；重构卡片布局，将激活开关移到标签行最右侧，并统一在该行展示“已测/未测/探测中”状态，移除卡片底部冗余拥挤的信息。
// ----------------------------------
// 版本: v1.0.4
// 日期: 2026-06-16
// 修改说明: 引入 warnings 属性，支持查找是否存在平台发现异常，并在卡片标题处渲染闪烁的“兼容性异常”警示标以及应用异常外发光 CSS 特效。
// ----------------------------------
// 版本: v1.0.3
// 日期: 2026-06-16
// 修改说明: 在卡片动作区中添加启用/禁用的 Switch 切换开关组件，允许用户直观控制激活或关闭单个平台。
// ----------------------------------
// 版本: v1.0.2
// 日期: 2026-06-16
// 修改说明: 卡片右上角并排双环形展示“综合评分”和“可用模型数”两个数据，并增加模型数精致环形指示器组件，使用户对排序更易直观区分与理解。
// ----------------------------------
// 版本: v1.0.1
// 日期: 2026-06-16
// 修改说明: 主界面卡片新增“可用模型数”标签与“综合评分/可用模型数”及“降序/升序”双维度排序切换按钮，且无分探测置底。
// ==================================

import React, { useState } from 'react';
import { Plus, Eye, Play, Edit2, Trash2, ArrowLeftRight, CheckSquare, Square, ExternalLink, ArrowUpDown } from 'lucide-react';

export default function HomePage({ platforms, warnings = [], onSelectPlatform, onAddPlatform, onEditPlatform, onDeletePlatform, onToggleEnable, onCompare, runningTests, onStartTest }) {
  const [selectedForCompare, setSelectedForCompare] = useState([]);
  const [searchTerm, setSearchTerm] = useState('');
  const [sortKey, setSortKey] = useState('score'); // 'score' | 'models'
  const [sortOrder, setSortOrder] = useState('desc'); // 'desc' | 'asc'
  const [allHovered, setAllHovered] = useState(false);

  const anySelectedRunning = selectedForCompare.some(name => runningTests[name]);
  const validSelectedCount = selectedForCompare.filter(name => {
    const p = platforms.find(pl => pl.name === name);
    return p && p.score !== null;
  }).length;

  const toggleSelectCompare = (name) => {
    setSelectedForCompare(prev => {
      if (prev.includes(name)) {
        return prev.filter(n => n !== name);
      } else {
        return [...prev, name];
      }
    });
  };

  // 过滤平台 (支持按名称或 URL 过滤)
  const filteredPlatforms = platforms.filter(p => {
    const term = searchTerm.trim().toLowerCase();
    if (!term) return true;
    const matchName = p.name && p.name.toLowerCase().includes(term);
    const matchUrl = p.base_url && p.base_url.toLowerCase().includes(term);
    return matchName || matchUrl;
  });

  // 全选与取消全选联动逻辑
  const isAllSelected = filteredPlatforms.length > 0 && filteredPlatforms.every(p => selectedForCompare.includes(p.name));

  const toggleSelectAll = () => {
    if (isAllSelected) {
      // 取消全选：把当前过滤出并且勾选的平台名称全部剔除
      setSelectedForCompare(prev => prev.filter(name => !filteredPlatforms.some(p => p.name === name)));
    } else {
      // 一键全选：将当前过滤显示的平台中未勾选的名称全部追加
      setSelectedForCompare(prev => {
        const toAdd = filteredPlatforms.map(p => p.name).filter(name => !prev.includes(name));
        return [...prev, ...toAdd];
      });
    }
  };

  // 排序比较器 (双维度，且未测平台始终稳定置底)
  const sortedPlatforms = [...filteredPlatforms].sort((a, b) => {
    const hasScoreA = a.score !== null && a.score !== undefined;
    const hasScoreB = b.score !== null && b.score !== undefined;
    
    if (hasScoreA && !hasScoreB) return -1; // a 在前
    if (!hasScoreA && hasScoreB) return 1;  // b 在前
    if (!hasScoreA && !hasScoreB) return a.name.localeCompare(b.name); // 均未测，按名字字母升序
    
    if (sortKey === 'score') {
      const scoreA = parseFloat(a.score);
      const scoreB = parseFloat(b.score);
      if (scoreA !== scoreB) {
        return sortOrder === 'desc' ? scoreB - scoreA : scoreA - scoreB;
      }
    } else {
      const modelsA = a.active_models_count !== undefined ? a.active_models_count : 0;
      const modelsB = b.active_models_count !== undefined ? b.active_models_count : 0;
      if (modelsA !== modelsB) {
        return sortOrder === 'desc' ? modelsB - modelsA : modelsA - modelsB;
      }
    }
    return a.name.localeCompare(b.name);
  });

  // 渲染可用模型数虚线环
  const renderModelsRing = (count) => {
    const displayCount = count !== undefined && count !== null ? count : 0;
    return (
      <div className="score-circle-container" title="可用模型数" style={{ marginRight: '0.25rem' }}>
        <svg className="score-circle-svg">
          <circle 
            className="score-circle-bar" 
            cx="35" 
            cy="35" 
            r="30" 
            stroke="#06b6d4" 
            strokeDasharray="4 2" 
            strokeDashoffset="0"
            style={{ strokeWidth: 3 }}
          />
        </svg>
        <div className="score-text" style={{ color: '#06b6d4', fontSize: '1.2rem', display: 'flex', flexDirection: 'column', alignItems: 'center', lineHeight: 1.1 }}>
          <span style={{ fontWeight: 700 }}>{displayCount}</span>
          <span style={{ fontSize: '0.55rem', opacity: 0.8, marginTop: '1px', fontWeight: 600, letterSpacing: '0.05em' }}>模型</span>
        </div>
      </div>
    );
  };

  // 渲染评分圆环
  const renderScoreRing = (score) => {
    if (score === null || score === undefined) {
      return (
        <div className="score-circle-container" title="综合评分">
          <svg className="score-circle-svg">
            <circle className="score-circle-bg" cx="35" cy="35" r="30" />
          </svg>
          <div className="score-text" style={{ color: 'var(--text-dim)', fontSize: '1.2rem', display: 'flex', flexDirection: 'column', alignItems: 'center', lineHeight: 1.1 }}>
            <span style={{ fontWeight: 700 }}>—</span>
            <span style={{ fontSize: '0.55rem', opacity: 0.6, marginTop: '1px', fontWeight: 600, letterSpacing: '0.05em' }}>评分</span>
          </div>
        </div>
      );
    }

    const pct = parseFloat(score);
    const strokeDashoffset = 188.5 - (pct / 100) * 188.5;
    
    // 渐变分级配色
    let strokeColor = '#ef4444'; // 红色
    if (pct >= 80) strokeColor = '#10b981'; // 绿色
    else if (pct >= 40) strokeColor = '#f59e0b'; // 黄色

    return (
      <div className="score-circle-container" title="综合评分">
        <svg className="score-circle-svg">
          <circle className="score-circle-bg" cx="35" cy="35" r="30" />
          <circle 
            className="score-circle-bar" 
            cx="35" 
            cy="35" 
            r="30" 
            stroke={strokeColor}
            strokeDasharray="188.5"
            strokeDashoffset={strokeDashoffset}
            style={{ strokeWidth: 4 }}
          />
        </svg>
        <div className="score-text" style={{ color: strokeColor, fontSize: '1.2rem', display: 'flex', flexDirection: 'column', alignItems: 'center', lineHeight: 1.1 }}>
          <span style={{ fontWeight: 700 }}>{pct.toFixed(0)}</span>
          <span style={{ fontSize: '0.55rem', opacity: 0.8, marginTop: '1px', fontWeight: 600, letterSpacing: '0.05em' }}>评分</span>
        </div>
      </div>
    );
  };

  return (
    <div style={{ flex: 1, display: 'flex', flexDirection: 'column' }}>
      {/* 搜索与动作栏 (使用与网格对齐的 Grid 布局) */}
      <div 
        style={{ 
          display: 'grid', 
          gridTemplateColumns: 'repeat(auto-fill, minmax(350px, 1fr))', 
          gap: '1.5rem', 
          padding: '2rem 2rem 0.5rem 2rem', 
          maxWidth: '1400px', 
          margin: '0 auto', 
          width: '100%' 
        }}
      >
        {/* 搜索框在网格第一列中占据 100% 宽度，物理对齐下方第一列卡片 */}
        <div style={{ position: 'relative', width: '100%' }}>
          <input
            type="text"
            className="form-control"
            placeholder="搜索平台或 URL..."
            value={searchTerm}
            onChange={e => setSearchTerm(e.target.value)}
            style={{ width: '100%' }}
          />
        </div>
        {/* 动作栏跨越剩余列并靠右对齐 */}
        <div 
          style={{ 
            gridColumn: '2 / -1', 
            display: 'flex', 
            justifyContent: 'flex-end', 
            alignItems: 'center', 
            gap: '0.75rem' 
          }}
        >
          {/* 排序属性切换 */}
          <button 
            className="btn btn-secondary" 
            style={{ display: 'flex', alignItems: 'center', gap: '0.4rem', whiteSpace: 'nowrap', padding: '0.5rem 1rem', fontSize: '0.8rem' }}
            onClick={() => setSortKey(prev => prev === 'score' ? 'models' : 'score')}
          >
            排序: {sortKey === 'score' ? '综合评分' : '可用模型数'}
          </button>
          {/* 排序方向切换 */}
          <button 
            className="btn btn-secondary" 
            style={{ display: 'flex', alignItems: 'center', gap: '0.4rem', whiteSpace: 'nowrap', padding: '0.5rem 1rem', fontSize: '0.8rem' }}
            onClick={() => setSortOrder(prev => prev === 'desc' ? 'asc' : 'desc')}
          >
            <ArrowUpDown size={12} /> {sortOrder === 'desc' ? '高 → 低' : '低 → 高'}
          </button>
          <button className="btn btn-primary" onClick={onAddPlatform} style={{ padding: '0.5rem 1rem', fontSize: '0.8rem' }}>
            <Plus size={16} /> 添加平台
          </button>
        </div>
      </div>

      {/* 全选控制栏（红框区域） */}
      {filteredPlatforms.length > 0 && (
        <div style={{ padding: '0 2rem', marginTop: '0.75rem', marginBottom: '-0.75rem', maxWidth: '1400px', marginLeft: 'auto', marginRight: 'auto', width: '100%', display: 'flex', alignItems: 'center' }}>
          <button
            type="button"
            style={{
              background: 'none',
              border: 'none',
              padding: 0,
              cursor: 'pointer',
              color: allHovered ? 'var(--text-bright, #fff)' : 'var(--text-dim, #94a3b8)',
              display: 'inline-flex',
              alignItems: 'center',
              gap: '0.5rem',
              fontFamily: 'inherit',
              fontSize: '0.875rem',
              transition: 'color 0.2s ease'
            }}
            onClick={toggleSelectAll}
            onMouseEnter={() => setAllHovered(true)}
            onMouseLeave={() => setAllHovered(false)}
          >
            {isAllSelected ? (
              <CheckSquare size={14} color="#3b82f6" />
            ) : (
              <Square size={14} />
            )}
            <span>全选 ({filteredPlatforms.length}个)</span>
          </button>
        </div>
      )}

      {/* 平台网格卡片 */}
      {sortedPlatforms.length === 0 ? (
        <div style={{ flex: 1, display: 'flex', justifyContent: 'center', alignItems: 'center', flexDirection: 'column', color: 'var(--text-dim)', padding: '5rem 0' }}>
          <p style={{ fontSize: '1.25rem', marginBottom: '1rem' }}>没有找到任何探测平台</p>
          <button className="btn btn-secondary" onClick={onAddPlatform}>添加第一个平台</button>
        </div>
      ) : (
        <div className="dashboard-grid">
          {sortedPlatforms.map(p => {
            const isRunning = runningTests[p.name] || false;
            const hasReport = p.score !== null;
            const platformWarning = warnings.find(w => w.platform_name === p.name);

            return (
              <div key={p.name} className={`glass-card ${platformWarning ? 'card-error-glow' : ''}`} style={{ opacity: p.enabled ? 1 : 0.6 }}>
                {/* 头部：名称、评分、状态 */}
                <div className="flex-between" style={{ marginBottom: '1.25rem' }}>
                  <div style={{ cursor: 'pointer' }} onClick={() => onSelectPlatform(p)}>
                    <h3 style={{ fontFamily: 'var(--font-title)', fontSize: '1.25rem', fontWeight: 700, display: 'flex', alignItems: 'center', gap: '0.5rem', flexWrap: 'wrap' }}>
                      {p.name}
                      {p.website && (
                        <a href={p.website} target="_blank" rel="noreferrer" style={{ color: 'var(--text-dim)' }} onClick={e => e.stopPropagation()}>
                          <ExternalLink size={14} />
                        </a>
                      )}
                      {platformWarning && (
                        <span className="card-compatibility-badge" title={`最近探测出错：${platformWarning.error_message}`}>
                          ⚠️ 兼容性异常
                        </span>
                      )}
                    </h3>
                    <div style={{ fontSize: '0.75rem', color: 'var(--text-dim)', marginTop: '0.15rem', wordBreak: 'break-all', maxWidth: '220px' }}>
                      {p.base_url}
                    </div>
                  </div>
                  <div className="flex-align" style={{ gap: '0.5rem' }}>
                    {p.score !== null && renderModelsRing(p.active_models_count)}
                    {renderScoreRing(p.score)}
                  </div>
                </div>

                {/* 模型和格式标签与激活开关这一行 */}
                <div className="flex-between" style={{ marginBottom: '0.75rem' }}>
                  <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.4rem', alignItems: 'center' }}>
                    <span style={{ background: 'rgba(59, 130, 246, 0.15)', color: '#93c5fd', padding: '0.2rem 0.5rem', borderRadius: '4px', fontSize: '0.7rem', fontWeight: 600 }}>
                      {p.discovery_handler.toUpperCase()}
                    </span>
                    
                    {/* 统一展示三种状态：探测中、已测、闲置 */}
                    {isRunning ? (
                      <span style={{ background: 'rgba(6, 182, 212, 0.15)', color: '#22d3ee', padding: '0.2rem 0.5rem', borderRadius: '4px', fontSize: '0.7rem', fontWeight: 600, display: 'inline-flex', alignItems: 'center', gap: '0.25rem' }}>
                        <span className="status-dot running" style={{ width: '6px', height: '6px' }} /> 探测中
                      </span>
                    ) : hasReport ? (
                      <span style={{ background: 'rgba(16, 185, 129, 0.15)', color: '#6ee7b7', padding: '0.2rem 0.5rem', borderRadius: '4px', fontSize: '0.7rem', fontWeight: 600 }}>
                        已测
                      </span>
                    ) : (
                      <span style={{ background: 'rgba(255, 255, 255, 0.06)', color: 'var(--text-dim)', padding: '0.2rem 0.5rem', borderRadius: '4px', fontSize: '0.7rem', fontWeight: 600 }}>
                        闲置
                      </span>
                    )}
                  </div>

                  {/* 激活/禁用小开关移到此行最右侧 */}
                  <label className="switch-container" title={p.enabled ? "禁用该平台" : "启用该平台"}>
                    <input 
                      type="checkbox" 
                      checked={p.enabled} 
                      onChange={(e) => onToggleEnable(p.name, e.target.checked)}
                      disabled={isRunning}
                    />
                    <span className="switch-slider" />
                  </label>
                </div>

                <div style={{ marginBottom: '1.25rem' }}>

                  {/* Top 模型列表 */}
                  {p.top_models && p.top_models.length > 0 ? (
                    <div>
                      <div style={{ fontSize: '0.75rem', color: 'var(--text-dim)', marginBottom: '0.35rem' }}>首选推荐模型:</div>
                      <div style={{ display: 'flex', flexDirection: 'column', gap: '0.25rem' }}>
                        {p.top_models.map(m => (
                          <div key={m} style={{ fontSize: '0.8rem', background: 'rgba(255,255,255,0.02)', padding: '0.25rem 0.5rem', borderRadius: '4px', borderLeft: '2px solid hsl(var(--color-primary))', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                            <code>{m}</code>
                          </div>
                        ))}
                      </div>
                    </div>
                  ) : (
                    <div style={{ fontSize: '0.75rem', color: 'var(--text-dim)', fontStyle: 'italic', padding: '0.5rem 0' }}>
                      暂无测试报告，请先运行测试
                    </div>
                  )}
                </div>

                {/* 备注 */}
                {p.notes && (
                  <p style={{ fontSize: '0.75rem', color: 'var(--text-dim)', borderTop: '1px solid rgba(255,255,255,0.05)', paddingTop: '0.75rem', marginBottom: '1.25rem', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                    备注: {p.notes}
                  </p>
                )}

                {/* 动作区 */}
                <div className="flex-between" style={{ borderTop: '1px solid rgba(255,255,255,0.05)', paddingTop: '0.75rem' }}>
                  {/* 对比勾选 */}
                  <button 
                    type="button" 
                    className="btn btn-secondary" 
                    style={{ padding: '0.35rem 0.75rem', fontSize: '0.75rem' }}
                    onClick={() => toggleSelectCompare(p.name)}
                  >
                    {selectedForCompare.includes(p.name) ? (
                      <>
                        <CheckSquare size={14} color="#3b82f6" /> 已选对比
                      </>
                    ) : (
                      <>
                        <Square size={14} /> 勾选对比
                      </>
                    )}
                  </button>

                  <div className="flex-align" style={{ gap: '0.5rem' }}>
                    <button className="btn btn-secondary btn-icon-only" title="查看报告与详情" onClick={() => onSelectPlatform(p)}>
                      <Eye size={14} />
                    </button>
                    <button className="btn btn-secondary btn-icon-only" title="修改配置" onClick={() => onEditPlatform(p)}>
                      <Edit2 size={14} />
                    </button>
                    <button className="btn btn-danger btn-icon-only" title="删除平台" onClick={() => onDeletePlatform(p.name)}>
                      <Trash2 size={14} />
                    </button>
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      )}

      {/* 底部浮动对比栏 */}
      <div className={`compare-bar ${selectedForCompare.length >= 1 ? 'show' : ''}`}>
        <div style={{ color: '#fff', fontSize: '0.875rem' }}>
          已选 <strong style={{ color: 'hsl(var(--color-secondary))' }}>{selectedForCompare.length}</strong> 个平台
        </div>
        <button 
          className="btn btn-secondary" 
          style={{ padding: '0.5rem 1.25rem', borderRadius: '25px', display: 'flex', alignItems: 'center', gap: '0.4rem', whiteSpace: 'nowrap' }}
          onClick={() => {
            onStartTest(selectedForCompare, 'standard');
            setSelectedForCompare([]); // 清空已选
          }}
          disabled={anySelectedRunning}
          title={anySelectedRunning ? "已有选中平台正在探测中" : "对所有选中平台批量运行标准测试"}
        >
          <Play size={14} /> 批量标准探测
        </button>
        <button 
          className="btn btn-secondary" 
          style={{ padding: '0.5rem 1.25rem', borderRadius: '25px', display: 'flex', alignItems: 'center', gap: '0.4rem', whiteSpace: 'nowrap' }}
          onClick={() => {
            onStartTest(selectedForCompare, 'deep');
            setSelectedForCompare([]); // 清空已选
          }}
          disabled={anySelectedRunning}
          title={anySelectedRunning ? "已有选中平台正在探测中" : "对所有选中平台批量运行深度测试"}
        >
          <Play size={14} style={{ color: 'hsl(var(--color-secondary))' }} /> 批量深度探测
        </button>
        <button 
          className="btn btn-primary" 
          style={{ padding: '0.5rem 1.5rem', borderRadius: '25px', display: 'flex', alignItems: 'center', gap: '0.5rem' }}
          onClick={() => {
            onCompare(selectedForCompare);
            setSelectedForCompare([]); // 清空已选
          }}
          disabled={validSelectedCount < 2}
          title={validSelectedCount < 2 ? "进行横向对比至少需要选择 2 个已测试的平台" : "一键生成横向对比报告"}
        >
          <ArrowLeftRight size={14} /> 一键横向对比
        </button>
        <button 
          style={{ background: 'none', border: 'none', color: 'var(--text-dim)', cursor: 'pointer', fontSize: '0.75rem', textDecoration: 'underline' }}
          onClick={() => setSelectedForCompare([])}
        >
          取消选择
        </button>
      </div>
    </div>
  );
}
