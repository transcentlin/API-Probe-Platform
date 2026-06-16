import React, { useState, useEffect } from 'react';
import { X, Eye, EyeOff } from 'lucide-react';

export default function PlatformModal({ platform, onClose, onSave }) {
  const [name, setName] = useState('');
  const [baseUrl, setBaseUrl] = useState('');
  const [apiKey, setApiKey] = useState('');
  const [website, setWebsite] = useState('');
  const [notes, setNotes] = useState('');
  const [showKey, setShowKey] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const isEdit = !!platform;

  useEffect(() => {
    if (platform) {
      setName(platform.name);
      setBaseUrl(platform.base_url);
      setApiKey(''); // 编辑时，不显示原本的 API Key (后端已遮罩)，输入框置空代表不修改
      setWebsite(platform.website || '');
      setNotes(platform.notes || '');
    } else {
      setName('');
      setBaseUrl('');
      setApiKey('');
      setWebsite('');
      setNotes('');
    }
  }, [platform]);

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!name.trim()) return setError('平台名称不能为空');
    if (!baseUrl.trim()) return setError('Base URL 不能为空');
    if (!isEdit && !apiKey.trim()) return setError('API 密钥不能为空');

    setLoading(true);
    setError('');

    // 智能动态检测并确认端点发现处理器 (Discovery Handler)
    let autoDiscoveryHandler = 'openai';
    const lowerUrl = baseUrl.toLowerCase();
    if (lowerUrl.includes('cloudflare')) {
      autoDiscoveryHandler = 'cloudflare';
    } else if (lowerUrl.includes('ollama') || lowerUrl.includes('11434')) {
      autoDiscoveryHandler = 'ollama';
    }

    const payload = {
      name: name.trim(),
      base_url: baseUrl.trim(),
      website: website.trim(),
      notes: notes.trim(),
      discovery_handler: autoDiscoveryHandler
    };

    // 如果在编辑状态且输入了新的 api_key，或者是在新建状态，则加入 api_key
    if (apiKey.trim()) {
      payload.api_key = apiKey;
    }

    try {
      await onSave(payload, isEdit);
    } catch (err) {
      setError(err.message || '保存平台失败');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="modal-overlay">
      <div className="modal-content">
        <div className="modal-header">
          <h3 className="modal-title">{isEdit ? '编辑平台配置' : '新增探测平台'}</h3>
          <button className="btn btn-secondary btn-icon-only" onClick={onClose} style={{ borderRadius: '50%', padding: '0.25rem' }}>
            <X size={18} />
          </button>
        </div>
        <form onSubmit={handleSubmit}>
          <div className="modal-body" style={{ maxHeight: '70vh', overflowY: 'auto' }}>
            {error && (
              <div style={{ background: 'rgba(239, 68, 68, 0.15)', border: '1px solid rgba(239, 68, 68, 0.3)', padding: '0.75rem 1rem', borderRadius: '8px', color: '#fca5a5', marginBottom: '1.25rem', fontSize: '0.875rem' }}>
                {error}
              </div>
            )}
            
            <div className="form-group">
              <label className="form-label">平台名称</label>
              <input
                type="text"
                className="form-control"
                placeholder="例如: Groq"
                value={name}
                onChange={e => setName(e.target.value)}
                disabled={loading}
                required
              />
            </div>

            <div className="form-group">
              <label className="form-label">API 基础 URL (Base URL)</label>
              <input
                type="url"
                className="form-control"
                placeholder="https://api.groq.com/openai/v1"
                value={baseUrl}
                onChange={e => setBaseUrl(e.target.value)}
                disabled={loading}
                required
              />
            </div>

            <div className="form-group">
              <label className="form-label">
                API 密钥 (API Key) 
                {isEdit && <span style={{ color: 'hsl(var(--color-primary))', fontWeight: 'normal', marginLeft: '0.5rem' }}>(留空表示不修改原密钥)</span>}
              </label>
              <div style={{ position: 'relative' }}>
                <input
                  type={showKey ? 'text' : 'password'}
                  className="form-control"
                  style={{ paddingRight: '2.5rem' }}
                  placeholder={isEdit ? '••••••••••••••••••••••••' : '输入明文 API Key'}
                  value={apiKey}
                  onChange={e => setApiKey(e.target.value)}
                  disabled={loading}
                  required={!isEdit}
                />
                <button
                  type="button"
                  onClick={() => setShowKey(!showKey)}
                  style={{ position: 'absolute', right: '0.75rem', top: '50%', transform: 'translateY(-50%)', background: 'none', border: 'none', color: 'var(--text-dim)', cursor: 'pointer' }}
                >
                  {showKey ? <EyeOff size={16} /> : <Eye size={16} />}
                </button>
              </div>
            </div>

            {/* 端点发现处理器由前端根据 Base URL 动态匹配生成，无需用户手动配置 */}

            <div className="form-group">
              <label className="form-label">官网地址 (可选)</label>
              <input
                type="text"
                className="form-control"
                placeholder="https://groq.com"
                value={website}
                onChange={e => setWebsite(e.target.value)}
                disabled={loading}
              />
            </div>

            <div className="form-group">
              <label className="form-label">备注说明 (Notes - 可选)</label>
              <textarea
                className="form-control"
                placeholder="例如: 额度低，仅供轻量级多轮测试"
                rows="3"
                value={notes}
                onChange={e => setNotes(e.target.value)}
                disabled={loading}
              ></textarea>
            </div>
          </div>
          <div className="modal-footer">
            <button type="button" className="btn btn-secondary" onClick={onClose} disabled={loading}>
              取消
            </button>
            <button type="submit" className="btn btn-primary" disabled={loading}>
              {loading ? '正在保存...' : '保存配置'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
