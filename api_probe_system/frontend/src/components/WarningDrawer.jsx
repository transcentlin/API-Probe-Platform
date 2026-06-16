import React from 'react';
import { X, AlertTriangle, Cpu, CheckCircle } from 'lucide-react';

export default function WarningDrawer({ isOpen, onClose, warnings }) {
  if (!isOpen) return null;

  return (
    <div className="drawer-overlay" onClick={onClose}>
      <div className="drawer-content" onClick={e => e.stopPropagation()}>
        {/* 头部 */}
        <div className="drawer-header">
          <div className="flex-align" style={{ gap: '0.5rem' }}>
            <AlertTriangle className="text-warning" size={20} />
            <h2 style={{ fontSize: '1.25rem', fontWeight: 700, margin: 0, fontFamily: 'var(--font-title)' }}>
              兼容性告警中心
            </h2>
          </div>
          <button className="btn-close" onClick={onClose} style={{ background: 'none', border: 'none', color: 'var(--text-dim)', cursor: 'pointer' }}>
            <X size={20} />
          </button>
        </div>

        {/* 列表内容 */}
        <div className="drawer-body">
          {warnings.length === 0 ? (
            <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', height: '100%', color: 'var(--text-muted)', textAlign: 'center', padding: '3rem 1.5rem' }}>
              <CheckCircle size={48} color="#10b981" style={{ marginBottom: '1rem', filter: 'drop-shadow(0 0 10px rgba(16, 185, 129, 0.2))' }} />
              <p style={{ fontSize: '1rem', fontWeight: 600, color: 'var(--text-bright)' }}>所有平台工作正常</p>
              <p style={{ fontSize: '0.8rem', opacity: 0.8 }}>暂无发现处理器兼容性或非标端点引发的报错。</p>
            </div>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
              <p style={{ fontSize: '0.8rem', color: 'var(--text-dim)' }}>
                检测到以下平台在模型发现过程中出现非标格式或网络异常。您可以通过这些数据决策是否需要为此开发新的适配器。
              </p>
              {warnings.map((w, idx) => (
                <div key={w.platform_name + idx} className="warning-card">
                  <div className="flex-between" style={{ marginBottom: '0.5rem' }}>
                    <span className="warning-card-title">{w.platform_name}</span>
                    <span className="warning-card-time">{w.detected_at}</span>
                  </div>
                  
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '0.4rem', fontSize: '0.8rem' }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '0.3rem', color: 'var(--text-dim)' }}>
                      <Cpu size={12} />
                      <span>调用处理器：<code>{w.handler_name}</code></span>
                    </div>
                    <div style={{ color: 'var(--text-dim)', wordBreak: 'break-all', display: 'flex', flexDirection: 'column', gap: '0.2rem' }}>
                      <span>接口 URL：<code style={{ fontSize: '0.75rem', color: '#93c5fd' }}>{w.base_url}</code></span>
                    </div>
                    
                    <div className="warning-error-box">
                      <div className="error-title">报错堆栈：</div>
                      <div className="error-msg">{w.error_message}</div>
                    </div>
                    
                    <div className="warning-suggest-box">
                      <div className="suggest-title">💡 开发决策建议：</div>
                      <div className="suggest-msg">{w.suggestion}</div>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
