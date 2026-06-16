// 修改历史 (Revision History)
// ==================================
// 版本: v1.2.3
// 日期: 2026-06-16
// 修改说明: 优化顶栏“横向对比”按钮，将其重构为纯图标按钮（FileText），隐藏文字，鼠标悬停时显示 tooltip“横向对比报告”，实现与顶栏其他操作组件视觉风格完全一致。
// ----------------------------------
// 版本: v1.2.2
// 日期: 2026-06-16
// 修改说明: 在顶部导航栏加入“横向对比”快捷进入按钮（GitCompare），支持清空勾选列表后无缝进入对比页查看历史报告。
// ----------------------------------
// 版本: v1.2.1
// 日期: 2026-06-16
// 修改说明: 移除 fetchPlatforms 方法中人为设置 of 1.5 秒硬编码加载延时，大幅提升首屏及刷新时的响应敏捷度。
// ----------------------------------
// 版本: v1.2.0
// 日期: 2026-06-16
// 修改说明: 在页面顶栏引入“探测日志”按钮及 HistoryDrawer 抽屉，支持测试历史的查阅、轮询监听与 Markdown 报告在线预览。
// ----------------------------------
// 版本: v1.1.5
// 日期: 2026-06-16
// 修改说明: 重构 handleStartTest 为支持接收单个平台（String）或多个平台名称数组（Array）的通用异步测试启动逻辑，并在 HomePage 组件渲染处增加 onStartTest 属性绑定。
// ----------------------------------
// 版本: v1.1.4
// 日期: 2026-06-16
// 修改说明: 实现 handleTogglePlatform 处理程序并将其作为 onToggleEnable 传递给 HomePage，支持平台卡片上的启用/禁用开关切换。
// ----------------------------------
// 版本: v1.1.3
// 日期: 2026-06-16
// 修改说明: 放大雷达过渡动画至 360px，增加中心图标 and 探测节点数量，并将加载文本更新为“API 平台深度探测中...”。
// ----------------------------------
// 版本: v1.1.2
// 日期: 2026-06-16
// 修改说明: 替换简陋的加载圈圈，设计并实现酷炫的雷达探测扫描过渡动画，贴合 API 探测平台的主题特色。
// ----------------------------------
// 版本: v1.1.1
// 日期: 2026-06-16
// 修改说明: 在 fetchPlatforms 逻辑中引入 1.5 秒的自适应时间延时锁，以提供首屏 and 刷新的过渡仪式感体验。
// ----------------------------------
// 版本: v1.1.0
// 日期: 2026-06-16
// 修改说明: 挂载前端打包静态资产目录，并配置 SPA Catchall Fallback 逻辑以支持客户端路由无缝刷新。
// ==================================

import React, { useState, useEffect } from 'react';
import { Compass, RefreshCw, AlertTriangle, Shield, History, GitCompare, FileText } from 'lucide-react';
import { apiClient } from './api/client';
import HomePage from './pages/HomePage';
import PlatformPage from './pages/PlatformPage';
import ComparePage from './pages/ComparePage';
import PlatformModal from './components/PlatformModal';
import WarningDrawer from './components/WarningDrawer';
import HistoryDrawer from './components/HistoryDrawer';

const flexGapStyle = { gap: '1rem' };
const backBtnStyle = { padding: '0.4rem 1rem', fontSize: '0.8rem' };

export default function App() {
  const [platforms, setPlatforms] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  
  const [warnings, setWarnings] = useState([]);
  const [warningDrawerOpen, setWarningDrawerOpen] = useState(false);
  const [historyDrawerOpen, setHistoryDrawerOpen] = useState(false);
  
  // 导航视图控制: 'home' | 'platform' | 'compare'
  const [activeView, setActiveView] = useState('home');
  const [selectedPlatform, setSelectedPlatform] = useState(null);
  const [comparePlatforms, setComparePlatforms] = useState([]);
  
  // 平台运行测试的状态映射: { [platform_name]: isRunning }
  const [runningTests, setRunningTests] = useState({});

  // 平台弹窗控制
  const [modalOpen, setModalOpen] = useState(false);
  const [editingPlatform, setEditingPlatform] = useState(null);

  // 获取告警列表
  const fetchWarnings = async () => {
    try {
      const data = await apiClient.getCompatibilityWarnings();
      setWarnings(data);
    } catch (err) {
      console.error('获取兼容性告警失败', err);
    }
  };

  // 1. 获取所有平台列表
  const fetchPlatforms = async (showLoading = true) => {
    if (showLoading) setLoading(true);
    try {
      const data = await apiClient.getPlatforms();
      setPlatforms(data);
      setError('');
      fetchWarnings();
    } catch (err) {
      console.error(err);
      setError('无法连接后端 API 服务，请确认后端服务已在 8080 端口正常启动。');
    } finally {
      if (showLoading) setLoading(false);
    }
  };

  // 2. 初始化加载及全局 SSE 订阅
  useEffect(() => {
    fetchPlatforms();

    // 订阅全局 SSE 事件流
    const unsubscribe = apiClient.subscribeToEvents(
      (data) => {
        // SSE 推送的格式为 { platform: 'X', stage: 'Y', status: 'running' | 'completed' | 'failed' | 'success', message: '...' }
        const pName = data.platform;
        const status = data.status;

        if (status === 'started' || status === 'running') {
          setRunningTests(prev => ({ ...prev, [pName]: true }));
        } else if (status === 'completed' || status === 'success' || status === 'failed') {
          setRunningTests(prev => ({ ...prev, [pName]: false }));
          // 静默刷新列表以同步评分和首选推荐模型
          fetchPlatforms(false);
        }
      },
      (err) => {
        console.warn('全局事件流连接断开，正在尝试重连...', err);
      }
    );

    return () => {
      if (unsubscribe) unsubscribe();
    };
  }, []);

  // 3. 平台 CRUD 处理器
  const handleAddPlatform = () => {
    setEditingPlatform(null);
    setModalOpen(true);
  };

  const handleEditPlatform = (platform) => {
    setEditingPlatform(platform);
    setModalOpen(true);
  };

  const handleDeletePlatform = async (name) => {
    if (!window.confirm(`您确定要永久物理删除平台 ${name} 吗？\n警告：这会同时清空加密注册表中的配置！`)) return;
    try {
      await apiClient.deletePlatform(name);
      fetchPlatforms(false);
    } catch (err) {
      alert(`删除失败: ${err.message}`);
    }
  };

  const handleSavePlatform = async (payload, isEdit) => {
    if (isEdit) {
      await apiClient.updatePlatform(editingPlatform.name, payload);
    } else {
      await apiClient.createPlatform(payload);
    }
    setModalOpen(false);
    fetchPlatforms(false);
  };

  const handleTogglePlatform = async (name, enabled) => {
    try {
      await apiClient.togglePlatform(name, enabled);
      fetchPlatforms(false);
    } catch (err) {
      alert(`切换平台状态失败: ${err.message}`);
    }
  };

  // 4. 触发异步测试（支持单个与批量触发）
  const handleStartTest = async (names, mode) => {
    const nameList = Array.isArray(names) ? names : [names];
    setRunningTests(prev => {
      const next = { ...prev };
      nameList.forEach(n => {
        next[n] = true;
      });
      return next;
    });
    try {
      await apiClient.startTest(nameList, mode);
    } catch (err) {
      setRunningTests(prev => {
        const next = { ...prev };
        nameList.forEach(n => {
          next[n] = false;
        });
        return next;
      });
      throw err;
    }
  };

  // 5. 触发横向对比
  const handleCompare = (selectedNames) => {
    setComparePlatforms(selectedNames);
    setActiveView('compare');
  };

  return (
    <div className="app-container">
      {/* 顶栏 */}
      <header className="nav-bar">
        <a href="/" className="brand" onClick={(e) => { e.preventDefault(); setActiveView('home'); }}>
          <Compass className="brand-icon" size={24} />
          <span className="brand-name">API Probe Station</span>
        </a>
        
        <div className="flex-align" style={flexGapStyle}>
          {activeView !== 'home' && (
            <button className="btn btn-secondary" style={backBtnStyle} onClick={() => setActiveView('home')}>
              返回主页
            </button>
          )}

          <button 
            className="btn btn-secondary btn-icon-only" 
            title="横向对比报告" 
            onClick={() => {
              setComparePlatforms([]);
              setActiveView('compare');
            }}
          >
            <FileText size={14} />
          </button>
          
          {/* 兼容性警告按钮 */}
          <button 
            className={`warning-pulse-btn ${warnings.length > 0 ? 'active' : ''}`}
            title={warnings.length > 0 ? `有 ${warnings.length} 个平台发现异常` : "查看平台兼容性告警 (无告警)"}
            onClick={() => setWarningDrawerOpen(true)}
          >
            {warnings.length > 0 ? (
              <AlertTriangle size={16} />
            ) : (
              <Shield size={16} />
            )}
            {warnings.length > 0 && (
              <span className="warning-badge-count">{warnings.length}</span>
            )}
          </button>

          {/* 探测历史日志按钮 */}
          <button 
            className="btn btn-secondary btn-icon-only" 
            title="查看探测历史日志" 
            onClick={() => setHistoryDrawerOpen(true)}
          >
            <History size={14} />
          </button>

          <button className="btn btn-secondary btn-icon-only" title="刷新列表" onClick={() => fetchPlatforms()} disabled={loading}>
            <RefreshCw size={14} className={loading ? 'brand-icon' : ''} style={{ animation: loading ? 'rotateGlow 1.5s linear infinite' : 'none' }} />
          </button>
        </div>
      </header>

      {/* 错误提示栏 */}
      {error && (
        <div style={{ background: 'rgba(239, 68, 68, 0.15)', borderBottom: '1px solid rgba(239, 68, 68, 0.3)', padding: '0.75rem 2rem', color: '#fca5a5', fontSize: '0.875rem', textAlign: 'center' }}>
          {error}
        </div>
      )}

      {/* 核心内容区 */}
      <main style={{ flex: 1, display: 'flex', flexDirection: 'column' }}>
        {loading ? (
          <div style={{ flex: 1, display: 'flex', justifyContent: 'center', alignItems: 'center', flexDirection: 'column', color: 'var(--text-muted)', padding: '6rem 0' }}>
            <div className="radar-loader-wrapper" style={{ marginBottom: '2.5rem' }}>
              <div className="radar-loader">
                <div className="radar-sweep" />
                <div className="radar-node radar-node-1" />
                <div className="radar-node radar-node-2" />
                <div className="radar-node radar-node-3" />
                <div className="radar-node radar-node-4" />
                <div className="radar-node radar-node-5" />
                <div className="radar-node radar-node-6" />
                <Compass size={56} className="radar-center-icon" />
              </div>
            </div>
            <p className="radar-loading-text">API 平台深度探测中...</p>
          </div>
        ) : (
          <>
            {activeView === 'home' && (
              <HomePage 
                platforms={platforms}
                warnings={warnings}
                onSelectPlatform={(p) => {
                  setSelectedPlatform(p);
                  setActiveView('platform');
                }}
                onAddPlatform={handleAddPlatform}
                onEditPlatform={handleEditPlatform}
                onDeletePlatform={handleDeletePlatform}
                onToggleEnable={handleTogglePlatform}
                onCompare={handleCompare}
                runningTests={runningTests}
                onStartTest={handleStartTest}
              />
            )}

            {activeView === 'platform' && (
              <PlatformPage 
                platform={selectedPlatform}
                onBack={() => setActiveView('home')}
                runningTests={runningTests}
                onStartTest={handleStartTest}
              />
            )}

            {activeView === 'compare' && (
              <ComparePage 
                platforms={comparePlatforms}
                onBack={() => setActiveView('home')}
              />
            )}
          </>
        )}
      </main>

      {/* CRUD 弹窗 */}
      {modalOpen && (
        <PlatformModal 
          platform={editingPlatform}
          onClose={() => setModalOpen(false)}
          onSave={handleSavePlatform}
        />
      )}

      {/* 兼容性告警抽屉 */}
      <WarningDrawer 
        isOpen={warningDrawerOpen}
        onClose={() => setWarningDrawerOpen(false)}
        warnings={warnings}
      />

      {/* 探测历史日志抽屉 */}
      <HistoryDrawer 
        isOpen={historyDrawerOpen}
        onClose={() => setHistoryDrawerOpen(false)}
      />
    </div>
  );
}
