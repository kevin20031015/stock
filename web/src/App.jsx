import React, { useState, useEffect, useMemo, useCallback, useRef } from 'react';
import { ComposedChart, Line, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, ReferenceLine, Cell, Area, LineChart, Legend } from 'recharts';
import { Activity, Search, Loader2, TrendingUp, DollarSign, History, Trash2, Filter, Settings, CheckCircle2, XCircle, Zap, Cpu, ScanSearch, Target, ArrowRightCircle, ShieldAlert, Save, BrainCircuit, Globe, BarChart3, AlertTriangle, Newspaper, Sliders, X, TrendingDown, RefreshCcw, ChevronDown, ChevronUp, PieChart, LayoutDashboard, Radio } from 'lucide-react';

// ═══════════════════════════════════════════════════════
// 1. 共用視覺元件
// ═══════════════════════════════════════════════════════

const Candlestick = React.memo((props) => {
  const { x, y, width, height, low, high, open, close } = props;
  if (low == null || high == null || open == null || close == null) return null;
  const isUp = close >= open;
  const color = isUp ? '#ef4444' : '#22c55e';
  const priceRange = high - low;
  if (priceRange === 0) {
    const midY = y + height / 2;
    return <g stroke={color} fill={color} strokeWidth="1.5"><line x1={x} y1={midY} x2={x + width} y2={midY} /></g>;
  }
  const pixelPerDollar = height / priceRange;
  const wickX = x + width / 2;
  const bodyTop    = y + (high - Math.max(open, close)) * pixelPerDollar;
  const bodyBottom = y + (high - Math.min(open, close)) * pixelPerDollar;
  const bodyHeight = Math.max(2, bodyBottom - bodyTop);
  return (
    <g stroke={color} fill={color} strokeWidth="1.5">
      <line x1={wickX} y1={y} x2={wickX} y2={y + height} />
      {open !== close
        ? <rect x={x + 1} y={bodyTop} width={Math.max(1, width - 2)} height={bodyHeight} fill={color} />
        : <line x1={x + 1} y1={bodyTop} x2={x + width - 1} y2={bodyTop} strokeWidth="2" />}
    </g>
  );
});

const SignalDot = React.memo((props) => {
  const { cx, cy, payload } = props;
  if (payload.signal === 1)  return <g transform={`translate(${cx},${cy + 30})`}><circle r="8" fill="#ef4444" stroke="white" strokeWidth="2" className="animate-pulse"/><text x="0" y="4" textAnchor="middle" fill="white" fontSize="10" fontWeight="bold">B</text></g>;
  if (payload.signal === 2)  return <g transform={`translate(${cx},${cy + 30})`}><circle r="8" fill="#8b5cf6" stroke="white" strokeWidth="2"/><text x="0" y="4" textAnchor="middle" fill="white" fontSize="10" fontWeight="bold">D</text></g>;
  if (payload.signal === -1) return <g transform={`translate(${cx},${cy - 30})`}><circle r="8" fill="#22c55e" stroke="white" strokeWidth="2"/><text x="0" y="4" textAnchor="middle" fill="white" fontSize="10" fontWeight="bold">S</text></g>;
  return null;
});

const CustomTooltip = React.memo(({ active, payload, label }) => {
  if (!active || !payload || !payload.length) return null;
  const d = payload[0]?.payload;
  if (!d) return null;
  const isUp = d.close >= d.open;
  const pct = d.close && d.open ? (((d.close - d.open) / d.open) * 100).toFixed(2) : null;
  const row = (title, value, color = '#e2e8f0') => (
    <div style={{ display: 'flex', justifyContent: 'space-between', gap: '16px', marginBottom: '2px' }}>
      <span style={{ color: '#94a3b8', fontSize: '12px' }}>{title}</span>
      <span style={{ color, fontFamily: 'monospace', fontWeight: 'bold', fontSize: '12px' }}>{value}</span>
    </div>
  );
  return (
    <div style={{ background: '#1e293b', border: '1px solid #334155', borderRadius: '8px', padding: '10px 14px', minWidth: '160px', boxShadow: '0 4px 20px rgba(0,0,0,0.5)' }}>
      <div style={{ fontSize: '12px', color: '#64748b', marginBottom: '6px', borderBottom: '1px solid #334155', paddingBottom: '4px' }}>{label}</div>
      {row('開', d.open?.toFixed(2))}
      {row('高', d.high?.toFixed(2), '#f87171')}
      {row('低', d.low?.toFixed(2), '#4ade80')}
      {row('收', d.close?.toFixed(2), isUp ? '#ef4444' : '#22c55e')}
      {pct !== null && row('漲跌', `${isUp ? '+' : ''}${pct}%`, isUp ? '#ef4444' : '#22c55e')}
      {d.ma5  != null && <div style={{ borderTop: '1px solid #334155', marginTop: '6px', paddingTop: '4px' }}>{row('MA5', d.ma5?.toFixed(2), '#f59e0b')}</div>}
      {d.ma20 != null && row('MA20', d.ma20?.toFixed(2), '#3b82f6')}
    </div>
  );
});

// ═══════════════════════════════════════════════════════
// 2. 主應用程式
// ═══════════════════════════════════════════════════════
const App = () => {

  // ── State ────────────────────────────────────────────
  const [activeTab, setActiveTab] = useState('analysis'); // 'analysis' | 'scanner' | 'portfolio'
  const [watchlist, setWatchlist] = useState(() => JSON.parse(localStorage.getItem('stockWatchlist_v8')) || [{ id: '2330.TW', displayId: '2330', name: '台積電' }]);
  const [initialCapital, setInitialCapital] = useState(() => localStorage.getItem('userCapital') || 500000);
  const [symbol, setSymbol] = useState(watchlist[0].id);
  const [chartData, setChartData] = useState([]);
  const [strategyInfo, setStrategyInfo] = useState(null);
  const [marketSentiment, setMarketSentiment] = useState(null);
  const [newsSentiment, setNewsSentiment] = useState(null);
  const [newStock, setNewStock] = useState('');
  const [loading, setLoading] = useState(false);
  const [period, setPeriod] = useState('6mo');
  const [optimizing, setOptimizing] = useState(false);
  const [gaResult, setGaResult] = useState(null);
  const [subChart, setSubChart] = useState('macd'); // 'macd' | 'kd' | 'equity'

  const defaultParams = { strategy_type: "swing", adx_threshold: 20, rsi_upper: 85, rsi_lower: 40, vol_ratio: 1.75, stop_loss: 0.08, take_profit: 0.20, atr_multiplier: 2.0 };
  const [activeParams, setActiveParams] = useState(defaultParams);
  const [showSettings, setShowSettings] = useState(false);
  const [stockSettingsCache, setStockSettingsCache] = useState(() => JSON.parse(localStorage.getItem('stockSettingsCache_v1')) || {});
  const [batchOptimizing, setBatchOptimizing] = useState(false);
  const [batchProgress, setBatchProgress] = useState({ current: 0, total: 0, currentStock: '' });

  const [scanning, setScanning] = useState(false);
  const [scanResults, setScanResults] = useState([]);
  const [scanProgress, setScanProgress] = useState({ current: 0, total: 0 });
  const [scanPage, setScanPage] = useState(0);
  const scanPollRef = useRef(null);

  const [aiPrediction, setAiPrediction] = useState(null);
  const [aiLoading, setAiLoading] = useState(false);
  const [showAiPopover, setShowAiPopover] = useState(false);

  const [myTrades, setMyTrades] = useState(() => { try { return JSON.parse(localStorage.getItem('myTrades_v1')) || []; } catch { return []; } });
  const [showTradeInput, setShowTradeInput] = useState(false);
  const [tradeForm, setTradeForm] = useState({ type: 'BUY', price: '', shares: '', note: '' });
  const [editingTradeId, setEditingTradeId] = useState(null);

  // ── LocalStorage sync ────────────────────────────────
  useEffect(() => localStorage.setItem('stockWatchlist_v8', JSON.stringify(watchlist)), [watchlist]);
  useEffect(() => localStorage.setItem('userCapital', initialCapital), [initialCapital]);
  useEffect(() => localStorage.setItem('myTrades_v1', JSON.stringify(myTrades)), [myTrades]);
  useEffect(() => localStorage.setItem('stockSettingsCache_v1', JSON.stringify(stockSettingsCache)), [stockSettingsCache]);
  useEffect(() => { if (scanPollRef.current) clearInterval(scanPollRef.current); }, []);

  // ── API ──────────────────────────────────────────────
  const abortControllerRef = useRef(null);

  const fetchData = useCallback(async (customParams = null) => {
    if (abortControllerRef.current) abortControllerRef.current.abort();
    const controller = new AbortController();
    abortControllerRef.current = controller;
    setLoading(true);
    setChartData([]); setStrategyInfo(null); setMarketSentiment(null); setNewsSentiment(null);
    try {
      const paramsToSend = customParams || activeParams;
      const url = `http://127.0.0.1:5000/api/stock/${symbol}?period=${period}&capital=${initialCapital}&params=${JSON.stringify(paramsToSend)}`;
      const res = await fetch(url, { signal: controller.signal });
      if (!res.ok) throw new Error("API Error");
      const data = await res.json();
      if (!controller.signal.aborted) {
        setChartData(data.chart_data);
        setStrategyInfo(data.strategy);
        setMarketSentiment(data.market_sentiment);
        setNewsSentiment(data.news_sentiment);
      }
    } catch (error) {
      if (error.name !== 'AbortError') console.error(error);
    }
    setLoading(false);
  }, [symbol, period, initialCapital, activeParams]);

  useEffect(() => {
    setGaResult(null);
    setAiPrediction(null);
    const cachedParams = stockSettingsCache[symbol];
    const params = cachedParams || defaultParams;
    setActiveParams(params);
    fetchData(params);
    return () => { if (abortControllerRef.current) abortControllerRef.current.abort(); };
  }, [symbol, period, initialCapital]);

  const handleManualParamChange = (newParams) => {
    setActiveParams(newParams);
    setStockSettingsCache(prev => ({ ...prev, [symbol]: newParams }));
    fetchData(newParams);
  };

  const runOptimization = async () => {
    setOptimizing(true);
    try {
      const res = await fetch(`http://127.0.0.1:5000/api/optimize/${symbol}?capital=${initialCapital}`);
      const data = await res.json();
      if (data?.best_params) {
        setStockSettingsCache(prev => ({ ...prev, [symbol]: data.best_params }));
        setActiveParams(data.best_params);
        setGaResult(data);
        fetchData(data.best_params);
      }
    } catch (e) { alert("優化失敗"); }
    setOptimizing(false);
  };

  const runBatchOptimization = async () => {
    if (batchOptimizing) return;
    setBatchOptimizing(true);
    let newCache = { ...stockSettingsCache };
    let completed = 0;
    for (const stock of watchlist) {
      setBatchProgress({ current: completed + 1, total: watchlist.length, currentStock: stock.name });
      try {
        const res = await fetch(`http://127.0.0.1:5000/api/optimize/${stock.id}?capital=${initialCapital}`);
        const data = await res.json();
        if (data?.best_params) newCache[stock.id] = data.best_params;
      } catch (e) {}
      completed++;
    }
    setStockSettingsCache(newCache);
    if (newCache[symbol]) { setActiveParams(newCache[symbol]); fetchData(newCache[symbol]); }
    setBatchOptimizing(false);
    alert("✅ 全批次優化完成！");
  };

  const runScan = useCallback(async () => {
    if (scanPollRef.current) clearInterval(scanPollRef.current);
    setScanning(true);
    setScanResults([]);
    setScanProgress({ current: 0, total: 0 });
    setActiveTab('scanner');
    try {
      const res = await fetch('http://127.0.0.1:5000/api/scan', { method: 'POST' });
      const data = await res.json();
      const taskId = data.task_id;
      let missCount = 0;
      scanPollRef.current = setInterval(async () => {
        try {
          const s = await fetch(`http://127.0.0.1:5000/api/scan/status/${taskId}`);
          const sd = await s.json();
          missCount = 0;
          setScanProgress({ current: sd.progress || 0, total: sd.total || 0 });
          if (sd.status === 'done') {
            clearInterval(scanPollRef.current); scanPollRef.current = null;
            setScanResults(sd.results || []); setScanPage(0); setScanning(false);
          } else if (sd.status === 'error') {
            clearInterval(scanPollRef.current); scanPollRef.current = null;
            setScanning(false); alert('掃描失敗：' + sd.error);
          }
        } catch (e) {
          if (++missCount >= 10) { clearInterval(scanPollRef.current); scanPollRef.current = null; setScanning(false); }
        }
      }, 3000);
    } catch (e) { setScanning(false); alert('掃描啟動失敗'); }
  }, []);

  const runAiPrediction = useCallback(async () => {
    setAiLoading(true);
    try {
      const res = await fetch(`http://127.0.0.1:5000/api/predict_ai/${symbol}`);
      const data = await res.json();
      setAiPrediction(data);
    } catch (e) { alert("AI 預測失敗"); }
    setAiLoading(false);
  }, [symbol]);

  const handleAddStock = useCallback(async (e) => {
    e.preventDefault();
    if (!newStock) return;
    try {
      const res = await fetch(`http://127.0.0.1:5000/api/search/${newStock}`);
      const info = await res.json();
      if (info.success && !watchlist.some(s => s.id === info.id)) {
        setWatchlist([...watchlist, { id: info.id, displayId: newStock.toUpperCase(), name: info.name }]);
        setSymbol(info.id);
      }
      setNewStock('');
    } catch (err) {}
  }, [newStock, watchlist]);

  const updateTrade = useCallback((id, newData) => {
    setMyTrades(prev => prev.map(t => t.id === id ? { ...t, ...newData } : t));
    setEditingTradeId(null);
  }, []);

  const addTrade = useCallback(() => {
    if (!tradeForm.price || !tradeForm.shares) return;
    setMyTrades(prev => [{
      id: Date.now(), symbol, symbolName: watchlist.find(w => w.id === symbol)?.name || symbol,
      type: tradeForm.type, price: parseFloat(tradeForm.price), shares: parseInt(tradeForm.shares),
      note: tradeForm.note, date: new Date().toISOString().split('T')[0],
    }, ...prev]);
    setTradeForm({ type: 'BUY', price: '', shares: '', note: '' });
    setShowTradeInput(false);
  }, [tradeForm, symbol, watchlist]);

  // ── Computed ─────────────────────────────────────────
  const fmtNum = (v) => {
    const abs = Math.abs(v), sign = v >= 0 ? '+' : '-';
    if (abs >= 1000000) return `${sign}${(abs/1000000).toFixed(1)}M`;
    if (abs >= 1000)    return `${sign}${(abs/1000).toFixed(0)}K`;
    return `${sign}${abs}`;
  };

  const displayData = useMemo(() => chartData.length <= 150 ? chartData : chartData.slice(-150), [chartData]);

  const pagedScanResults = useMemo(() => scanResults.slice(scanPage * 20, (scanPage + 1) * 20), [scanResults, scanPage]);

  const tooltipStyle = useMemo(() => ({ contentStyle: { backgroundColor: '#1e293b', borderColor: '#334155', fontSize: '12px' }, itemStyle: { color: '#e2e8f0' }, labelStyle: { color: '#94a3b8' } }), []);

  const marketVerdict = useMemo(() => {
    if (!marketSentiment) return null;
    if (marketSentiment.status === 'BEAR') return { label: '❌ 不建議進場', color: 'text-rose-400', bg: 'bg-rose-950/30 border-rose-500/30', desc: 'VIX飆高／美股走空，現金為王' };
    if (marketSentiment.status === 'BULL') return { label: '✅ 大盤配合',   color: 'text-emerald-400', bg: 'bg-emerald-950/30 border-emerald-500/30', desc: '全球多頭助攻，訊號可正常參考' };
    return { label: '⚠️ 大盤震盪', color: 'text-amber-400', bg: 'bg-amber-950/20 border-amber-500/30', desc: '多空不明，建議輕倉或等待' };
  }, [marketSentiment]);

  const signalReasons = useMemo(() => {
    if (!strategyInfo) return [];
    const c = strategyInfo.checklist;
    return [
      { ok: c.adx_ok,  text: c.adx_ok  ? 'ADX 確認趨勢強度足夠' : 'ADX 趨勢不明，可能盤整' },
      { ok: c.vol_ok,  text: c.vol_ok  ? '量能放大，有資金進場' : '量能不足，缺乏支撐' },
      { ok: c.macd,    text: c.macd    ? 'MACD 黃金交叉，中線偏多' : 'MACD 尚未交叉或走弱' },
      { ok: c.kd,      text: c.kd      ? 'KD 金叉，短線有轉折訊號' : 'KD 尚未金叉' },
      { ok: c.chip_ok, text: c.chip_ok ? '外資／投信買超，籌碼支撐' : '法人未明顯買進', strong: true },
    ];
  }, [strategyInfo]);

  const myStats = useMemo(() => {
    const trades = myTrades.filter(t => t.symbol === symbol);
    if (!trades.length) return null;
    const buys = trades.filter(t => t.type === 'BUY');
    const sells = trades.filter(t => t.type === 'SELL');
    const avgBuy = buys.length ? buys.reduce((s, t) => s + t.price * t.shares, 0) / buys.reduce((s, t) => s + t.shares, 0) : 0;
    const currentPrice = chartData.length ? chartData[chartData.length - 1].close : 0;
    const totalShares = buys.reduce((s, t) => s + t.shares, 0) - sells.reduce((s, t) => s + t.shares, 0);
    const unrealizedPnl = totalShares > 0 ? (currentPrice - avgBuy) * totalShares : 0;
    const unrealizedPct = avgBuy > 0 ? ((currentPrice - avgBuy) / avgBuy * 100) : 0;
    return { trades, buys, sells, avgBuy, totalShares, unrealizedPnl, unrealizedPct, currentPrice };
  }, [myTrades, symbol, chartData]);

  const allPortfolioStats = useMemo(() => {
    const symbolMap = {};
    for (const t of myTrades) {
      if (!symbolMap[t.symbol]) symbolMap[t.symbol] = { symbol: t.symbol, name: t.symbolName, buys: [], sells: [] };
      if (t.type === 'BUY')  symbolMap[t.symbol].buys.push(t);
      if (t.type === 'SELL') symbolMap[t.symbol].sells.push(t);
    }
    return Object.values(symbolMap).map(s => {
      const totalBuyShares = s.buys.reduce((a, t) => a + t.shares, 0);
      const holdShares = totalBuyShares - s.sells.reduce((a, t) => a + t.shares, 0);
      const avgBuy = totalBuyShares > 0 ? s.buys.reduce((a, t) => a + t.price * t.shares, 0) / totalBuyShares : 0;
      const currentPrice = s.symbol === symbol && chartData.length ? chartData[chartData.length - 1].close : null;
      const unrealizedPnl = currentPrice && holdShares > 0 ? (currentPrice - avgBuy) * holdShares : null;
      const unrealizedPct = avgBuy > 0 && unrealizedPnl !== null ? (unrealizedPnl / (avgBuy * holdShares) * 100) : null;
      return { ...s, holdShares, avgBuy, currentPrice, unrealizedPnl, unrealizedPct };
    }).filter(s => s.holdShares > 0);
  }, [myTrades, symbol, chartData]);

  // ── 共用 UI 元件 ─────────────────────────────────────
  const currentStock = watchlist.find(w => w.id === symbol);
  const currentPrice = chartData.length ? chartData[chartData.length - 1].close : null;

  // ═══════════════════════════════════════════════════════
  // RENDER
  // ═══════════════════════════════════════════════════════
  return (
    <div className="flex flex-col h-screen bg-slate-950 text-white font-sans overflow-hidden">

      {/* ── 頂部導航列 ── */}
      <div className="h-14 bg-slate-900 border-b border-slate-700 flex items-center justify-between px-4 flex-shrink-0 z-30">
        <div className="flex items-center gap-6">
          {/* Logo */}
          <div className="flex items-center gap-2 text-blue-400 font-bold text-base">
            <Activity size={18} /> QuantTrader
            <span className="text-xs bg-rose-600 text-white px-1.5 py-0.5 rounded">AI PRO</span>
          </div>

          {/* Tab 切換 */}
          <div className="flex items-center gap-1 bg-slate-800 rounded-lg p-1">
            {[
              { id: 'analysis', icon: <LayoutDashboard size={14}/>, label: '個股分析' },
              { id: 'scanner',  icon: <Radio size={14}/>,          label: '市場掃描' },
              { id: 'portfolio',icon: <PieChart size={14}/>,       label: '交易管理' },
            ].map(tab => (
              <button key={tab.id} onClick={() => setActiveTab(tab.id)}
                className={`flex items-center gap-1.5 px-3 py-1.5 rounded text-sm font-medium transition ${activeTab === tab.id ? 'bg-blue-600 text-white' : 'text-slate-400 hover:text-white'}`}>
                {tab.icon}{tab.label}
              </button>
            ))}
          </div>
        </div>

        {/* 右側：大盤哨兵 + 期間選擇 */}
        <div className="flex items-center gap-4">
          {marketSentiment && (
            <div className={`hidden lg:flex items-center gap-3 px-3 py-1 rounded-lg border text-sm ${marketSentiment.status === 'BULL' ? 'bg-emerald-900/20 border-emerald-500/30' : marketSentiment.status === 'BEAR' ? 'bg-rose-900/20 border-rose-500/30' : 'bg-slate-800 border-slate-700'}`}>
              <Globe size={12} className="text-slate-400"/>
              <span className={marketSentiment.status === 'BULL' ? 'text-emerald-400' : marketSentiment.status === 'BEAR' ? 'text-rose-400' : 'text-slate-400'}>{marketSentiment.desc}</span>
              <span className="text-slate-500 text-xs">VIX {marketSentiment.indicators?.vix}</span>
              <span className={`text-xs ${marketSentiment.indicators?.sp500_bull ? 'text-emerald-400' : 'text-rose-400'}`}>S&P {marketSentiment.indicators?.sp500_bull ? '↑' : '↓'}</span>
            </div>
          )}
          {activeTab === 'analysis' && (
            <div className="flex gap-1">
              {['3mo','6mo','1y'].map(p => (
                <button key={p} onClick={() => setPeriod(p)} className={`px-3 py-1 text-sm rounded font-bold transition ${period === p ? 'bg-blue-600 text-white' : 'text-slate-400 hover:bg-slate-800'}`}>
                  {p === '3mo' ? '3月' : p === '6mo' ? '半年' : '1年'}
                </button>
              ))}
            </div>
          )}
          {/* 本金設定 */}
          <div className="relative">
            <input type="number" value={initialCapital} onChange={e => setInitialCapital(e.target.value)}
              className="w-32 bg-slate-800 border border-slate-600 rounded py-1 pl-5 pr-2 text-sm text-white font-mono focus:border-blue-500 focus:outline-none"/>
            <span className="absolute left-1.5 top-1.5 text-slate-500 text-sm">$</span>
          </div>
        </div>
      </div>

      {/* ── 主內容區 ── */}
      <div className="flex-1 flex overflow-hidden">

        {/* 左側欄：搜尋 + 自選股（所有 Tab 共用） */}
        <div className="w-56 bg-slate-900 border-r border-slate-700 flex flex-col flex-shrink-0">
          {/* 搜尋 */}
          <div className="p-3 border-b border-slate-700">
            <form onSubmit={handleAddStock} className="relative">
              <input type="text" placeholder="搜尋代號" value={newStock} onChange={e => setNewStock(e.target.value)}
                className="w-full bg-slate-800 border border-slate-600 rounded py-1.5 pl-8 pr-2 text-sm text-white focus:border-blue-500 focus:outline-none"/>
              <Search className="absolute left-2 top-2 text-slate-400 w-4 h-4"/>
            </form>
          </div>

          {/* 操作按鈕 */}
          <div className="p-2 border-b border-slate-700 grid grid-cols-2 gap-1.5">
            <button onClick={runScan} disabled={scanning || batchOptimizing}
              className="col-span-2 flex items-center justify-center gap-1 bg-indigo-600 hover:bg-indigo-500 text-white text-sm py-1.5 rounded transition disabled:opacity-50">
              {scanning ? <Loader2 className="animate-spin w-3 h-3"/> : <ScanSearch size={13}/>}
              {scanning ? '掃描中...' : '全台掃描'}
            </button>
            <button onClick={() => setShowSettings(true)}
              className="flex items-center justify-center gap-1 bg-slate-800 border border-slate-600 hover:bg-slate-700 text-slate-300 text-sm py-1.5 rounded transition">
              <Sliders size={12}/> 參數
            </button>
            <button onClick={runOptimization} disabled={optimizing || batchOptimizing}
              className={`flex items-center justify-center gap-1 text-sm py-1.5 rounded transition border disabled:opacity-50 ${gaResult ? 'bg-amber-500/10 text-amber-400 border-amber-500/50' : 'bg-slate-800 border-slate-600 text-slate-300 hover:bg-slate-700'}`}>
              {optimizing ? <Loader2 className="animate-spin w-3 h-3"/> : <Cpu size={12}/>}
              {optimizing ? '優化中' : 'AI優化'}
            </button>
            <button onClick={runBatchOptimization} disabled={batchOptimizing || optimizing}
              className="flex items-center justify-center gap-1 col-span-2 bg-slate-700 hover:bg-slate-600 text-emerald-300 border border-slate-600 text-sm py-1.5 rounded transition disabled:opacity-50">
              {batchOptimizing ? <Loader2 className="animate-spin w-3 h-3"/> : <BrainCircuit size={12}/>}
              {batchOptimizing ? `優化中 ${batchProgress.currentStock}` : '全批次 AI 優化'}
            </button>
            {scanResults.length > 0 && !scanning && (
              <button onClick={() => setActiveTab('scanner')}
                className="col-span-2 flex items-center justify-center gap-1 bg-indigo-900/40 border border-indigo-500/30 hover:bg-indigo-800/50 text-indigo-300 text-sm py-1 rounded transition">
                <BarChart3 size={12}/> 上次結果（{scanResults.length}）
              </button>
            )}
          </div>

          {/* 自選股清單 */}
          <div className="flex-1 overflow-y-auto">
            {watchlist.map(s => (
              <div key={s.id} onClick={() => { setSymbol(s.id); if (activeTab !== 'portfolio') setActiveTab('analysis'); }}
                className={`p-2.5 border-b border-slate-800 cursor-pointer hover:bg-slate-800 transition flex justify-between items-center ${symbol === s.id ? 'bg-slate-800 border-l-2 border-l-blue-500' : ''}`}>
                <div>
                  <div className="font-bold text-slate-200 text-sm">{s.name}</div>
                  <div className="text-xs text-slate-500">{s.displayId}</div>
                </div>
                <div className="flex items-center gap-1">
                  {stockSettingsCache[s.id] && <span className="text-xs text-amber-500 font-bold">AI</span>}
                  <button onClick={e => { e.stopPropagation(); setWatchlist(watchlist.filter(w => w.id !== s.id)); }}
                    className="text-slate-600 hover:text-rose-500 p-1"><Trash2 size={12}/></button>
                </div>
              </div>
            ))}
          </div>

          {/* 批次優化進度 */}
          {batchOptimizing && (
            <div className="p-2 bg-indigo-900/20 border-t border-indigo-500/30">
              <div className="flex justify-between text-xs text-indigo-400 mb-1">
                <span>{batchProgress.currentStock}</span>
                <span>{Math.round(batchProgress.current / batchProgress.total * 100)}%</span>
              </div>
              <div className="w-full bg-slate-800 h-1 rounded-full overflow-hidden">
                <div className="bg-indigo-500 h-full transition-all" style={{ width: `${batchProgress.current / batchProgress.total * 100}%` }}/>
              </div>
            </div>
          )}
        </div>

        {/* ── TAB 內容 ── */}

        {/* ════ TAB 1：個股分析 ════ */}
        {activeTab === 'analysis' && (
          <div className="flex-1 flex overflow-hidden">

            {/* 中間：圖表區 */}
            <div className="flex-1 flex flex-col p-2 gap-1.5 overflow-hidden relative min-w-0">
              {loading && (
                <div className="absolute inset-0 flex items-center justify-center bg-slate-950/80 z-10">
                  <Loader2 className="w-8 h-8 text-blue-500 animate-spin"/>
                </div>
              )}

              {/* 股票標題列 */}
              <div className="flex items-center justify-between px-2 flex-shrink-0">
                <div className="flex items-center gap-3">
                  <h2 className="text-lg font-bold">{currentStock?.name}</h2>
                  <span className={`text-sm px-2 py-0.5 rounded border flex items-center gap-1 ${activeParams.strategy_type === 'trend' ? 'bg-emerald-900/30 border-emerald-500/30 text-emerald-400' : 'bg-slate-800 border-slate-700 text-slate-300'}`}>
                    {activeParams.strategy_type === 'trend' ? <TrendingUp size={11}/> : <Zap size={11}/>}
                    {activeParams.strategy_type === 'trend' ? '趨勢' : '波段'}
                  </span>
                  {currentPrice && <span className="text-xl font-mono font-bold text-slate-200">{currentPrice.toFixed(2)}</span>}
                </div>

                {/* AI 預測 Popover 按鈕 */}
                <div className="relative">
                  <button onClick={() => setShowAiPopover(v => !v)}
                    className="flex items-center gap-1.5 bg-emerald-700 hover:bg-emerald-600 text-white text-sm px-3 py-1.5 rounded transition">
                    <BrainCircuit size={14}/> GPU 預測
                    {aiPrediction && <span className="w-2 h-2 bg-yellow-400 rounded-full"/>}
                  </button>
                  {showAiPopover && (
                    <div className="absolute right-0 top-10 z-50 w-72 bg-slate-900 border border-slate-700 rounded-xl shadow-2xl p-4">
                      <div className="flex justify-between items-center mb-3">
                        <span className="text-sm font-bold text-slate-300 flex items-center gap-1"><Cpu size={13}/> AI 深度學習</span>
                        <button onClick={() => setShowAiPopover(false)} className="text-slate-500 hover:text-white"><X size={14}/></button>
                      </div>
                      {!aiPrediction ? (
                        <button onClick={runAiPrediction} disabled={aiLoading}
                          className="w-full bg-emerald-600 hover:bg-emerald-500 text-white py-2.5 rounded-lg text-sm font-bold transition flex items-center justify-center gap-2">
                          {aiLoading ? <Loader2 className="animate-spin" size={14}/> : <Zap size={14} className="text-yellow-300"/>}
                          {aiLoading ? '運算中...' : '啟動 GPU 預測'}
                        </button>
                      ) : (
                        <div>
                          <div className="flex justify-between items-center mb-3 pb-2 border-b border-slate-800">
                            <span className="text-xs text-indigo-400">{aiPrediction.model_type}</span>
                            <button onClick={runAiPrediction} className="text-slate-500 hover:text-white"><RefreshCcw size={12}/></button>
                          </div>
                          <div className="grid grid-cols-3 gap-1.5 mb-3">
                            {aiPrediction.predicted?.map((price, i) => (
                              <div key={i} className="text-center bg-slate-800 rounded p-1.5">
                                <div className="text-xs text-slate-500">T+{i+1}</div>
                                <div className={`text-sm font-mono font-bold ${price > aiPrediction.current ? 'text-rose-400' : 'text-emerald-400'}`}>${price}</div>
                              </div>
                            ))}
                          </div>
                          <div className="flex justify-between text-xs text-slate-400 mb-2">
                            <span>現價: ${aiPrediction.current}</span>
                            <span className={aiPrediction.change_pct >= 0 ? 'text-rose-400 font-bold' : 'text-emerald-400 font-bold'}>
                              均幅 {aiPrediction.change_pct > 0 ? '+' : ''}{aiPrediction.change_pct}%
                            </span>
                          </div>
                          <div className="h-1.5 w-full bg-slate-800 rounded-full overflow-hidden">
                            <div className={`h-full ${aiPrediction.trend === 'BULL' ? 'bg-rose-500' : 'bg-emerald-500'}`} style={{ width: `${aiPrediction.confidence}%` }}/>
                          </div>
                          <div className="text-xs text-right text-slate-500 mt-1">信心度 {aiPrediction.confidence}%</div>
                        </div>
                      )}
                    </div>
                  )}
                </div>
              </div>

              {chartData.length > 0 ? (
                <>
                  {/* 主圖：K線（70% 高度） */}
                  <div className="flex-[7] bg-slate-900/30 rounded-lg border border-slate-800 p-1 min-h-0">
                    <ResponsiveContainer width="100%" height="100%">
                      <ComposedChart data={displayData} margin={{ top: 4, right: 4, left: 0, bottom: 0 }}>
                        <CartesianGrid strokeDasharray="3 3" stroke="#334155" vertical={false} opacity={0.2}/>
                        <XAxis dataKey="time" hide/>
                        <YAxis domain={['auto','auto']} orientation="right" stroke="#64748b" tick={{ fontSize: 11 }} tickLine={false} axisLine={false}/>
                        <Tooltip content={<CustomTooltip/>} cursor={{ stroke: '#64748b', strokeWidth: 1, strokeDasharray: '5 5' }}/>
                        <Line type="monotone" dataKey="ma5"  stroke="#f59e0b" strokeWidth={1}   dot={false} name="MA5"/>
                        <Line type="monotone" dataKey="ma20" stroke="#3b82f6" strokeWidth={1.5} dot={false} name="MA20"/>
                        <Area type="monotone" dataKey="bb_up"  stroke="none" fill="#3b82f6" fillOpacity={0.05}/>
                        <Area type="monotone" dataKey="bb_low" stroke="none" fill="#3b82f6" fillOpacity={0.05}/>
                        <Line dataKey="close" stroke="none" dot={<SignalDot/>} activeDot={false} legendType="none" name="訊號"/>
                        <Bar dataKey={d => [d.low, d.high]} name="股價" isAnimationActive={false}
                          shape={props => <Candlestick {...props} low={props.payload.low} high={props.payload.high} open={props.payload.open} close={props.payload.close}/>}/>
                      </ComposedChart>
                    </ResponsiveContainer>
                  </div>

                  {/* 副圖切換列 */}
                  <div className="flex items-center gap-2 flex-shrink-0 px-1">
                    {[
                      { id: 'macd',   label: 'MACD' },
                      { id: 'kd',     label: 'KD' },
                      { id: 'equity', label: '資金曲線' },
                    ].map(s => (
                      <button key={s.id} onClick={() => setSubChart(s.id)}
                        className={`text-xs px-3 py-1 rounded font-bold transition ${subChart === s.id ? 'bg-blue-600 text-white' : 'bg-slate-800 text-slate-500 hover:text-slate-300'}`}>
                        {s.label}
                      </button>
                    ))}
                  </div>

                  {/* 副圖（30% 高度） */}
                  <div className="flex-[3] bg-slate-900/30 rounded-lg border border-slate-800 p-1 relative min-h-0">
                    <div className="absolute top-1 left-2 text-xs text-slate-500 font-bold z-10">
                      {subChart === 'macd' ? 'MACD' : subChart === 'kd' ? 'KD' : '資金曲線'}
                    </div>

                    {subChart === 'macd' && (
                      <ResponsiveContainer width="100%" height="100%">
                        <ComposedChart data={displayData}>
                          <CartesianGrid strokeDasharray="3 3" stroke="#334155" vertical={false} opacity={0.2}/>
                          <XAxis dataKey="time" hide/>
                          <YAxis orientation="right" stroke="#64748b" tick={{ fontSize: 10 }} tickLine={false} axisLine={false}/>
                          <Tooltip {...tooltipStyle}/>
                          <Bar dataKey="macd_osc" name="MACD柱" isAnimationActive={false}>
                            {displayData.map((entry, index) => <Cell key={index} fill={entry.macd_osc >= 0 ? '#ef4444' : '#22c55e'}/>)}
                          </Bar>
                          <Line type="monotone" dataKey="macd_dif" stroke="#3b82f6" dot={false} strokeWidth={1} name="DIF"/>
                          <Line type="monotone" dataKey="macd_dea" stroke="#f59e0b" dot={false} strokeWidth={1} name="DEA"/>
                        </ComposedChart>
                      </ResponsiveContainer>
                    )}

                    {subChart === 'kd' && (
                      <ResponsiveContainer width="100%" height="100%">
                        <ComposedChart data={displayData}>
                          <CartesianGrid strokeDasharray="3 3" stroke="#334155" vertical={false} opacity={0.2}/>
                          <XAxis dataKey="time" stroke="#64748b" tick={{ fontSize: 10 }} tickLine={false} axisLine={false}/>
                          <YAxis domain={[0,100]} ticks={[20,80]} orientation="right" stroke="#64748b" tick={{ fontSize: 10 }} tickLine={false} axisLine={false}/>
                          <Tooltip {...tooltipStyle}/>
                          <ReferenceLine y={80} stroke="#64748b" strokeDasharray="3 3"/>
                          <ReferenceLine y={20} stroke="#64748b" strokeDasharray="3 3"/>
                          <Line type="monotone" dataKey="k" stroke="#f59e0b" dot={false} strokeWidth={1} name="K"/>
                          <Line type="monotone" dataKey="d" stroke="#3b82f6" dot={false} strokeWidth={1} name="D"/>
                        </ComposedChart>
                      </ResponsiveContainer>
                    )}

                    {subChart === 'equity' && (
                      <ResponsiveContainer width="100%" height="100%">
                        <LineChart data={displayData}>
                          <CartesianGrid strokeDasharray="3 3" stroke="#334155" vertical={false} opacity={0.2}/>
                          <XAxis dataKey="time" stroke="#64748b" tick={{ fontSize: 10 }} tickLine={false} axisLine={false}/>
                          <YAxis orientation="right" stroke="#64748b" tick={{ fontSize: 10 }} tickLine={false} axisLine={false}/>
                          <Tooltip {...tooltipStyle}/>
                          <Legend wrapperStyle={{ fontSize: '11px' }}/>
                          <Line type="monotone" dataKey="equity"    stroke="#22c55e" strokeWidth={2} dot={false} name="本策略"/>
                          <Line type="monotone" dataKey="bh_equity" stroke="#64748b" strokeWidth={1} strokeDasharray="5 5" dot={false} name="買進持有"/>
                        </LineChart>
                      </ResponsiveContainer>
                    )}
                  </div>
                </>
              ) : (
                <div className="flex-1 flex items-center justify-center text-slate-500">暫無資料</div>
              )}
            </div>

            {/* 右側：決策面板 */}
            {strategyInfo && (
              <div className="w-80 bg-slate-900 border-l border-slate-700 flex flex-col overflow-y-auto flex-shrink-0">

                {/* A. 現在該怎麼做 */}
                <div className="p-3 border-b border-slate-800">
                  <div className="text-sm text-slate-400 font-bold mb-2 uppercase tracking-wider">現在該怎麼做？</div>
                  {marketVerdict && (
                    <div className={`p-2.5 rounded-lg border mb-2 ${marketVerdict.bg}`}>
                      <div className={`text-sm font-bold ${marketVerdict.color}`}>{marketVerdict.label}</div>
                      <p className="text-xs text-slate-400 mt-0.5 leading-snug">{marketVerdict.desc}</p>
                    </div>
                  )}
                  <div className={`p-3 rounded-xl border ${strategyInfo.suggestion_color === 'red' ? 'bg-rose-500/10 border-rose-500/30' : strategyInfo.suggestion_color === 'green' ? 'bg-emerald-500/10 border-emerald-500/30' : 'bg-slate-800 border-slate-700'}`}>
                    <div className={`text-xl font-bold ${strategyInfo.suggestion_color === 'red' ? 'text-rose-400' : strategyInfo.suggestion_color === 'green' ? 'text-emerald-400' : 'text-slate-400'}`}>
                      {marketSentiment?.status === 'BEAR' ? '⚠️ 觀望為主' : strategyInfo.suggestion}
                    </div>
                    {marketSentiment?.status === 'BEAR' && strategyInfo.suggestion_color === 'red' && (
                      <p className="text-xs text-slate-500 mt-1">策略顯示買進，但大盤空頭期間訊號可靠性下降</p>
                    )}
                  </div>
                </div>

                {/* B. 訊號理由 */}
                <div className="p-3 border-b border-slate-800">
                  <div className="text-sm text-slate-400 font-bold mb-2 uppercase tracking-wider">訊號理由</div>
                  <div className="space-y-1">
                    {signalReasons.map((r, i) => (
                      <div key={i} className={`flex items-start gap-2 text-sm px-2 py-1.5 rounded ${r.ok ? (r.strong ? 'bg-purple-500/10 text-purple-300' : 'text-emerald-300') : 'text-slate-600'}`}>
                        <span className="shrink-0">{r.ok ? (r.strong ? '🟣' : '🟢') : '⚪'}</span>
                        <span className={r.strong ? 'font-bold' : ''}>{r.text}</span>
                      </div>
                    ))}
                  </div>
                  <div className="mt-1.5 text-sm text-slate-500">
                    通過 {signalReasons.filter(r => r.ok).length}/{signalReasons.length} 項
                    {signalReasons.filter(r => r.ok).length >= 4 ? <span className="text-emerald-500 ml-1">— 較可信</span>
                      : signalReasons.filter(r => r.ok).length <= 2 ? <span className="text-rose-500 ml-1">— 條件不足</span>
                      : <span className="text-amber-500 ml-1">— 可觀望</span>}
                  </div>
                </div>

                {/* C. 籌碼面 */}
                {strategyInfo.checklist.chip_detail && (() => {
                  const cd = strategyInfo.checklist.chip_detail;
                  const fmt = fmtNum;
                  const fc = (v) => v > 0 ? 'text-rose-400' : v < 0 ? 'text-emerald-400' : 'text-slate-500';
                  return (
                    <div className="p-3 border-b border-slate-800">
                      <div className="text-sm text-slate-400 font-bold mb-2 uppercase tracking-wider">🏦 籌碼面</div>
                      <div className="bg-slate-950 rounded-lg border border-slate-800 divide-y divide-slate-800">
                        <div className="p-2">
                          <div className="flex justify-between items-center">
                            <span className="text-sm font-bold text-slate-200">外資</span>
                            <span className={`font-mono font-bold text-base ${fc(cd.foreign_today)}`}>{fmt(cd.foreign_today)}</span>
                          </div>
                          <div className="flex justify-between text-sm text-slate-400 mt-0.5">
                            <span>近5日 <span className={`font-mono font-bold ${fc(cd.foreign_5d)}`}>{fmt(cd.foreign_5d)}</span></span>
                            {cd.foreign_streak >= 3 ? <span className="text-purple-400 font-bold">連買{cd.foreign_streak}天🔥</span>
                              : cd.foreign_streak > 0 ? <span className="text-slate-400">連買{cd.foreign_streak}天</span>
                              : <span className="text-slate-600">賣超中</span>}
                          </div>
                        </div>
                        <div className="p-2">
                          <div className="flex justify-between items-center">
                            <span className="text-sm font-bold text-slate-200">投信</span>
                            <span className={`font-mono font-bold text-base ${fc(cd.trust_today)}`}>{fmt(cd.trust_today)}</span>
                          </div>
                          <div className="flex justify-between text-sm text-slate-400 mt-0.5">
                            <span>近5日 <span className={`font-mono font-bold ${fc(cd.trust_5d)}`}>{fmt(cd.trust_5d)}</span></span>
                            {cd.trust_streak >= 3 ? <span className="text-purple-400 font-bold">連買{cd.trust_streak}天🔥</span>
                              : cd.trust_streak > 0 ? <span className="text-slate-400">連買{cd.trust_streak}天</span> : null}
                          </div>
                        </div>
                        <div className="p-2 flex justify-between text-sm">
                          <span className="text-slate-400">三大法人近5日</span>
                          <span className={`font-mono font-bold ${fc(cd.inst_5d)}`}>{fmt(cd.inst_5d)}</span>
                        </div>
                      </div>
                      {cd.foreign_5d > 0 && cd.trust_5d > 0 && (
                        <div className="mt-2 bg-purple-500/10 border border-purple-500/30 rounded px-2 py-1.5 text-xs text-purple-300 font-bold">🟣 外資＋投信同步買超</div>
                      )}
                      {cd.foreign_5d < 0 && cd.trust_5d < 0 && (
                        <div className="mt-2 bg-slate-800 border border-slate-700 rounded px-2 py-1.5 text-xs text-slate-500">⚠️ 外資＋投信同步賣超，謹慎</div>
                      )}

                      {/* 融資面（有實際資料才顯示）*/}
                      {cd.margin_bal >= 0 && (
                        <div className="mt-2 bg-slate-950 rounded-lg border border-slate-800 p-2">
                          <div className="flex justify-between items-center mb-1.5">
                            <span className="text-xs font-bold text-slate-300">💳 融資水位</span>
                            <span className={`text-xs font-mono font-bold ${cd.margin_level_pct < 50 ? 'text-emerald-400' : cd.margin_level_pct > 80 ? 'text-rose-400' : 'text-amber-400'}`}>
                              {cd.margin_level_pct}%
                            </span>
                          </div>
                          {/* 水位進度條 */}
                          <div className="w-full bg-slate-800 h-1.5 rounded-full overflow-hidden mb-1.5">
                            <div className={`h-full rounded-full transition-all ${cd.margin_level_pct < 50 ? 'bg-emerald-500' : cd.margin_level_pct > 80 ? 'bg-rose-500' : 'bg-amber-500'}`}
                              style={{ width: `${cd.margin_level_pct}%` }}/>
                          </div>
                          <div className="flex justify-between text-xs text-slate-500">
                            <span>近5日增減 <span className={`font-mono font-bold ${cd.margin_diff_5d < 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
                              {cd.margin_diff_5d > 0 ? '+' : ''}{cd.margin_diff_5d?.toLocaleString()}
                            </span></span>
                            {cd.margin_shrink_days >= 3
                              ? <span className="text-emerald-400 font-bold">連減{cd.margin_shrink_days}天 ✨</span>
                              : cd.margin_shrink_days > 0
                              ? <span className="text-slate-400">連減{cd.margin_shrink_days}天</span>
                              : null}
                          </div>
                          {/* S 級訊號提示 */}
                          {cd.margin_shrink_days >= 3 && cd.inst_5d > 0 && (
                            <div className="mt-1.5 bg-yellow-500/10 border border-yellow-500/30 rounded px-2 py-1 text-xs text-yellow-300 font-bold">
                              💎 法人吃貨＋散戶踩踏，S級籌碼結構
                            </div>
                          )}
                        </div>
                      )}
                    </div>
                  );
                })()}

                {/* D. 停損支撐 */}
                <div className="p-3 border-b border-slate-800">
                  <div className="text-sm text-slate-400 font-bold mb-2 uppercase tracking-wider flex items-center gap-1"><ShieldAlert size={12}/> 停損 / 支撐壓力</div>
                  {currentPrice > 0 && strategyInfo.forecast.support > 0 && currentPrice < strategyInfo.forecast.support && (
                    <div className="flex items-start gap-2 bg-rose-600/20 border border-rose-500/60 p-2.5 rounded-lg mb-2 animate-pulse">
                      <AlertTriangle size={15} className="text-rose-400 shrink-0 mt-0.5"/>
                      <div>
                        <div className="text-rose-300 font-bold text-sm">⚠️ 已跌破支撐！</div>
                        <div className="text-rose-400/80 text-xs mt-0.5">現價 ${currentPrice?.toFixed(2)} 低於支撐 ${strategyInfo.forecast.support}</div>
                      </div>
                    </div>
                  )}
                  <div className="grid grid-cols-2 gap-2 mb-2">
                    <div className={`bg-slate-950 p-2 rounded border text-center ${currentPrice && currentPrice < strategyInfo.forecast.support ? 'border-rose-500/50' : 'border-slate-800'}`}>
                      <div className="text-sm text-slate-400 mb-1">支撐</div>
                      <div className={`font-mono font-bold ${currentPrice && currentPrice < strategyInfo.forecast.support ? 'text-rose-400' : 'text-emerald-400'}`}>${strategyInfo.forecast.support}</div>
                    </div>
                    <div className="bg-slate-950 p-2 rounded border border-slate-800 text-center">
                      <div className="text-sm text-slate-400 mb-1">壓力</div>
                      <div className="font-mono text-rose-400 font-bold">${strategyInfo.forecast.pressure}</div>
                    </div>
                  </div>
                  {strategyInfo.forecast.stop_loss > 0 && (
                    <div className="flex items-center gap-2 bg-rose-500/10 border border-rose-500/20 p-2 rounded text-rose-300 text-xs">
                      <ShieldAlert size={12}/>
                      <div>
                        <span className="font-bold">停損 ${strategyInfo.forecast.stop_loss}</span>
                        {currentPrice > 0 && (
                          <span className="text-rose-400/70 ml-1">
                            ({((strategyInfo.forecast.stop_loss - currentPrice) / currentPrice * 100).toFixed(1)}%)
                          </span>
                        )}
                        <div className="text-rose-400/50 text-xs mt-0.5">破此價位建議無條件出場</div>
                      </div>
                    </div>
                  )}
                </div>

                {/* E. 近期新聞 */}
                {newsSentiment && newsSentiment.news.length > 0 && (
                  <div className="p-3 border-b border-slate-800">
                    <div className="text-sm text-slate-400 font-bold mb-2 uppercase tracking-wider flex items-center gap-1">
                      <Newspaper size={12}/> 近期新聞
                      <span className={`ml-auto px-1.5 py-0.5 rounded text-xs font-bold ${newsSentiment.sentiment_score >= 2 ? 'bg-emerald-500/20 text-emerald-400' : newsSentiment.sentiment_score <= -2 ? 'bg-rose-500/20 text-rose-400' : 'bg-slate-700 text-slate-400'}`}>
                        {newsSentiment.summary}
                      </span>
                    </div>
                    <div className="space-y-1.5">
                      {newsSentiment.news.slice(0, 3).map((n, i) => (
                        <a key={i} href={n.link} target="_blank" rel="noopener noreferrer"
                          className="block hover:bg-slate-800 p-1.5 rounded transition">
                          <div className="flex justify-between mb-0.5">
                            <span className={`px-1 rounded text-xs ${n.sentiment === 'positive' ? 'bg-emerald-500/20 text-emerald-400' : n.sentiment === 'negative' ? 'bg-rose-500/20 text-rose-400' : 'bg-slate-700 text-slate-400'}`}>
                              {n.sentiment === 'positive' ? '利多' : n.sentiment === 'negative' ? '利空' : '中立'}
                            </span>
                            <span className="text-slate-500 text-sm">{n.time}</span>
                          </div>
                          <div className={`text-sm line-clamp-2 leading-snug ${n.relevant === false ? "text-slate-500" : "text-slate-200"}`}>{n.title}{n.relevant === false && <span className="text-xs text-slate-600 ml-1">（相關性待確認）</span>}</div>
                        </a>
                      ))}
                    </div>
                  </div>
                )}

                {/* F. 回測績效 */}
                <div className="p-3">
                  <div className="text-sm text-slate-400 font-bold mb-1 uppercase tracking-wider">回測績效（歷史模擬）</div>
                  <p className="text-sm text-slate-500 mb-2">⚠️ 以下為同段資料調參後回測，實際通常更差</p>
                  <div className="space-y-1">
                    {[
                      { label: '策略報酬', value: `${strategyInfo.performance.total_return > 0 ? '+' : ''}${strategyInfo.performance.total_return}%`, color: strategyInfo.performance.total_return >= 0 ? 'text-rose-400' : 'text-emerald-400' },
                      { label: '買進持有', value: `${strategyInfo.performance.buy_hold_return}%`,   color: strategyInfo.performance.buy_hold_return >= 0 ? 'text-rose-400' : 'text-emerald-400' },
                      { label: 'Sharpe',   value: strategyInfo.performance.sharpe.toFixed(2), color: 'text-blue-400' },
                    ].map(r => (
                      <div key={r.label} className="flex justify-between text-sm">
                        <span className="text-slate-500">{r.label}</span>
                        <span className={`font-mono font-bold ${r.color}`}>{r.value}</span>
                      </div>
                    ))}
                  </div>
                  {strategyInfo.performance.total_return < strategyInfo.performance.buy_hold_return && (
                    <p className="text-xs text-amber-600 mt-2">⚠️ 跑輸買進持有，直接買 0050 更好</p>
                  )}
                </div>

              </div>
            )}
          </div>
        )}

        {/* ════ TAB 2：市場掃描 ════ */}
        {activeTab === 'scanner' && (
          <div className="flex-1 flex flex-col p-4 overflow-hidden">
            <div className="flex items-center justify-between mb-4">
              <h2 className="text-xl font-bold flex items-center gap-2 text-indigo-400"><ScanSearch size={20}/> 全市場強勢股掃描</h2>
              <button onClick={runScan} disabled={scanning}
                className="flex items-center gap-2 bg-indigo-600 hover:bg-indigo-500 text-white px-4 py-2 rounded-lg text-sm font-bold transition disabled:opacity-50">
                {scanning ? <Loader2 className="animate-spin" size={14}/> : <ScanSearch size={14}/>}
                {scanning ? '掃描中...' : '重新掃描'}
              </button>
            </div>

            {/* 大盤哨兵 */}
            {marketSentiment && (
              <div className={`p-4 rounded-xl border mb-4 ${marketSentiment.status === 'BULL' ? 'bg-emerald-900/20 border-emerald-500/30' : marketSentiment.status === 'BEAR' ? 'bg-rose-900/20 border-rose-500/30' : 'bg-slate-800 border-slate-700'}`}>
                <div className="flex items-center justify-between">
                  <div>
                    <div className="text-xs text-slate-500 mb-1 flex items-center gap-1"><Globe size={11}/> WORLD MOOD</div>
                    <div className={`text-lg font-bold ${marketSentiment.status === 'BULL' ? 'text-emerald-400' : marketSentiment.status === 'BEAR' ? 'text-rose-400' : 'text-slate-400'}`}>{marketSentiment.desc}</div>
                  </div>
                  <div className="flex gap-6 text-sm">
                    <div><div className="text-xs text-slate-500">S&P 500</div><div className={`font-mono font-bold ${marketSentiment.indicators?.sp500_bull ? 'text-emerald-400' : 'text-rose-400'}`}>{marketSentiment.indicators?.sp500_price} {marketSentiment.indicators?.sp500_bull ? '↑' : '↓'}</div></div>
                    <div><div className="text-xs text-slate-500">VIX 恐慌</div><div className={`font-mono font-bold ${marketSentiment.indicators?.vix > 20 ? 'text-rose-400' : 'text-emerald-400'}`}>{marketSentiment.indicators?.vix}</div></div>
                    <div><div className="text-xs text-slate-500">台股加權</div><div className={`font-mono font-bold ${marketSentiment.indicators?.twii_bull ? 'text-emerald-400' : 'text-rose-400'}`}>{marketSentiment.indicators?.twii_bull ? '多頭' : '空頭'}</div></div>
                  </div>
                </div>
              </div>
            )}

            {scanning ? (
              <div className="flex-1 flex flex-col items-center justify-center gap-4 text-slate-500">
                <Loader2 className="w-12 h-12 animate-spin text-indigo-500"/>
                <p className="text-slate-300">AI 正在掃描全台股 1800+ 檔股票...</p>
                {scanProgress.total > 0 && (
                  <div className="w-80">
                    <div className="flex justify-between text-xs text-slate-400 mb-1">
                      <span>掃描進度</span><span>{scanProgress.current} / {scanProgress.total} 檔</span>
                    </div>
                    <div className="w-full bg-slate-800 h-2 rounded-full overflow-hidden">
                      <div className="bg-indigo-500 h-full transition-all duration-500" style={{ width: `${Math.round(scanProgress.current / scanProgress.total * 100)}%` }}/>
                    </div>
                    <p className="text-xs text-slate-600 mt-1 text-center">掃描期間可切換到其他分頁查看個股</p>
                  </div>
                )}
              </div>
            ) : (
              <div className="flex-1 flex flex-col overflow-hidden bg-slate-900 border border-slate-800 rounded-xl">
                <div className="flex items-center justify-between px-4 py-2 bg-slate-800 border-b border-slate-700 flex-shrink-0">
                  <span className="text-sm text-slate-400">共 <span className="text-white font-bold">{scanResults.length}</span> 檔通過篩選，顯示 {scanPage*20+1}–{Math.min((scanPage+1)*20, scanResults.length)}</span>
                  <div className="flex gap-2">
                    <button onClick={() => setScanPage(p => Math.max(0, p-1))} disabled={scanPage === 0} className="text-xs px-3 py-1 rounded bg-slate-700 hover:bg-slate-600 disabled:opacity-30">← 上頁</button>
                    <button onClick={() => setScanPage(p => p+1)} disabled={(scanPage+1)*20 >= scanResults.length} className="text-xs px-3 py-1 rounded bg-slate-700 hover:bg-slate-600 disabled:opacity-30">下頁 →</button>
                  </div>
                </div>
                <div className="flex-1 overflow-y-auto">
                  <table className="w-full text-sm text-left">
                    <thead className="bg-slate-800 text-slate-400 text-xs uppercase sticky top-0">
                      <tr><th className="px-4 py-3">代號</th><th className="px-4 py-3">現價</th><th className="px-4 py-3">RSI</th><th className="px-4 py-3">量能</th><th className="px-4 py-3">模式</th><th className="px-4 py-3">操作</th></tr>
                    </thead>
                    <tbody className="divide-y divide-slate-800">
                      {pagedScanResults.map(stock => (
                        <tr key={stock.id} className="hover:bg-slate-800/50">
                          <td className="px-4 py-3"><div className="font-bold text-slate-200">{stock.name || stock.id}</div><div className="text-xs text-blue-300 font-mono">{stock.id.split('.')[0]}</div></td>
                          <td className="px-4 py-3 font-mono">${stock.price}</td>
                          <td className={`px-4 py-3 font-bold ${stock.rsi > 70 ? 'text-rose-400' : 'text-slate-300'}`}>{stock.rsi}</td>
                          <td className="px-4 py-3 text-amber-400">{stock.vol_ratio}x</td>
                          <td className="px-4 py-3">
                            <span className={`text-xs px-2 py-1 rounded font-bold border flex items-center gap-1 w-fit ${stock.suggestion.includes('趨勢') ? 'bg-emerald-500/20 text-emerald-400 border-emerald-500/30' : 'bg-indigo-500/20 text-indigo-400 border-indigo-500/30'}`}>
                              {stock.suggestion.includes('趨勢') ? <TrendingUp size={10}/> : <Zap size={10}/>}{stock.suggestion}
                            </span>
                          </td>
                          <td className="px-4 py-3">
                            <button onClick={() => { if (!watchlist.some(w => w.id === stock.id)) setWatchlist([...watchlist, { id: stock.id, displayId: stock.id.split('.')[0], name: stock.name || stock.id }]); setSymbol(stock.id); setActiveTab('analysis'); }}
                              className="text-xs bg-blue-600 hover:bg-blue-500 text-white px-3 py-1 rounded">查看</button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                  {scanResults.length === 0 && <div className="p-10 text-center text-slate-500">沒有發現符合條件的股票</div>}
                </div>
              </div>
            )}
          </div>
        )}

        {/* ════ TAB 3：交易管理 ════ */}
        {activeTab === 'portfolio' && (
          <div className="flex-1 flex gap-4 p-4 overflow-hidden">

            {/* 左：持股總覽 */}
            <div className="w-80 flex flex-col gap-4 flex-shrink-0">
              <div className="bg-slate-900 border border-slate-700 rounded-xl overflow-hidden flex flex-col">
                <div className="px-4 py-3 bg-slate-800 border-b border-slate-700">
                  <h3 className="font-bold text-slate-200 flex items-center gap-2"><DollarSign size={14}/> 持股損益總覽</h3>
                </div>
                <div className="flex-1 overflow-y-auto divide-y divide-slate-800">
                  {allPortfolioStats.length > 0 ? allPortfolioStats.map(s => (
                    <div key={s.symbol} onClick={() => { setSymbol(s.symbol); setActiveTab('analysis'); }}
                      className="px-4 py-3 hover:bg-slate-800 cursor-pointer transition">
                      <div className="flex justify-between items-start">
                        <div>
                          <div className="font-bold text-slate-200 text-sm">{s.name}</div>
                          <div className="text-xs text-slate-500">{s.symbol.split('.')[0]} · {s.holdShares.toLocaleString()} 股 · 均 ${s.avgBuy.toFixed(1)}</div>
                        </div>
                        <div className="text-right">
                          {s.unrealizedPnl !== null ? (
                            <>
                              <div className={`font-mono font-bold text-sm ${s.unrealizedPnl >= 0 ? 'text-rose-400' : 'text-emerald-400'}`}>
                                {s.unrealizedPnl >= 0 ? '+' : ''}{Math.round(s.unrealizedPnl).toLocaleString()}
                              </div>
                              <div className={`text-xs ${s.unrealizedPct >= 0 ? 'text-rose-400/70' : 'text-emerald-400/70'}`}>
                                {s.unrealizedPct >= 0 ? '+' : ''}{s.unrealizedPct.toFixed(1)}%
                              </div>
                            </>
                          ) : <div className="text-slate-600 text-xs">點入查看</div>}
                        </div>
                      </div>
                    </div>
                  )) : (
                    <div className="p-8 text-center text-slate-600 text-sm">還沒有交易記錄</div>
                  )}
                </div>
                {/* 合計 */}
                {allPortfolioStats.some(s => s.unrealizedPnl !== null) && (() => {
                  const total = allPortfolioStats.reduce((sum, s) => sum + (s.unrealizedPnl || 0), 0);
                  return (
                    <div className="px-4 py-3 border-t border-slate-700 flex justify-between items-center bg-slate-900">
                      <span className="text-sm text-slate-500">未實現損益合計</span>
                      <span className={`font-mono font-bold text-base ${total >= 0 ? 'text-rose-400' : 'text-emerald-400'}`}>
                        {total >= 0 ? '+' : ''}{Math.round(total).toLocaleString()}
                      </span>
                    </div>
                  );
                })()}
              </div>
            </div>

            {/* 中：當前股票交易記錄 */}
            <div className="flex-1 flex flex-col gap-4 min-w-0 overflow-hidden">
              <div className="bg-slate-900 border border-slate-700 rounded-xl flex flex-col overflow-hidden flex-1">
                <div className="px-4 py-3 bg-slate-800 border-b border-slate-700 flex items-center justify-between">
                  <div>
                    <h3 className="font-bold text-slate-200 flex items-center gap-2"><History size={14}/> {currentStock?.name} — 交易記錄</h3>
                    <p className="text-xs text-slate-500 mt-0.5">從左側自選股切換股票來查看對應記錄</p>
                  </div>
                  <button onClick={() => setShowTradeInput(v => !v)}
                    className="text-sm bg-blue-600 hover:bg-blue-500 text-white px-3 py-1 rounded transition">
                    {showTradeInput ? '取消' : '+ 新增'}
                  </button>
                </div>

                {showTradeInput && (
                  <div className="p-4 border-b border-slate-800 bg-slate-950">
                    <div className="grid grid-cols-2 gap-2 mb-2">
                      <button onClick={() => setTradeForm(f => ({ ...f, type: 'BUY' }))}  className={`py-2 rounded font-bold text-sm transition ${tradeForm.type === 'BUY'  ? 'bg-rose-600 text-white' : 'bg-slate-800 text-slate-400'}`}>買進</button>
                      <button onClick={() => setTradeForm(f => ({ ...f, type: 'SELL' }))} className={`py-2 rounded font-bold text-sm transition ${tradeForm.type === 'SELL' ? 'bg-emerald-600 text-white' : 'bg-slate-800 text-slate-400'}`}>賣出</button>
                    </div>
                    <div className="grid grid-cols-3 gap-2 mb-2">
                      <input type="number" placeholder="成交價格" value={tradeForm.price} onChange={e => setTradeForm(f => ({ ...f, price: e.target.value }))}
                        className="bg-slate-800 border border-slate-700 rounded px-3 py-2 text-sm text-white focus:border-blue-500 focus:outline-none"/>
                      <input type="number" placeholder="股數" value={tradeForm.shares} onChange={e => setTradeForm(f => ({ ...f, shares: e.target.value }))}
                        className="bg-slate-800 border border-slate-700 rounded px-3 py-2 text-sm text-white focus:border-blue-500 focus:outline-none"/>
                      <input type="text" placeholder="備註（選填）" value={tradeForm.note} onChange={e => setTradeForm(f => ({ ...f, note: e.target.value }))}
                        className="bg-slate-800 border border-slate-700 rounded px-3 py-2 text-sm text-white focus:border-blue-500 focus:outline-none"/>
                    </div>
                    <button onClick={addTrade} className="w-full bg-blue-600 hover:bg-blue-500 text-white py-2 rounded font-bold text-sm transition">確認記錄</button>
                  </div>
                )}

                {myStats && myStats.totalShares > 0 && (
                  <div className={`mx-4 mt-3 p-3 rounded-lg border ${myStats.unrealizedPnl >= 0 ? 'bg-rose-950/20 border-rose-500/20' : 'bg-emerald-950/20 border-emerald-500/20'}`}>
                    <div className="flex justify-between items-center">
                      <div>
                        <div className="text-xs text-slate-500">持倉 {myStats.totalShares.toLocaleString()} 股 · 均價 ${myStats.avgBuy.toFixed(2)}</div>
                        <div className="text-xs text-slate-500 mt-0.5">現價 ${myStats.currentPrice.toFixed(2)}</div>
                      </div>
                      <div className="text-right">
                        <div className={`font-mono font-bold text-lg ${myStats.unrealizedPnl >= 0 ? 'text-rose-400' : 'text-emerald-400'}`}>
                          {myStats.unrealizedPnl >= 0 ? '+' : ''}{myStats.unrealizedPnl.toLocaleString(undefined, { maximumFractionDigits: 0 })}
                        </div>
                        <div className={`text-sm ${myStats.unrealizedPct >= 0 ? 'text-rose-400/70' : 'text-emerald-400/70'}`}>
                          {myStats.unrealizedPct >= 0 ? '+' : ''}{myStats.unrealizedPct.toFixed(1)}%
                        </div>
                      </div>
                    </div>
                  </div>
                )}

                <div className="flex-1 overflow-y-auto p-4 space-y-2">
                  {myStats ? myStats.trades.map(t => (
                    <div key={t.id}>
                      {editingTradeId === t.id ? (
                        <div className="bg-slate-800 border border-blue-500/40 rounded-lg p-3 space-y-2">
                          <div className="grid grid-cols-2 gap-1">
                            <button onClick={() => setTradeForm(f => ({ ...f, type: 'BUY' }))}  className={`py-1.5 rounded font-bold text-sm ${tradeForm.type==='BUY' ? 'bg-rose-600 text-white' : 'bg-slate-700 text-slate-400'}`}>買進</button>
                            <button onClick={() => setTradeForm(f => ({ ...f, type: 'SELL' }))} className={`py-1.5 rounded font-bold text-sm ${tradeForm.type==='SELL' ? 'bg-emerald-600 text-white' : 'bg-slate-700 text-slate-400'}`}>賣出</button>
                          </div>
                          <div className="grid grid-cols-3 gap-2">
                            <input type="number" value={tradeForm.price}  onChange={e => setTradeForm(f => ({ ...f, price: e.target.value }))}  placeholder="價格" className="bg-slate-900 border border-slate-700 rounded px-2 py-1.5 text-sm text-white focus:border-blue-500 focus:outline-none"/>
                            <input type="number" value={tradeForm.shares} onChange={e => setTradeForm(f => ({ ...f, shares: e.target.value }))} placeholder="股數" className="bg-slate-900 border border-slate-700 rounded px-2 py-1.5 text-sm text-white focus:border-blue-500 focus:outline-none"/>
                            <input type="text"   value={tradeForm.note}   onChange={e => setTradeForm(f => ({ ...f, note: e.target.value }))}   placeholder="備註" className="bg-slate-900 border border-slate-700 rounded px-2 py-1.5 text-sm text-white focus:border-blue-500 focus:outline-none"/>
                          </div>
                          <div className="grid grid-cols-2 gap-2">
                            <button onClick={() => updateTrade(t.id, { type: tradeForm.type, price: parseFloat(tradeForm.price), shares: parseInt(tradeForm.shares), note: tradeForm.note })}
                              className="bg-blue-600 hover:bg-blue-500 text-white text-sm py-1.5 rounded font-bold">儲存</button>
                            <button onClick={() => setEditingTradeId(null)} className="bg-slate-700 text-slate-300 text-sm py-1.5 rounded">取消</button>
                          </div>
                        </div>
                      ) : (
                        <div className="flex justify-between items-center py-2.5 px-3 border border-slate-800 rounded-lg hover:bg-slate-800/50 group transition">
                          <div className="flex items-center gap-2">
                            <span className={`px-2 py-0.5 rounded font-bold text-sm ${t.type==='BUY' ? 'bg-rose-500/20 text-rose-400' : 'bg-emerald-500/20 text-emerald-400'}`}>{t.type==='BUY'?'買':'賣'}</span>
                            <span className="text-slate-400 text-sm">{t.date}</span>
                            {t.note && <span className="text-slate-600 text-xs">· {t.note}</span>}
                          </div>
                          <div className="flex items-center gap-2">
                            <span className="font-mono text-slate-300 text-sm">${t.price} × {t.shares.toLocaleString()}</span>
                            <div className="flex gap-1 opacity-0 group-hover:opacity-100 transition">
                              <button onClick={() => { setEditingTradeId(t.id); setTradeForm({ type: t.type, price: t.price, shares: t.shares, note: t.note || '' }); }}
                                className="text-slate-500 hover:text-blue-400 px-1 text-sm">✏️</button>
                              <button onClick={() => setMyTrades(prev => prev.filter(x => x.id !== t.id))}
                                className="text-slate-500 hover:text-rose-500"><X size={13}/></button>
                            </div>
                          </div>
                        </div>
                      )}
                    </div>
                  )) : (
                    <div className="text-center text-slate-600 py-8">還沒有 {currentStock?.name} 的交易記錄</div>
                  )}
                </div>
              </div>
            </div>

            {/* 右：狙擊紀錄 Log */}
            <div className="w-72 flex flex-col flex-shrink-0">
              <div className="bg-slate-900 border border-slate-700 rounded-xl flex flex-col overflow-hidden flex-1">
                <div className="px-4 py-3 bg-slate-800 border-b border-slate-700">
                  <h3 className="font-bold text-slate-200 flex items-center gap-2"><Filter size={14}/> 策略訊號 Log</h3>
                </div>
                <div className="flex-1 overflow-y-auto p-3 space-y-2">
                  {strategyInfo?.logs && strategyInfo.logs.length > 0 ? (
                    strategyInfo.logs.slice().reverse().map((log, idx) => (
                      <div key={idx} className="text-sm border-b border-slate-800 pb-2">
                        <div className="flex justify-between items-center mb-1">
                          <span className="text-slate-500 text-xs">{new Date(log.date).toLocaleDateString()}</span>
                          <span className={`font-bold px-1.5 py-0.5 rounded text-xs ${log.type === 'BUY' ? 'bg-rose-500/20 text-rose-400' : 'bg-emerald-500/20 text-emerald-400'}`}>{log.type === 'BUY' ? '買進' : '賣出'}</span>
                        </div>
                        <div className="flex justify-between items-start gap-2">
                          <span className="text-slate-400 text-xs break-words leading-tight flex-1">{log.desc}</span>
                          <span className="text-slate-300 font-mono font-bold text-xs flex-shrink-0 bg-slate-800 px-1 rounded">${log.price.toFixed(0)}</span>
                        </div>
                      </div>
                    ))
                  ) : <div className="text-slate-600 text-sm text-center mt-4">等待獵物中...</div>}
                </div>
              </div>
            </div>
          </div>
        )}
      </div>

      {/* ── 參數設定 Modal ── */}
      {showSettings && (
        <div className="fixed inset-0 bg-slate-950/90 z-50 flex items-center justify-center">
          <div className="bg-slate-900 border border-slate-700 rounded-xl p-6 w-96 shadow-2xl">
            <div className="flex justify-between items-center mb-5 pb-4 border-b border-slate-800">
              <h2 className="text-base font-bold flex items-center gap-2"><Sliders size={16} className="text-blue-500"/> 策略參數設定</h2>
              <button onClick={() => setShowSettings(false)} className="text-slate-400 hover:text-white"><X size={18}/></button>
            </div>
            <div className="space-y-4">
              <div className="bg-slate-800 p-3 rounded-lg border border-slate-700">
                <label className="text-xs text-slate-400 block mb-2 font-bold">策略模式</label>
                <div className="grid grid-cols-2 gap-2">
                  {[{ id:'swing', label:'狙擊波段', sub:'中小型/飆股' }, { id:'trend', label:'趨勢長抱', sub:'大型/ETF' }].map(m => (
                    <button key={m.id} onClick={() => setActiveParams({ ...activeParams, strategy_type: m.id })}
                      className={`text-sm py-2 rounded flex flex-col items-center gap-0.5 transition ${activeParams.strategy_type === m.id ? (m.id==='swing' ? 'bg-indigo-600 text-white ring-2 ring-indigo-400' : 'bg-emerald-600 text-white ring-2 ring-emerald-400') : 'bg-slate-700 text-slate-400 hover:bg-slate-600'}`}>
                      <span className="font-bold">{m.label}</span>
                      <span className="text-xs opacity-70">{m.sub}</span>
                    </button>
                  ))}
                </div>
              </div>
              {[
                { label: '停損幅度', key: 'stop_loss', min: 0.01, max: 0.20, step: 0.01, format: v => `${(v*100).toFixed(0)}%`, color: 'rose' },
                activeParams.strategy_type === 'swing' && { label: '停利幅度', key: 'take_profit', min: 0.05, max: 0.50, step: 0.01, format: v => `${(v*100).toFixed(0)}%`, color: 'emerald' },
                { label: 'ATR 動態倍數', key: 'atr_multiplier', min: 1.0, max: 4.0, step: 0.1, format: v => `${v}x`, color: 'blue' },
              ].filter(Boolean).map(s => (
                <div key={s.key} className="space-y-1">
                  <label className="text-xs text-slate-400 flex justify-between">{s.label} <span className={`text-${s.color}-400 font-mono`}>{s.format(activeParams[s.key])}</span></label>
                  <input type="range" min={s.min} max={s.max} step={s.step} value={activeParams[s.key]}
                    onChange={e => setActiveParams({ ...activeParams, [s.key]: parseFloat(e.target.value) })}
                    className={`w-full accent-${s.color}-500 h-1.5 bg-slate-700 rounded-lg appearance-none cursor-pointer`}/>
                </div>
              ))}
              <div className="pt-4 border-t border-slate-800 grid grid-cols-2 gap-3">
                <button onClick={() => setActiveParams(defaultParams)} className="bg-slate-800 hover:bg-slate-700 text-slate-400 py-2 rounded text-sm font-bold transition">重置預設</button>
                <button onClick={() => { handleManualParamChange(activeParams); setShowSettings(false); }}
                  className="bg-blue-600 hover:bg-blue-500 text-white py-2 rounded text-sm font-bold transition flex items-center justify-center gap-1"><Save size={12}/> 套用</button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default App;