// 修改历史 (Revision History)
// ==================================
// 版本: v1.2.0
// 日期: 2026-06-16
// 修改说明: 新增 getLatestReportContent(platformName) 方法，调用 /api/reports/latest?platform={name} 获取最新探测报告。
// ==================================

// -*- coding: utf-8 -*-

/**
 * API Probe Station 统一前端 API 客户端
 */

const BASE_URL = '/api';

export const apiClient = {
  // ── 平台配置 CRUD ──
  async getPlatforms() {
    const res = await fetch(`${BASE_URL}/platforms`);
    if (!res.ok) throw new Error('获取平台列表失败');
    return res.json();
  },

  async getPlatform(name) {
    const res = await fetch(`${BASE_URL}/platforms/${name}`);
    if (!res.ok) throw new Error(`获取平台 ${name} 详情失败`);
    return res.json();
  },

  async createPlatform(data) {
    const res = await fetch(`${BASE_URL}/platforms`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data)
    });
    if (!res.ok) {
      const errData = await res.json().catch(() => ({}));
      throw new Error(errData.detail || '新建平台失败');
    }
    return res.json();
  },

  async updatePlatform(name, data) {
    const res = await fetch(`${BASE_URL}/platforms/${name}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data)
    });
    if (!res.ok) {
      const errData = await res.json().catch(() => ({}));
      throw new Error(errData.detail || '修改平台失败');
    }
    return res.json();
  },

  async deletePlatform(name) {
    const res = await fetch(`${BASE_URL}/platforms/${name}`, {
      method: 'DELETE'
    });
    if (!res.ok) throw new Error(`删除平台 ${name} 失败`);
    return true;
  },

  async togglePlatform(name, enabled) {
    const res = await fetch(`${BASE_URL}/platforms/${name}/toggle`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ enabled })
    });
    if (!res.ok) throw new Error('切换平台状态失败');
    return res.json();
  },

  async getCompatibilityWarnings() {
    const res = await fetch(`${BASE_URL}/platforms/warnings`);
    if (!res.ok) throw new Error('获取平台兼容性警告失败');
    return res.json();
  },

  // ── 异步测试调度 ──
  async startTest(platforms, mode = 'standard') {
    const res = await fetch(`${BASE_URL}/tests/start`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ platforms, mode })
    });
    if (!res.ok) {
      const errData = await res.json().catch(() => ({}));
      throw new Error(errData.detail || '启动测试任务失败');
    }
    return res.json();
  },

  // ── 探测历史日志 ──
  async getTestHistory() {
    const res = await fetch(`${BASE_URL}/tests/history`);
    if (!res.ok) throw new Error('获取探测日志失败');
    return res.json();
  },

  async clearTestHistory() {
    const res = await fetch(`${BASE_URL}/tests/history`, {
      method: 'DELETE'
    });
    if (!res.ok) throw new Error('清空探测日志失败');
    return true;
  },

  // ── 报告管理 ──
  async listReports(platformName = '') {
    const url = platformName ? `${BASE_URL}/reports?platform=${encodeURIComponent(platformName)}` : `${BASE_URL}/reports`;
    const res = await fetch(url);
    if (!res.ok) throw new Error('获取报告列表失败');
    return res.json();
  },

  async getLatestReportContent(platformName) {
    const res = await fetch(`${BASE_URL}/reports/latest?platform=${encodeURIComponent(platformName)}`);
    if (res.status === 404) return '';
    if (!res.ok) throw new Error('加载最新报告文本失败');
    return res.text();
  },

  async getReportContent(filename) {
    const res = await fetch(`${BASE_URL}/reports/${filename}`);
    if (!res.ok) throw new Error('加载报告文本失败');
    return res.text();
  },

  async deleteReport(filename) {
    const res = await fetch(`${BASE_URL}/reports/${filename}`, {
      method: 'DELETE'
    });
    if (!res.ok) throw new Error('删除报告失败');
    return true;
  },

  async generateComparison(platforms) {
    const res = await fetch(`${BASE_URL}/reports/compare`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ platforms })
    });
    if (!res.ok) {
      const errData = await res.json().catch(() => ({}));
      throw new Error(errData.detail || '生成横向对比报告失败');
    }
    return res.json();
  },

  // ── SSE 实时进度订阅 ──
  subscribeToEvents(onMessage, onError) {
    const eventSource = new EventSource(`${BASE_URL}/tests/events`);
    
    eventSource.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        onMessage(data);
      } catch (err) {
        console.error('解析 SSE 事件失败', err);
      }
    };

    eventSource.onerror = (err) => {
      if (onError) onError(err);
      eventSource.close();
    };

    return () => {
      eventSource.close();
    };
  }
};
