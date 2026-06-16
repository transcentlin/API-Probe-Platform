// 修改历史 (Revision History)
// ==================================
// 版本: v1.0.4
// 日期: 2026-06-16
// 修改说明: 重构 loadLatestReport 方法，仅发起 getLatestReportContent 单次请求直接加载最新报告内容，大幅削减 st_size 导致的百度同步盘磁盘 I/O 延迟。
// ----------------------------------
// 版本: v1.0.3
// 日期: 2026-06-16
// 修改说明: 1) listReports 请求传入 platform.name 以支持后端单平台报告过滤优化；2) 分离 Tab 数据拉取逻辑消除重复并发；3) SSE 订阅全局保活消除测试完成时局部 SSE 被提前掐灭导致最新报告未刷新的 Race Condition。
// ----------------------------------
// 版本: v1.0.2
// 日期: 2026-06-16
// 修改说明: 重构布局，将测试控制台移至头部右侧并排放置，使探测报告展示卡片拉伸为 100% 全宽
// ----------------------------------
// 版本: v1.0.1
// 日期: 2026-06-16
// 修改说明: 注入 markdownComponents 自定义 HTML 拦截器以解析 markdown 表格中的 <br> 换行符
// ==================================

import React, { useState, useEffect, useRef } from 'react';
import { ArrowLeft, Play, AlertTriangle, FileText, Download, Trash2, CheckCircle2, XCircle } from 'lucide-react';
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

export default function PlatformPage({ platform, onBack, runningTests, onStartTest }) {
  const [activeTab, setActiveTab] = useState('latest'); // 'latest' | 'history'
  const [reportContent, setReportContent] = useState('');
  const [reportsList, setReportsList] = useState([]);
  const [loadingReport, setLoadingReport] = useState(false);
  const [loadingHistory, setLoadingHistory] = useState(false);
  const [testMode, setTestMode] = useState('standard');
  const [testLog, setTestLog] = useState([]);
  const [currentStage, setCurrentStage] = useState('');
  const [currentProgress, setCurrentProgress] = useState(0);

  // SSE 订阅取消引用的 Ref
  const unsubscribeRef = useRef(null);

  // 1. 获取最新报告内容
  const loadLatestReport = async () => {
    setLoadingReport(true);
    setReportContent('');
    try {
      // 通过单一接口直接拉取最新一份探测报告的原文内容，完美避开多余的 listReports + st_size 开销
      const content = await apiClient.getLatestReportContent(platform.name);
      if (content) {
        setReportContent(content);
      } else {
        setReportContent('_该平台暂无探测报告，请点击上方「启动探测」生成报告。_');
      }
    } catch (err) {
      console.error(err);
      setReportContent('_加载最新报告失败_');
    } finally {
      setLoadingReport(false);
    }
  };

  // 2. 加载历史报告列表
  const loadHistoryList = async () => {
    setLoadingHistory(true);
    try {
      const list = await apiClient.listReports(platform.name);
      setReportsList(list);
    } catch (err) {
      console.error(err);
    } finally {
      setLoadingHistory(false);
    }
  };

  // 按需加载，阻止重复并发请求
  useEffect(() => {
    if (activeTab === 'latest') {
      loadLatestReport();
    } else if (activeTab === 'history') {
      loadHistoryList();
    }
  }, [platform.name, activeTab]);

  // 3. 监听 SSE 事件
  // 在详情页挂载期间始终保持全局 SSE 订阅，不要根据 runningTests 的真假反复断开重建，
  // 从而彻底杜绝在测试完成瞬间因局部订阅被提前掐死导致的报告刷新 Race Condition。
  useEffect(() => {
    // 开启订阅
    unsubscribeRef.current = apiClient.subscribeToEvents(
      (data) => {
        // 只接收本平台的事件
        if (data.platform !== platform.name) return;

        // 计算进度百分比
        let pct = 0;
        const stageName = data.stage || '';
        if (stageName.includes('连通性')) pct = 15;
        else if (stageName.includes('格式')) pct = 35;
        else if (stageName.includes('端点')) pct = 50;
        else if (data.stage_number === 2.5 || stageName.includes('预检') || stageName.includes('2.5')) pct = 65;
        else if (stageName.includes('能力')) pct = 85;
        else if (data.status === 'completed' || data.status === 'success') pct = 100;

        setCurrentStage(stageName || data.status);
        setCurrentProgress(pct);

        // 填充日志
        if (data.message) {
          setTestLog(prev => [...prev, { 
            message: data.message, 
            type: data.status === 'failed' ? 'error' : data.status === 'completed' ? 'success' : 'info'
          }]);
        }

        // 测试如果完成，刷新数据
        if (data.status === 'completed') {
          loadLatestReport();
          loadHistoryList();
        }
      },
      (err) => {
        console.error('SSE Error:', err);
        setTestLog(prev => [...prev, { message: '与服务器的事件流连接断开', type: 'error' }]);
      }
    );

    return () => {
      if (unsubscribeRef.current) {
        unsubscribeRef.current();
        unsubscribeRef.current = null;
      }
    };
  }, [platform.name]);

  const handleStartTest = async () => {
    setTestLog([{ message: `已发送启动指令 (${testMode} 模式)...`, type: 'info' }]);
    setCurrentProgress(5);
    try {
      await onStartTest(platform.name, testMode);
    } catch (err) {
      setTestLog(prev => [...prev, { message: `测试启动失败: ${err.message}`, type: 'error' }]);
      setCurrentProgress(0);
    }
  };

  const handleDeleteReport = async (filename) => {
    if (!window.confirm('您确定要永久删除这份历史报告吗？')) return;
    try {
      await apiClient.deleteReport(filename);
      loadHistoryList();
      // 如果删的是最新的，重新拉取最新报告
      loadLatestReport();
    } catch (err) {
      alert(`删除报告失败: ${err.message}`);
    }
  };

  const isTesting = runningTests[platform.name] || false;

  return (
    <div style={{ maxWidth: '1200px', margin: '0 auto', width: '100%', padding: '2rem' }}>
      {/* 头部面包屑、返回与控制台 */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: '2rem', marginBottom: '2rem', flexWrap: 'wrap' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '1rem' }}>
          <button className="btn btn-secondary btn-icon-only" onClick={onBack}>
            <ArrowLeft size={16} />
          </button>
          <div>
            <span style={{ fontSize: '0.875rem', color: 'var(--text-dim)' }}>API Probe Station &gt;</span>
            <h2 style={{ fontFamily: 'var(--font-title)', fontSize: '1.75rem', fontWeight: 700, margin: 0, lineHeight: 1.2 }}>
              {platform.name}
            </h2>
          </div>
        </div>

        {/* 紧凑的测试控制台 */}
        <div className="glass-card" style={{ display: 'flex', alignItems: 'center', gap: '1rem', padding: '0.5rem 1rem', borderRadius: '12px' }}>
          <span style={{ fontSize: '0.85rem', color: 'var(--text-muted)', fontWeight: 500 }}>探测模式:</span>
          <div style={{ display: 'flex', background: 'rgba(0,0,0,0.2)', padding: '2px', borderRadius: '8px', border: '1px solid rgba(255,255,255,0.05)' }}>
            <button 
              className={`btn`}
              style={{ 
                borderRadius: '6px', 
                padding: '0.25rem 0.75rem', 
                fontSize: '0.75rem', 
                border: 'none', 
                background: testMode === 'standard' ? 'linear-gradient(135deg, hsl(var(--color-primary)) 0%, hsl(var(--color-secondary)) 100%)' : 'transparent',
                boxShadow: testMode === 'standard' ? '0 2px 6px rgba(var(--color-primary-glow))' : 'none',
                color: testMode === 'standard' ? '#fff' : 'hsl(var(--text-muted))',
                fontWeight: 600
              }}
              onClick={() => setTestMode('standard')}
              disabled={isTesting}
            >
              Standard
            </button>
            <button 
              className={`btn`}
              style={{ 
                borderRadius: '6px', 
                padding: '0.25rem 0.75rem', 
                fontSize: '0.75rem', 
                border: 'none', 
                background: testMode === 'deep' ? 'linear-gradient(135deg, hsl(var(--color-primary)) 0%, hsl(var(--color-secondary)) 100%)' : 'transparent',
                boxShadow: testMode === 'deep' ? '0 2px 6px rgba(var(--color-primary-glow))' : 'none',
                color: testMode === 'deep' ? '#fff' : 'hsl(var(--text-muted))',
                fontWeight: 600
              }}
              onClick={() => setTestMode('deep')}
              disabled={isTesting}
              title="包含边界与稳定性并发压测 (耗时较长)"
            >
              Deep
            </button>
          </div>

          <button 
            className="btn btn-primary" 
            style={{ padding: '0.45rem 1rem', fontSize: '0.8rem', gap: '0.35rem', borderRadius: '8px' }}
            onClick={handleStartTest}
            disabled={isTesting}
          >
            <Play size={12} /> {isTesting ? '探测中...' : '启动探测'}
          </button>
        </div>
      </div>

      <div style={{ display: 'flex', flexDirection: 'column', gap: '1.5rem', width: '100%' }}>
        {/* 实时进度与日志区 (测试运行中或有日志时展示) */}
        {(isTesting || testLog.length > 0) && (
          <div className="glass-card" style={{ padding: '1.5rem', display: 'grid', gridTemplateColumns: '1fr 2fr', gap: '1.5rem', alignItems: 'center' }}>
            {/* 左侧：进度信息 */}
            <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
              <div className="flex-between">
                <h4 style={{ fontFamily: 'var(--font-title)', fontSize: '1rem', fontWeight: 600 }}>实时测试进度</h4>
                {isTesting ? (
                  <span style={{ fontSize: '0.75rem', color: 'hsl(var(--color-warning))', display: 'flex', alignItems: 'center', gap: '0.25rem' }}>
                    <span className="status-dot running" /> 正在发包...
                  </span>
                ) : (
                  <span style={{ fontSize: '0.75rem', color: 'hsl(var(--color-success))', display: 'flex', alignItems: 'center', gap: '0.25rem' }}>
                    <CheckCircle2 size={12} /> 已完成
                  </span>
                )}
              </div>

              {/* 进度条 */}
              <div>
                <div className="progress-container">
                  <div className="progress-bar" style={{ width: `${currentProgress}%` }} />
                </div>
                <div className="flex-between" style={{ fontSize: '0.75rem', marginTop: '0.35rem' }}>
                  <span style={{ color: 'var(--text-dim)' }}>阶段: {currentStage || '准备中'}</span>
                  <span>{currentProgress}%</span>
                </div>
              </div>
            </div>

            {/* 右侧：日志输出 */}
            <div style={{ background: 'rgba(0,0,0,0.3)', border: '1px solid rgba(255,255,255,0.05)', borderRadius: '8px', padding: '0.75rem', height: '120px', overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: '0.4rem', fontFamily: 'Consolas, monospace', fontSize: '0.75rem' }}>
              {testLog.map((log, idx) => (
                <div 
                  key={idx} 
                  style={{ 
                    color: log.type === 'error' ? '#fca5a5' : log.type === 'success' ? '#6ee7b7' : 'hsl(var(--text-muted))',
                    wordBreak: 'break-all'
                  }}
                >
                  [{new Date().toLocaleTimeString()}] {log.message}
                </div>
              ))}
            </div>
          </div>
        )}

        {/* 报告展示卡片 (全宽) */}
        <div className="glass-card" style={{ padding: '2rem', minHeight: '500px', width: '100%' }}>
          {/* Tab 导航 */}
          <div style={{ display: 'flex', gap: '1rem', borderBottom: '1px solid rgba(255,255,255,0.08)', paddingBottom: '1rem', marginBottom: '1.5rem' }}>
            <button 
              className={`btn ${activeTab === 'latest' ? 'btn-primary' : 'btn-secondary'}`}
              style={{ borderRadius: '20px', padding: '0.4rem 1.25rem', fontSize: '0.8rem' }}
              onClick={() => setActiveTab('latest')}
            >
              最新探测报告
            </button>
            <button 
              className={`btn ${activeTab === 'history' ? 'btn-primary' : 'btn-secondary'}`}
              style={{ borderRadius: '20px', padding: '0.4rem 1.25rem', fontSize: '0.8rem' }}
              onClick={() => setActiveTab('history')}
            >
              历史报告发现
            </button>
          </div>

          {activeTab === 'latest' ? (
            <div className="report-view">
              {loadingReport ? (
                <div style={{ color: 'var(--text-dim)', textAlign: 'center', padding: '5rem 0' }}>正在从磁盘加载报告...</div>
              ) : (
                <ReactMarkdown remarkPlugins={[remarkGfm]} components={markdownComponents}>
                  {reportContent}
                </ReactMarkdown>
              )}
            </div>
          ) : (
            <div>
              {loadingHistory ? (
                <div style={{ color: 'var(--text-dim)', textAlign: 'center', padding: '3rem 0' }}>正在加载历史列表...</div>
              ) : reportsList.length === 0 ? (
                <div style={{ color: 'var(--text-dim)', textAlign: 'center', padding: '3rem 0', fontStyle: 'italic' }}>暂无任何历史报告。</div>
              ) : (
                <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.875rem' }}>
                  <thead>
                    <tr style={{ borderBottom: '1px solid rgba(255,255,255,0.08)', color: '#fff', textAlign: 'left' }}>
                      <th style={{ padding: '0.75rem' }}>报告文件名</th>
                      <th style={{ padding: '0.75rem' }}>生成时间</th>
                      <th style={{ padding: '0.75rem' }}>文件大小</th>
                      <th style={{ padding: '0.75rem', textAlign: 'right' }}>操作</th>
                    </tr>
                  </thead>
                  <tbody>
                    {reportsList.map(r => (
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
                          <a 
                            className="btn btn-secondary btn-icon-only" 
                            href={`/api/reports/${r.filename}`} 
                            download
                            title="下载原始 Markdown 文件"
                            style={{ marginRight: '0.5rem' }}
                          >
                            <Download size={12} />
                          </a>
                          <button 
                            className="btn btn-danger btn-icon-only"
                            onClick={() => handleDeleteReport(r.filename)}
                            title="物理删除报告"
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
    </div>
  );
}
