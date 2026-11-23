import React, { useState, useEffect } from 'react';

interface LineItem {
  id?: string;
  sku: string;
  title: string;
  quantity: number;
  unit_price: number | string;
}

interface Order {
  id: string;
  shopify_order_number: string;
  customer_name: string;
  total_price: number | string;
  financial_status: string;
  fulfillment_status: string;
  workflow_source: string;
  notes?: string;
  created_at: string;
  updated_at: string;
  items: LineItem[];
}

interface WorkflowLog {
  id: string;
  timestamp: string;
  workflow: string;
  action: string;
  order_id?: string;
  status: string;
  details: string;
}

export default function App() {
  const [orders, setOrders] = useState<Order[]>([]);
  const [logs, setLogs] = useState<WorkflowLog[]>([]);
  const [filter, setFilter] = useState<'all' | 'w1' | 'w2'>('all');
  const [loadingOrders, setLoadingOrders] = useState(false);

  // Form State
  const [orderNumber, setOrderNumber] = useState('#1095');
  const [customerName, setCustomerName] = useState('Sarah Connor');
  const [targetWorkflow, setTargetWorkflow] = useState<'w1' | 'w2'>('w1');
  const [lineItems, setLineItems] = useState<LineItem[]>([
    { sku: 'TEE-BLK-M', title: 'Organic Cotton Tee', quantity: 2, unit_price: '24.50' }
  ]);

  // Agent State
  const [agentPrompt, setAgentPrompt] = useState('');
  const [agentExecuting, setAgentExecuting] = useState(false);
  const [agentResult, setAgentResult] = useState<any>(null);

  // Fetch Data
  const fetchOrders = async (currentFilter = filter) => {
    try {
      setLoadingOrders(true);
      const res = await fetch(`/api/orders?workflow=${currentFilter}`);
      if (res.ok) {
        const data = await res.json();
        setOrders(data);
      }
    } catch (err) {
      console.error('Failed to fetch orders:', err);
    } finally {
      setLoadingOrders(false);
    }
  };

  const fetchLogs = async () => {
    try {
      const res = await fetch('/api/logs?limit=40');
      if (res.ok) {
        const data = await res.json();
        setLogs(data);
      }
    } catch (err) {
      console.error('Failed to fetch logs:', err);
    }
  };

  const refreshAll = () => {
    fetchOrders(filter);
    fetchLogs();
  };

  useEffect(() => {
    refreshAll();
    const interval = setInterval(fetchLogs, 4000);
    return () => clearInterval(interval);
  }, []);

  useEffect(() => {
    fetchOrders(filter);
  }, [filter]);

  // Form Actions
  const handleAddLineItem = () => {
    setLineItems([
      ...lineItems,
      {
        sku: `ITEM-${Math.floor(Math.random() * 900 + 100)}`,
        title: 'Sample Accessory',
        quantity: 1,
        unit_price: '15.00'
      }
    ]);
  };

  const handleUpdateLineItem = (index: number, field: keyof LineItem, value: any) => {
    const updated = [...lineItems];
    updated[index] = { ...updated[index], [field]: value };
    setLineItems(updated);
  };

  const handleRemoveLineItem = (index: number) => {
    if (lineItems.length > 1) {
      setLineItems(lineItems.filter((_, i) => i !== index));
    }
  };

  const handleCreateOrder = async (e: React.FormEvent) => {
    e.preventDefault();
    const endpoint = targetWorkflow === 'w1' ? '/api/w1/orders' : '/api/w2/orders';
    try {
      const res = await fetch(endpoint, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          shopify_order_number: orderNumber,
          customer_name: customerName,
          items: lineItems.map((item) => ({
            sku: item.sku,
            title: item.title,
            quantity: Number(item.quantity) || 1,
            unit_price: String(item.unit_price || '0.00')
          }))
        })
      });
      if (res.ok) {
        const num = parseInt(orderNumber.replace('#', '')) || 1000;
        setOrderNumber(`#${num + 1}`);
        refreshAll();
      } else {
        alert('Failed to create order');
      }
    } catch (err) {
      console.error('Order creation error:', err);
    }
  };

  // Trigger Async Worker
  const handleTriggerAsync = async (orderId: string) => {
    try {
      const res = await fetch(`/api/w1/orders/${orderId}/sync-async`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ target_status: 'FULFILLED' })
      });
      if (res.ok) {
        fetchLogs();
        setTimeout(() => refreshAll(), 700);
      }
    } catch (err) {
      console.error('Failed to trigger async job:', err);
    }
  };

  // Agent Query
  const handleSubmitAgent = async () => {
    if (!agentPrompt.trim()) return;
    setAgentExecuting(true);
    try {
      const res = await fetch('/api/agent/query', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ prompt: agentPrompt })
      });
      if (res.ok) {
        const data = await res.json();
        setAgentResult(data);
        refreshAll();
      }
    } catch (err: any) {
      alert(`Agent execution failed: ${err.message}`);
    } finally {
      setAgentExecuting(false);
    }
  };

  return (
    <div className="min-h-screen bg-slate-900 text-slate-100">
      {/* Top Navbar */}
      <header className="border-b border-slate-800 bg-slate-950/80 backdrop-blur sticky top-0 z-50 px-6 py-4 flex items-center justify-between">
        <div className="flex items-center space-x-3">
          <div className="w-8 h-8 rounded-lg bg-emerald-500/20 text-emerald-400 flex items-center justify-center font-bold text-lg border border-emerald-500/30">
            S
          </div>
          <div>
            <h1 className="text-base font-bold text-white tracking-tight flex items-center space-x-2">
              <span>Shopify + Google ADK 2.0</span>
              <span className="text-xs font-medium px-2 py-0.5 rounded-full bg-slate-800 text-slate-400 border border-slate-700">
                React MVP
              </span>
            </h1>
            <p className="text-xs text-slate-400">
              Dual Workflow Architecture (PGlite + Worker | Firebase Data Connect)
            </p>
          </div>
        </div>
        <div className="flex items-center space-x-3 text-xs">
          <span className="inline-flex items-center px-2.5 py-1 rounded-md bg-blue-500/10 text-blue-400 border border-blue-500/30 font-medium">
            ● W1: PGlite + worker.py
          </span>
          <span className="inline-flex items-center px-2.5 py-1 rounded-md bg-amber-500/10 text-amber-400 border border-amber-500/30 font-medium">
            ● W2: Firebase Data Connect
          </span>
          <button
            onClick={refreshAll}
            className="px-3 py-1 bg-slate-800 hover:bg-slate-700 rounded text-slate-200 border border-slate-700 transition"
          >
            Refresh All
          </button>
        </div>
      </header>

      <main className="max-w-7xl mx-auto p-6 space-y-6">
        {/* Grid: Google ADK 2.0 Agent + Create Order */}
        <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
          {/* ADK Agent Assistant */}
          <section className="lg:col-span-5 bg-slate-950/60 border border-slate-800 rounded-xl p-5 flex flex-col justify-between shadow-sm">
            <div>
              <div className="flex items-center justify-between pb-3 border-b border-slate-800 mb-4">
                <div className="flex items-center space-x-2">
                  <span className="text-indigo-400 text-lg">🤖</span>
                  <h2 className="font-semibold text-sm text-slate-200">Google ADK 2.0 Root Agent</h2>
                </div>
                <span className="text-[11px] px-2 py-0.5 rounded bg-indigo-950/60 text-indigo-300 border border-indigo-800/60 font-mono">
                  ShopifyWorkflowAgent
                </span>
              </div>

              <p className="text-xs text-slate-400 mb-4">
                Natural language coordinator with Shopify tools and workflow routing. Empty-key safe with deterministic fallback execution.
              </p>

              {/* Quick Prompts */}
              <div className="flex flex-wrap gap-1.5 mb-3 text-[11px]">
                <button
                  type="button"
                  onClick={() => setAgentPrompt('Fetch Shopify order #1001 with items')}
                  className="px-2 py-1 rounded bg-slate-800/80 hover:bg-slate-700 text-slate-300 border border-slate-700/60"
                >
                  🔍 Fetch Mock #1001
                </button>
                <button
                  type="button"
                  onClick={() => setAgentPrompt('Create an order via Workflow 1 sync')}
                  className="px-2 py-1 rounded bg-blue-950/40 hover:bg-blue-900/60 text-blue-300 border border-blue-800/40"
                >
                  ⚡ W1 Sync Create
                </button>
                <button
                  type="button"
                  onClick={() => setAgentPrompt('Reconcile order status with async worker')}
                  className="px-2 py-1 rounded bg-blue-950/40 hover:bg-blue-900/60 text-blue-300 border border-blue-800/40"
                >
                  ⏳ W1 Async Worker
                </button>
                <button
                  type="button"
                  onClick={() => setAgentPrompt('Save order to Firebase Data Connect W2')}
                  className="px-2 py-1 rounded bg-amber-950/40 hover:bg-amber-900/60 text-amber-300 border border-amber-800/40"
                >
                  🔥 W2 Data Connect
                </button>
              </div>

              {/* Input Area */}
              <div className="space-y-2">
                <textarea
                  rows={2}
                  value={agentPrompt}
                  onChange={(e) => setAgentPrompt(e.target.value)}
                  placeholder="Ask the ADK Agent (e.g. 'Fetch Shopify order #1001 and store in W1')..."
                  className="w-full bg-slate-900 border border-slate-800 rounded-lg p-2.5 text-xs text-slate-200 focus:outline-none focus:border-indigo-500"
                />
                <button
                  type="button"
                  disabled={agentExecuting}
                  onClick={handleSubmitAgent}
                  className="w-full py-2 bg-indigo-600 hover:bg-indigo-500 text-white rounded-lg text-xs font-semibold tracking-wide transition flex items-center justify-center space-x-2"
                >
                  <span>{agentExecuting ? 'Processing with Agent...' : 'Execute with ADK Agent'}</span>
                </button>
              </div>
            </div>

            {/* Agent Result Display */}
            {agentResult && (
              <div className="mt-4 pt-3 border-t border-slate-800/60">
                <div className="text-[11px] font-mono text-slate-400 mb-1 flex items-center justify-between">
                  <span>Agent Result ({agentResult.mode || 'ADK'})</span>
                  {agentResult.selected_tool && (
                    <span className="text-indigo-400 font-medium">Tool: {agentResult.selected_tool}</span>
                  )}
                </div>
                <pre className="text-xs bg-slate-900/90 rounded p-2.5 text-slate-300 border border-slate-800 max-h-40 overflow-y-auto font-mono whitespace-pre-wrap">
                  {JSON.stringify(agentResult, null, 2)}
                </pre>
              </div>
            )}
          </section>

          {/* Create Order Form */}
          <section className="lg:col-span-7 bg-slate-950/60 border border-slate-800 rounded-xl p-5 shadow-sm">
            <div className="flex items-center justify-between pb-3 border-b border-slate-800 mb-4">
              <div className="flex items-center space-x-2">
                <span className="text-emerald-400 text-lg">📦</span>
                <h2 className="font-semibold text-sm text-slate-200">Parent Order & Child Line Items Builder</h2>
              </div>
              <span className="text-xs text-slate-400">1:N Entity Relationship</span>
            </div>

            <form onSubmit={handleCreateOrder} className="space-y-4">
              <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
                <div>
                  <label className="block text-[11px] font-medium text-slate-400 mb-1">Order #</label>
                  <input
                    type="text"
                    required
                    value={orderNumber}
                    onChange={(e) => setOrderNumber(e.target.value)}
                    className="w-full bg-slate-900 border border-slate-800 rounded px-2.5 py-1.5 text-xs text-slate-200"
                  />
                </div>
                <div>
                  <label className="block text-[11px] font-medium text-slate-400 mb-1">Customer Name</label>
                  <input
                    type="text"
                    required
                    value={customerName}
                    onChange={(e) => setCustomerName(e.target.value)}
                    className="w-full bg-slate-900 border border-slate-800 rounded px-2.5 py-1.5 text-xs text-slate-200"
                  />
                </div>
                <div>
                  <label className="block text-[11px] font-medium text-slate-400 mb-1">Target Workflow</label>
                  <select
                    value={targetWorkflow}
                    onChange={(e) => setTargetWorkflow(e.target.value as 'w1' | 'w2')}
                    className="w-full bg-slate-900 border border-slate-800 rounded px-2.5 py-1.5 text-xs text-slate-200"
                  >
                    <option value="w1">Workflow 1 (PGlite / Sync)</option>
                    <option value="w2">Workflow 2 (Firebase Data Connect)</option>
                  </select>
                </div>
              </div>

              {/* Child Line Items */}
              <div className="bg-slate-900/50 border border-slate-800/80 rounded-lg p-3 space-y-2">
                <div className="flex items-center justify-between mb-1">
                  <span className="text-xs font-semibold text-slate-300">Child Line Items (1-to-Many)</span>
                  <button
                    type="button"
                    onClick={handleAddLineItem}
                    className="text-[11px] text-emerald-400 hover:text-emerald-300 font-medium"
                  >
                    + Add Item
                  </button>
                </div>
                <div className="space-y-2">
                  {lineItems.map((item, idx) => (
                    <div key={idx} className="grid grid-cols-12 gap-2 items-center">
                      <input
                        type="text"
                        placeholder="SKU"
                        value={item.sku}
                        onChange={(e) => handleUpdateLineItem(idx, 'sku', e.target.value)}
                        className="col-span-4 bg-slate-900 border border-slate-800 rounded px-2 py-1 text-xs"
                      />
                      <input
                        type="text"
                        placeholder="Title"
                        value={item.title}
                        onChange={(e) => handleUpdateLineItem(idx, 'title', e.target.value)}
                        className="col-span-4 bg-slate-900 border border-slate-800 rounded px-2 py-1 text-xs"
                      />
                      <input
                        type="number"
                        min="1"
                        placeholder="Qty"
                        value={item.quantity}
                        onChange={(e) => handleUpdateLineItem(idx, 'quantity', parseInt(e.target.value) || 1)}
                        className="col-span-2 bg-slate-900 border border-slate-800 rounded px-2 py-1 text-xs"
                      />
                      <div className="col-span-2 flex items-center space-x-1">
                        <input
                          type="number"
                          step="0.01"
                          placeholder="Price"
                          value={item.unit_price}
                          onChange={(e) => handleUpdateLineItem(idx, 'unit_price', e.target.value)}
                          className="w-full bg-slate-900 border border-slate-800 rounded px-2 py-1 text-xs"
                        />
                        {lineItems.length > 1 && (
                          <button
                            type="button"
                            onClick={() => handleRemoveLineItem(idx)}
                            className="text-slate-500 hover:text-red-400 px-1 text-xs"
                          >
                            ×
                          </button>
                        )}
                      </div>
                    </div>
                  ))}
                </div>
              </div>

              <div className="flex items-center justify-end space-x-3 pt-2">
                <button
                  type="submit"
                  className="px-5 py-2 bg-emerald-600 hover:bg-emerald-500 text-white rounded-lg text-xs font-semibold tracking-wide transition"
                >
                  Create Order
                </button>
              </div>
            </form>
          </section>
        </div>

        {/* Orders Explorer: Workflow 1 vs. Workflow 2 */}
        <section className="bg-slate-950/60 border border-slate-800 rounded-xl p-5 shadow-sm">
          <div className="flex flex-col sm:flex-row sm:items-center justify-between pb-3 border-b border-slate-800 gap-3">
            <div className="flex items-center space-x-3">
              <h2 className="font-semibold text-sm text-slate-200">Orders & Nested Line Items</h2>
              <div className="flex rounded-lg bg-slate-900 p-0.5 border border-slate-800 text-xs">
                <button
                  onClick={() => setFilter('all')}
                  className={`px-2.5 py-1 rounded transition ${
                    filter === 'all'
                      ? 'bg-slate-800 text-slate-200 font-medium'
                      : 'text-slate-400 hover:text-slate-200'
                  }`}
                >
                  All
                </button>
                <button
                  onClick={() => setFilter('w1')}
                  className={`px-2.5 py-1 rounded transition ${
                    filter === 'w1'
                      ? 'bg-blue-900 text-blue-200 font-medium'
                      : 'text-slate-400 hover:text-slate-200'
                  }`}
                >
                  W1 (PGlite)
                </button>
                <button
                  onClick={() => setFilter('w2')}
                  className={`px-2.5 py-1 rounded transition ${
                    filter === 'w2'
                      ? 'bg-amber-900 text-amber-200 font-medium'
                      : 'text-slate-400 hover:text-slate-200'
                  }`}
                >
                  W2 (Data Connect)
                </button>
              </div>
            </div>
            <span className="text-xs text-slate-400 font-mono">
              {orders.length} order(s) loaded
            </span>
          </div>

          <div className="mt-4 space-y-3">
            {loadingOrders && orders.length === 0 ? (
              <div className="text-center py-8 text-xs text-slate-500">Loading orders...</div>
            ) : orders.length === 0 ? (
              <div className="text-center py-8 text-xs text-slate-500">
                No orders found for selected workflow filter.
              </div>
            ) : (
              orders.map((order) => {
                const isW1 = order.workflow_source === 'WORKFLOW_1_PGLITE';
                const badgeClass = isW1
                  ? 'bg-blue-500/10 text-blue-400 border-blue-500/30'
                  : 'bg-amber-500/10 text-amber-400 border-amber-500/30';
                const badgeLabel = isW1 ? 'Workflow 1 (PGlite)' : 'Workflow 2 (Firebase Data Connect)';

                const statusClass =
                  order.fulfillment_status === 'FULFILLED'
                    ? 'bg-emerald-500/10 text-emerald-400 border-emerald-500/30'
                    : 'bg-yellow-500/10 text-yellow-400 border-yellow-500/30';

                return (
                  <div key={order.id} className="border border-slate-800 bg-slate-900/40 rounded-lg p-4 space-y-3">
                    <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2">
                      <div className="flex items-center space-x-2">
                        <span className={`text-xs px-2 py-0.5 rounded border font-medium ${badgeClass}`}>
                          {badgeLabel}
                        </span>
                        <span className="font-bold text-sm text-slate-100">{order.shopify_order_number}</span>
                        <span className="text-xs text-slate-400">({order.customer_name})</span>
                      </div>
                      <div className="flex items-center space-x-2">
                        <span className={`text-xs px-2 py-0.5 rounded border font-mono ${statusClass}`}>
                          {order.fulfillment_status}
                        </span>
                        <span className="text-xs font-mono font-bold text-emerald-400">
                          ${parseFloat(String(order.total_price)).toFixed(2)}
                        </span>
                        {isW1 && (
                          <button
                            type="button"
                            onClick={() => handleTriggerAsync(order.id)}
                            className="px-2.5 py-1 bg-blue-600/20 hover:bg-blue-600/30 text-blue-300 border border-blue-500/30 rounded text-xs font-medium transition"
                          >
                            ⚡ Trigger Async Worker
                          </button>
                        )}
                      </div>
                    </div>

                    {/* Nested Child Line Items */}
                    <div className="border-t border-slate-800/80 pt-2 space-y-1">
                      <div className="text-[11px] font-semibold text-slate-400 uppercase tracking-wider">
                        Child Line Items ({order.items?.length || 0})
                      </div>
                      <div className="space-y-1">
                        {(order.items || []).map((item, idx) => (
                          <div
                            key={item.id || idx}
                            className="flex items-center justify-between py-1 px-2.5 bg-slate-900/60 rounded text-xs"
                          >
                            <div className="flex items-center space-x-2">
                              <span className="font-mono text-slate-400">{item.sku}</span>
                              <span className="text-slate-200">{item.title}</span>
                            </div>
                            <div className="text-slate-400 font-mono">
                              {item.quantity} × ${parseFloat(String(item.unit_price)).toFixed(2)}
                            </div>
                          </div>
                        ))}
                      </div>
                    </div>
                  </div>
                );
              })
            )}
          </div>
        </section>

        {/* Live Logs */}
        <section className="bg-slate-950/60 border border-slate-800 rounded-xl p-5 shadow-sm">
          <div className="flex items-center justify-between pb-3 border-b border-slate-800 mb-3">
            <div className="flex items-center space-x-2">
              <span className="text-amber-400">📜</span>
              <h2 className="font-semibold text-sm text-slate-200">Live Workflow Logs & Worker Events</h2>
            </div>
            <button
              onClick={fetchLogs}
              className="text-xs text-slate-400 hover:text-slate-200 font-mono"
            >
              Refresh Logs
            </button>
          </div>

          <div className="bg-slate-900 rounded-lg p-3 max-h-56 overflow-y-auto space-y-1.5 font-mono text-[11px] border border-slate-800">
            {logs.length === 0 ? (
              <div className="text-slate-500">No events logged yet.</div>
            ) : (
              logs.map((log) => {
                const isW1 = log.workflow === 'WORKFLOW_1_PGLITE';
                const badgeClass = isW1 ? 'text-blue-400' : 'text-amber-400';
                const time = new Date(log.timestamp).toLocaleTimeString();
                return (
                  <div
                    key={log.id}
                    className="flex items-start space-x-2 py-0.5 border-b border-slate-800/40"
                  >
                    <span className="text-slate-500 select-none">{time}</span>
                    <span className={`font-semibold ${badgeClass}`}>[{log.workflow}]</span>
                    <span className="text-slate-300 font-bold">{log.action}</span>
                    <span className="text-slate-400">{log.details}</span>
                  </div>
                );
              })
            )}
          </div>
        </section>
      </main>
    </div>
  );
}
