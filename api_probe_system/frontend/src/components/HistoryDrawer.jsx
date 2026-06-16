// 修改历史 (Revision History)
// ==================================
// 版本: v1.0.0
// 日期: 2026-06-16
// 修改说明: 创建探测历史抽屉组件，支持 3s 定时轮询、日志记录项渲染、卡片折叠与一键清除，并内嵌 ReactMarkdown 的报告预览 Modal。
// ==================================

import React, { useState, useEffect } from 'react';
import { X, History, Trash2, CheckCircle2, XCircle, Loader2, FileText, ArrowLeft } from 'lucide-react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { apiClient } from '../api/client';

const markdownComponents = {
  td({ children, ...props }) {
    if (!children) return <td {...props}>{children}</td>;
    const arrayChildren = React.Children.toArray(children);
    const result = [];
    arrayChildren.forEach((child, i) => {
      if (typeof child === 'string') {
        const parts = child.split(/<br\s*\/?>/gi);
        parts.forEach((part, index) => {
          if (part) result.push(part);
          if (index < parts.length - 1) result.push(<br key={`br-${i}-${index}`} />);
        });
      } else {
        result.push(child);
      }
    });
    return <td {...props}>{result}</td>;
  },
  th({ children, ...props }) {
    if (!children) return <th {...props}>{children}</th>;
    const arrayChildren = React.Children.toArray(children);
    const result = [];
    arrayChildren.forEach((child, i) => {
      if (typeof child === 'string') {
        const parts = child.split(/<br\s*\/?>/gi);
        parts.forEach((part, index) => {
          if (part) result.push(part);
          if (index < parts.length - 1) result.push(<br key={`br-${i}-${index}`} />);
        });
      } else {
        result.push(child);
      }
    });
    return <th {...props}>{result}</th>;
  }
};

export default function HistoryDrawer({ isOpen, onClose }) {
  const [history, setHistory] = useState([]);
  const [loading, setLoading] = useState(false);
  const [previewFilename, setPreviewFilename] = useState(null);
  const [previewContent, setPreviewContent] = useState('');
  const [previewLoading, setPreviewLoading] = useState(false);

  // 获取历史日志
  const fetchHistory = async (showLoading = false) => {
    if (showLoading) setLoading(true);
    try {
      const data = await apiClient.getTestHistory();
      setHistory(data);
    } catch (err) {
      console.error('拉取探测日志失败', err);
    } finally {
      if (showLoading) setLoading(false);
    }
  };

  // 轮询与开启刷新
  useEffect(() => {
    if (isOpen) {
      fetchHistory(true);
      // 开启 3 秒的定时器，实时查看运行状态变化
      const timer = setInterval(() => {
        fetchHistory(false);
      }, 3000);
      return () => clearInterval(timer);
    }
  }, [isOpen]);

  // 清空历史日志
  const handleClear = async () => {
    if (!window.confirm('您确定要清空所有探测历史日志吗？\n警告：此操作不可恢复！')) return;
    try {
      await apiClient.clearTestHistory();
      setHistory([]);
    } catch (err) {
      alert(`清空日志失败: ${err.message}`);
    }
  };

  // 预览报告
  const handlePreview = async (filename) => {
    setPreviewFilename(filename);
    setPreviewLoading(true);
    setPreviewContent('');
    try {
      const content = await apiClient.getReportContent(filename);
      setPreviewContent(content);
    } catch (err) {
      setPreviewContent(`### 加载报告失败\n无法获取文件 \`${filename}\` 的内容。\n错误信息: ${err.message}`);
    } finally {
      setPreviewLoading(false);
    }
  };

  if (!isOpen) return null;

  return (
    <div className="drawer-overlay" onClick={onClose}>
      <div 
        className="drawer-content" 
        onClick={e => e.stopPropagation()} 
        style={{ width: '580px', borderLeft: '1px solid rgba(255, 255, 255, 0.1)' }}
      >
        {/* 头部 */}
        <div className="drawer-header">
          <div className="flex-align" style={{ gap: '0.6rem' }}>
            <History className="text-primary" size={20} style={{ color: '#3b82f6' }} />
            <h2 style={{ fontSize: '1.25rem', fontWeight: 700, margin: 0, fontFamily: 'var(--font-title)', color: 'var(--text-bright)' }}>
              探测历史日志
            </h2>
          </div>
          <div className="flex-align" style={{ gap: '0.8rem' }}>
            {history.length > 0 && (
              <button 
                className="btn btn-secondary btn-icon-only" 
                title="清空所有日志" 
                onClick={handleClear}
                style={{ border: '1px solid rgba(239, 68, 68, 0.2)', background: 'rgba(239, 68, 68, 0.05)', display: 'flex', alignItems: 'center', justifyContent: 'center', padding: '0.4rem' }}
              >
                <Trash2 size={14} style={{ color: '#ef4444' }} />
              </button>
            )}
            <button className="btn-close" onClick={onClose} style={{ background: 'none', border: 'none', color: 'var(--text-dim)', cursor: 'pointer' }}>
              <X size={20} />
            </button>
          </div>
        </div>

        {/* 抽屉主体 */}
        <div className="drawer-body" style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
          {loading && history.length === 0 ? (
            <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', height: '100%', color: 'var(--text-muted)' }}>
              <Loader2 className="animate-spin" size={32} />
              <span style={{ marginLeft: '0.5rem' }}>加载日志中...</span>
            </div>
          ) : history.length === 0 ? (
            <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', height: '100%', color: 'var(--text-muted)', textAlign: 'center', padding: '3rem 1.5rem' }}>
              <History size={48} style={{ marginBottom: '1rem', opacity: 0.2 }} />
              <p style={{ fontSize: '1rem', fontWeight: 600, color: 'var(--text-bright)' }}>暂无探测历史</p>
              <p style={{ fontSize: '0.8rem', opacity: 0.8 }}>点击主页的“探测”或“批量探测”按钮即可开始记录任务。</p>
            </div>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
              {history.map((item) => {
                const isRunning = item.status === 'running';
                const isSuccess = item.status === 'success';
                const isFailed = item.status === 'failed';

                return (
                  <div 
                    key={item.task_id} 
                    className="history-card"
                    style={{
                      background: 'rgba(255, 255, 255, 0.02)',
                      border: isRunning 
                        ? '1px solid rgba(59, 130, 246, 0.25)' 
                        : isSuccess 
                          ? '1px solid rgba(16, 185, 129, 0.15)' 
                          : '1px solid rgba(239, 68, 68, 0.2)',
                      borderRadius: '8px',
                      padding: '1rem',
                      transition: 'all 0.25s ease',
                      position: 'relative',
                      overflow: 'hidden'
                    }}
                  >
                    {/* 左侧装饰性高亮条 */}
                    <div 
                      style={{
                        position: 'absolute',
                        left: 0,
                        top: 0,
                        bottom: 0,
                        width: '4px',
                        background: isRunning 
                          ? '#3b82f6' 
                          : isSuccess 
                            ? '#10b981' 
                            : '#ef4444'
                      }}
                    />

                    <div className="flex-between" style={{ marginBottom: '0.5rem', paddingLeft: '4px' }}>
                      <div className="flex-align" style={{ gap: '0.5rem' }}>
                        <span style={{ fontWeight: 700, fontSize: '0.95rem', color: 'var(--text-bright)' }}>
                          {item.platform_name}
                        </span>
                        <span 
                          style={{
                            fontSize: '0.65rem',
                            padding: '0.1rem 0.4rem',
                            borderRadius: '10px',
                            background: 'rgba(255, 255, 255, 0.06)',
                            color: 'var(--text-dim)',
                            border: '1px solid rgba(255, 255, 255, 0.1)'
                          }}
                        >
                          {item.mode === 'deep' ? '深度探测' : '标准探测'}
                        </span>
                      </div>
                      
                      {/* 状态芯片 */}
                      <div className="flex-align">
                        {isRunning && (
                          <span className="flex-align" style={{ gap: '0.25rem', color: '#60a5fa', fontSize: '0.75rem', fontWeight: 600, background: 'rgba(59, 130, 246, 0.1)', padding: '0.15rem 0.5rem', borderRadius: '4px', border: '1px solid rgba(59, 130, 246, 0.2)' }}>
                            <Loader2 size={12} className="animate-spin" />
                            运行中
                          </span>
                        )}
                        {isSuccess && (
                          <span className="flex-align" style={{ gap: '0.25rem', color: '#34d399', fontSize: '0.75rem', fontWeight: 600, background: 'rgba(16, 185, 129, 0.1)', padding: '0.15rem 0.5rem', borderRadius: '4px', border: '1px solid rgba(16, 185, 129, 0.2)' }}>
                            <CheckCircle2 size={12} />
                            成功 {item.score !== null && item.score !== undefined ? `(${item.score}分)` : ''}
                          </span>
                        )}
                        {isFailed && (
                          <span className="flex-align" style={{ gap: '0.25rem', color: '#f87171', fontSize: '0.75rem', fontWeight: 600, background: 'rgba(239, 68, 68, 0.1)', padding: '0.15rem 0.5rem', borderRadius: '4px', border: '1px solid rgba(239, 68, 68, 0.2)' }}>
                            <XCircle size={12} />
                            失败
                          </span>
                        )}
                      </div>
                    </div>

                    {/* 卡片详情 */}
                    <div style={{ paddingLeft: '4px', display: 'flex', flexDirection: 'column', gap: '0.4rem', fontSize: '0.8rem' }}>
                      <div style={{ color: 'var(--text-dim)', fontSize: '0.75rem' }}>
                        <span>时间: {item.start_time}</span>
                        {item.end_time && <span> ~ {item.end_time.split(' ')[1]}</span>}
                      </div>

                      <div 
                        style={{ 
                          color: isFailed ? '#fca5a5' : 'var(--text-dim)', 
                          wordBreak: 'break-all', 
                          background: isFailed ? 'rgba(239, 68, 68, 0.05)' : 'none',
                          padding: isFailed ? '0.4rem 0.6rem' : '0',
                          border: isFailed ? '1px solid rgba(239, 68, 68, 0.1)' : 'none',
                          borderRadius: isFailed ? '4px' : '0',
                          fontFamily: isFailed ? 'monospace' : 'inherit',
                          fontSize: isFailed ? '0.75rem' : '0.8rem'
                        }}
                      >
                        {item.message}
                      </div>

                      {/* 探测后的报告预览 */}
                      {item.report_filename && (
                        <div style={{ marginTop: '0.4rem', display: 'flex', justifyContent: 'flex-end' }}>
                          <button 
                            className="btn btn-secondary flex-align"
                            style={{ 
                              padding: '0.25rem 0.6rem', 
                              fontSize: '0.75rem', 
                              gap: '0.3rem',
                              border: '1px solid rgba(255, 255, 255, 0.12)',
                              borderRadius: '4px'
                            }}
                            onClick={() => handlePreview(item.report_filename)}
                          >
                            <FileText size={12} />
                            预览报告
                          </button>
                        </div>
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>

        {/* 二级 Preview Modal */}
        {previewFilename && (
          <div 
            className="modal-overlay" 
            style={{ 
              position: 'fixed', 
              top: 0, 
              left: 0, 
              right: 0, 
              bottom: 0, 
              background: 'rgba(0,0,0,0.8)', 
              backdropFilter: 'blur(8px)', 
              zIndex: 1100, 
              display: 'flex', 
              justifyContent: 'center', 
              alignItems: 'center' 
            }}
            onClick={() => setPreviewFilename(null)}
          >
            <div 
              className="modal-content" 
              style={{ 
                width: '900px', 
                maxWidth: '90%', 
                height: '85vh', 
                background: 'rgba(10, 16, 28, 0.95)', 
                border: '1px solid rgba(255, 255, 255, 0.12)', 
                borderRadius: '12px',
                display: 'flex',
                flexDirection: 'column',
                boxShadow: '0 20px 50px rgba(0, 0, 0, 0.6)'
              }}
              onClick={e => e.stopPropagation()}
            >
              {/* 预览头部 */}
              <div 
                className="flex-between" 
                style={{ 
                  padding: '1.2rem 1.5rem', 
                  borderBottom: '1px solid rgba(255, 255, 255, 0.08)' 
                }}
              >
                <div className="flex-align" style={{ gap: '0.5rem' }}>
                  <button 
                    style={{ background: 'none', border: 'none', color: 'var(--text-bright)', cursor: 'pointer', display: 'flex', alignItems: 'center', gap: '0.4rem', padding: '0.2rem' }}
                    onClick={() => setPreviewFilename(null)}
                  >
                    <ArrowLeft size={16} />
                    <span>返回日志列表</span>
                  </button>
                  <span style={{ color: 'var(--text-muted)' }}>|</span>
                  <span style={{ fontWeight: 600, color: 'var(--text-muted)', fontSize: '0.9rem' }}>
                    {previewFilename}
                  </span>
                </div>
                <button 
                  className="btn-close" 
                  onClick={() => setPreviewFilename(null)}
                  style={{ background: 'none', border: 'none', color: 'var(--text-dim)', cursor: 'pointer' }}
                >
                  <X size={20} />
                </button>
              </div>

              {/* 预览主体 */}
              <div 
                className="report-view"
                style={{ 
                  flex: 1, 
                  padding: '1.5rem', 
                  overflowY: 'auto', 
                  background: 'rgba(0, 0, 0, 0.2)' 
                }}
              >
                {previewLoading ? (
                  <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', height: '100%', color: 'var(--text-muted)' }}>
                    <Loader2 className="animate-spin" size={32} />
                    <span style={{ marginLeft: '0.5rem' }}>加载报告内容中...</span>
                  </div>
                ) : (
                  <div className="markdown-body text-left">
                    <ReactMarkdown remarkPlugins={[remarkGfm]} components={markdownComponents}>
                      {previewContent}
                    </ReactMarkdown>
                  </div>
                )}
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
