// 修改历史 (Revision History)
// ==================================
// 版本: v1.0.3
// 日期: 2026-06-16
// 修改说明: 重构 ComparePage 为经典双子页标签模式，实现“最新对比报告”和“历史对比报告发现”两个子页。支持勾选平台自动生成与导航常驻按钮无平台进入时自动读取最新物理报告，并在历史表格中打通预览、下载与物理删除的闭环交互。
// ----------------------------------
// 版本: v1.0.2
// 日期: 2026-06-16
// 修改说明: 重构多平台横向对比界面为左右双栏布局，左侧 (75%) 预览 Markdown 报告，右侧 (25%) 展示历史对比报告列表，支持预览、下载、物理删除报告。
// ----------------------------------
// 版本: v1.0.1
// 日期: 2026-06-16
// 修改说明: 注入 markdownComponents 自定义 HTML 拦截器以解析 markdown 表格中的 <br> 换行符
// ==================================

import React, { useState, useEffect } from 'react';
import { ArrowLeft, RefreshCw, FileText, CheckCircle2, ShieldAlert, Download, Trash2, Eye, Calendar, HardDrive } from 'lucide-react';
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

export default function ComparePage({ platforms, onBack }) {
  const [activeTab, setActiveTab] = useState('latest'); // 'latest' | 'history'
  const [reportContent, setReportContent] = useState('');
  const [currentReportName, setCurrentReportName] = useState('');
  const [loading, setLoading] = useState(false); // 生成或读取最新报告的加载状态
  const [error, setError] = useState('');
  const [historyList, setHistoryList] = useState([]);
  const [historyLoading, setHistoryLoading] = useState(false);

  // 加载历史列表
  const loadHistoryList = async () => {
    setHistoryLoading(true);
    try {
      const data = await apiClient.listReports("横向对比");
      setHistoryList(data);
    } catch (err) {
      console.error('加载对比历史报告失败:', err);
    } finally {
      setHistoryLoading(false);
    }
  };

  // 生成最新或者读取历史最新
  const loadLatestOrCreate = async () => {
    setLoading(true);
    setError('');
    setReportContent('');
    setCurrentReportName('');
    try {
      if (platforms && platforms.length > 0) {
        // 路径 A：主页勾选了平台，发起新生成
        const res = await apiClient.generateComparison(platforms);
        const content = await apiClient.getReportContent(res.filename);
        setReportContent(content);
        setCurrentReportName(res.filename);
      } else {
        // 路径 B：无平台参数传入（如顶栏直达），加载历史中最近的一份报告
        const history = await apiClient.listReports("横向对比");
        if (history && history.length > 0) {
          const latestFile = history[0].filename;
          const content = await apiClient.getReportContent(latestFile);
          setReportContent(content);
          setCurrentReportName(latestFile);
        } else {
          setReportContent('_暂无历史横向对比报告。请先返回主页选择 API 平台发起横向选型对比。_');
        }
      }
    } catch (err) {
      console.error(err);
      setError(err.message || '加载横向对比报告失败，请确保各平台均已有单平台测试报告。');
    } finally {
      setLoading(false);
    }
  };

  // 监听 platforms 参数变动：变动时自动重置 Tab 为 latest 并生成或加载最新
  useEffect(() => {
    setActiveTab('latest');
    loadLatestOrCreate();
  }, [platforms]);

  // 监听 Tab 变动
  useEffect(() => {
    if (activeTab === 'history') {
      loadHistoryList();
    }
  }, [activeTab]);

  // 查看预览历史某份报告
  const handlePreview = async (filename) => {
    setLoading(true);
    setActiveTab('latest');
    setError('');
    try {
      const content = await apiClient.getReportContent(filename);
      setReportContent(content);
      setCurrentReportName(filename);
    } catch (err) {
      console.error(err);
      setError('加载该份历史报告失败: ' + err.message);
    } finally {
      setLoading(false);
    }
  };

  // 文件下载
  const handleDownload = async (filename) => {
    try {
      const content = await apiClient.getReportContent(filename);
      const blob = new Blob([content], { type: 'text/markdown;charset=utf-8;' });
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.setAttribute('download', filename);
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      URL.revokeObjectURL(url);
    } catch (err) {
      console.error(err);
      alert('物理下载报告失败：' + err.message);
    }
  };

  // 文件物理删除
  const handleDelete = async (filename) => {
    if (window.confirm(`确认永久删除此横向对比报告吗？\n文件 [ ${filename} ] 将从磁盘被物理删除！`)) {
      try {
        await apiClient.deleteReport(filename);
        if (currentReportName === filename) {
          setReportContent('');
          setCurrentReportName('');
        }
        await loadHistoryList();
      } catch (err) {
        console.error(err);
        alert('删除报告失败：' + err.message);
      }
    }
  };

  return (
    <div style={{ maxWidth: '1200px', margin: '0 auto', width: '100%', padding: '2rem' }}>
      {/* 头部导航与标题 */}
      <div style={{ display: 'flex', alignItems: 'center', gap: '1rem', marginBottom: '2rem' }}>
        <button className="btn btn-secondary btn-icon-only" onClick={onBack}>
          <ArrowLeft size={16} />
        </button>
        <div>
          <span style={{ fontSize: '0.875rem', color: 'var(--text-dim)' }}>API Probe Station &gt;</span>
          <h2 style={{ fontFamily: 'var(--font-title)', fontSize: '1.75rem', fontWeight: 700 }}>
            多平台横向对比分析
          </h2>
        </div>
      </div>

      {/* 主面板 */}
      <div className="glass-card" style={{ padding: '2rem', minHeight: '550px', width: '100%' }}>
        {/* Tab 导航切换 */}
        <div style={{ display: 'flex', gap: '1rem', borderBottom: '1px solid rgba(255,255,255,0.08)', paddingBottom: '1rem', marginBottom: '1.5rem' }}>
          <button 
            className={`btn ${activeTab === 'latest' ? 'btn-primary' : 'btn-secondary'}`}
            style={{ borderRadius: '20px', padding: '0.4rem 1.25rem', fontSize: '0.8rem' }}
            onClick={() => setActiveTab('latest')}
          >
            最新对比报告
          </button>
          <button 
            className={`btn ${activeTab === 'history' ? 'btn-primary' : 'btn-secondary'}`}
            style={{ borderRadius: '20px', padding: '0.4rem 1.25rem', fontSize: '0.8rem' }}
            onClick={() => setActiveTab('history')}
          >
            历史报告发现
          </button>
        </div>

        {/* 子标签页内容区 */}
        {activeTab === 'latest' ? (
          <div className="report-view">
            {loading ? (
              <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', padding: '6rem 0', color: 'var(--text-muted)' }}>
                <RefreshCw size={40} className="brand-icon" style={{ marginBottom: '1.5rem', animation: 'rotateGlow 2s linear infinite' }} />
                <p style={{ fontSize: '1.1rem', fontWeight: 500, marginBottom: '0.5rem' }}>正在加载多平台对比报告数据...</p>
                <p style={{ fontSize: '0.875rem', color: 'var(--text-dim)' }}>计算多维评分矩阵并呈递横向选型推荐</p>
              </div>
            ) : error ? (
              <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', padding: '5rem 0', color: '#fca5a5', textAlign: 'center' }}>
                <ShieldAlert size={48} style={{ marginBottom: '1.5rem', color: 'hsl(var(--color-danger))' }} />
                <p style={{ fontSize: '1.1rem', fontWeight: 600, marginBottom: '1rem' }}>{error}</p>
                {platforms && platforms.length > 0 && (
                  <button className="btn btn-primary" onClick={loadLatestOrCreate}>
                    重新尝试生成
                  </button>
                )}
              </div>
            ) : (
              <>
                {/* 顶栏报告名称及下载快捷方式 */}
                {currentReportName && (
                  <div style={{ 
                    display: 'flex', 
                    justifyContent: 'space-between', 
                    alignItems: 'center', 
                    borderBottom: '1px solid rgba(255,255,255,0.05)', 
                    paddingBottom: '0.75rem', 
                    marginBottom: '1.5rem' 
                  }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', color: 'hsl(var(--color-primary))' }}>
                      <FileText size={15} />
                      <span style={{ fontSize: '0.875rem', fontWeight: 600 }}>{currentReportName}</span>
                    </div>
                    <button 
                      className="btn btn-secondary" 
                      style={{ padding: '4px 10px', fontSize: '0.75rem' }} 
                      onClick={() => handleDownload(currentReportName)}
                    >
                      <Download size={12} />
                      下载此 Markdown 文件
                    </button>
                  </div>
                )}
                
                <ReactMarkdown remarkPlugins={[remarkGfm]} components={markdownComponents}>
                  {reportContent}
                </ReactMarkdown>
              </>
            )}
          </div>
        ) : (
          <div>
            {historyLoading ? (
              <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', padding: '5rem 0' }}>
                <RefreshCw size={30} className="animate-spin" style={{ color: 'var(--text-dim)' }} />
              </div>
            ) : historyList.length === 0 ? (
              <div style={{ textAlign: 'center', color: 'var(--text-dim)', padding: '5rem 0', fontStyle: 'italic' }}>
                暂无任何历史横向对比报告。
              </div>
            ) : (
              <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.875rem' }}>
                <thead>
                  <tr style={{ borderBottom: '1px solid rgba(255,255,255,0.08)', color: '#fff', textAlign: 'left' }}>
                    <th style={{ padding: '0.75rem' }}>对比报告文件名</th>
                    <th style={{ padding: '0.75rem' }}>生成时间</th>
                    <th style={{ padding: '0.75rem' }}>文件大小</th>
                    <th style={{ padding: '0.75rem', textAlign: 'right' }}>操作</th>
                  </tr>
                </thead>
                <tbody>
                  {historyList.map(r => (
                    <tr key={r.filename} style={{ borderBottom: '1px solid rgba(255,255,255,0.03)' }}>
                      <td style={{ padding: '0.75rem' }}>
                        <span style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                          <FileText size={14} color="var(--text-dim)" />
                          <code>{r.filename}</code>
                        </span>
                      </td>
                      <td style={{ padding: '0.75rem', color: 'hsl(var(--text-muted))' }}>{r.created_at}</td>
                      <td style={{ padding: '0.75rem', color: 'hsl(var(--text-dim))' }}>{(r.size_bytes / 1024).toFixed(1)} KB</td>
                      <td style={{ padding: '0.75rem', textAlign: 'right' }}>
                        <button 
                          className="btn btn-secondary btn-icon-only" 
                          onClick={() => handlePreview(r.filename)}
                          title="在线预览此对比报告"
                          style={{ marginRight: '0.5rem', width: '28px', height: '28px', padding: 0, display: 'inline-flex', justifyContent: 'center', alignItems: 'center' }}
                        >
                          <Eye size={12} />
                        </button>
                        <button 
                          className="btn btn-secondary btn-icon-only" 
                          onClick={() => handleDownload(r.filename)}
                          title="下载原始 Markdown 文件"
                          style={{ marginRight: '0.5rem', width: '28px', height: '28px', padding: 0, display: 'inline-flex', justifyContent: 'center', alignItems: 'center' }}
                        >
                          <Download size={12} />
                        </button>
                        <button 
                          className="btn btn-danger btn-icon-only"
                          onClick={() => handleDelete(r.filename)}
                          title="从磁盘物理删除报告"
                          style={{ width: '28px', height: '28px', padding: 0, display: 'inline-flex', justifyContent: 'center', alignItems: 'center' }}
                        >
                          <Trash2 size={12} />
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
