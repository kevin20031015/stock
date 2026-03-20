import React from 'react';
import { Activity, Search, Loader2, BrainCircuit, ScanSearch, Sliders, Cpu, Trash2, Zap, RefreshCcw, Settings, Filter } from 'lucide-react';
import { useAppContext } from '../contexts/AppContext';

// This is a sub-component for the watchlist item, to keep logic clean.
const WatchlistItem = ({ stock }) => {
    const { symbol, setSymbol, setShowScanner, stockSettingsCache, watchlist, setWatchlist } = useAppContext();

    const handleSelect = () => {
        setSymbol(stock.id);
        setShowScanner(false);
    };

    const handleRemove = (e) => {
        e.stopPropagation();
        setWatchlist(watchlist.filter(w => w.id !== stock.id));
    };

    const isActive = symbol === stock.id && !setShowScanner; // A simplified check
    const hasAiParams = stockSettingsCache[stock.id];

    return (
        <div onClick={handleSelect} className={`p-3 border-b border-slate-800 cursor-pointer hover:bg-slate-800 transition flex justify-between items-center ${isActive ? 'bg-slate-800 border-l-4 border-l-blue-500' : ''}`}>
            <div>
                <div className="font-bold text-slate-200 text-sm">{stock.name}</div>
                <div className="text-xs text-slate-500">{stock.displayId}</div>
            </div>
            <div className="flex items-center">
                {hasAiParams && <div className="flex items-center justify-center w-5 h-5 bg-amber-500/20 rounded text-[9px] text-amber-500 font-bold mr-2" title="已使用 AI 參數">AI</div>}
                <button onClick={handleRemove} className="text-slate-600 hover:text-rose-500 p-2"><Trash2 size={14} /></button>
            </div>
        </div>
    );
};


const LeftSidebar = () => {
    const {
        runScan,
        scanning,
        batchOptimizing,
        setShowSettings,
        runOptimization,
        optimizing,
        gaResult,
        runBatchOptimization,
        initialCapital,
        setInitialCapital,
        runAiPrediction,
        aiLoading,
        aiPrediction,
        batchProgress,
        handleAddStock,
        newStock,
        setNewStock,
        watchlist,
        strategyInfo,
    } = useAppContext();

    return (
        <div className="w-72 bg-slate-900 border-r border-slate-700 flex flex-col shadow-xl z-20 flex-shrink-0">
            <div className="p-4 border-b border-slate-700 bg-slate-900">
                <h1 className="text-lg font-bold flex items-center gap-2 text-blue-400">
                    <Activity className="w-5 h-5" /> QuantTrader
                    <span className="text-[9px] bg-rose-600 text-white px-1.5 py-0.5 rounded">AI PRO</span>
                </h1>
            </div>

            {/* AI 功能按鈕區 */}
            <div className="p-3 bg-slate-800/50 border-b border-slate-700 grid grid-cols-2 gap-2">
                <button onClick={runScan} disabled={scanning || batchOptimizing} className="col-span-1 flex items-center justify-center gap-1.5 bg-indigo-600 hover:bg-indigo-500 text-white text-xs py-2 rounded transition disabled:opacity-50">
                    {scanning ? <Loader2 className="animate-spin w-3 h-3" /> : <ScanSearch size={14} />} 全台掃描
                </button>
                <button onClick={() => setShowSettings(true)} className="col-span-1 flex items-center justify-center gap-1.5 bg-slate-800 border border-slate-600 hover:bg-slate-700 text-slate-300 text-xs py-2 rounded transition">
                    <Sliders size={14} /> 參數設定
                </button>
                <button onClick={runOptimization} disabled={optimizing || batchOptimizing} className={`col-span-1 flex items-center justify-center gap-1.5 text-xs py-2 rounded transition border ${gaResult ? 'bg-amber-500/10 text-amber-400 border-amber-500/50' : 'bg-slate-800 border-slate-600 text-slate-300 hover:bg-slate-700'} disabled:opacity-50`}>
                    {optimizing ? <Loader2 className="animate-spin w-3 h-3" /> : <Cpu size={14} />} {optimizing ? "計算中..." : "AI 優化"}
                </button>
                <button onClick={runBatchOptimization} disabled={batchOptimizing || optimizing} className="col-span-1 flex items-center justify-center gap-1.5 bg-slate-700 hover:bg-slate-600 text-emerald-300 border border-slate-600 text-xs py-2 rounded transition disabled:opacity-50">
                    {batchOptimizing ? <Loader2 className="animate-spin w-3 h-3" /> : <BrainCircuit size={14} />}
                    {batchOptimizing ? `優化中` : "全批次"}
                </button>
            </div>

            <div className="p-4 border-b border-slate-700 bg-slate-800/50">
                <div className="text-xs font-bold text-slate-400 mb-2 flex items-center gap-1"><Settings size={12} /> 投資本金</div>
                <div className="relative">
                    <input type="number" value={initialCapital} onChange={(e) => setInitialCapital(e.target.value)} className="w-full bg-slate-900 border border-slate-600 rounded py-1.5 pl-6 pr-2 text-sm text-white font-mono focus:border-blue-500 focus:outline-none" />
                    <span className="absolute left-2 top-1.5 text-slate-500">$</span>
                </div>
            </div>

            <div className="p-4 border-b border-slate-700 bg-gradient-to-br from-slate-900 to-slate-800">
                <h3 className="text-xs font-bold text-slate-400 mb-3 flex items-center gap-1"><BrainCircuit size={12} /> AI 深度學習 (RTX 4070)</h3>
                {!aiPrediction ? (
                    <button onClick={runAiPrediction} disabled={aiLoading} className="w-full relative overflow-hidden group bg-emerald-600 hover:bg-emerald-500 text-white py-3 rounded-lg text-sm font-bold transition-all shadow-lg shadow-emerald-900/20">
                        <div className="absolute inset-0 bg-white/20 translate-y-full group-hover:translate-y-0 transition-transform duration-300" />
                        <div className="relative flex items-center justify-center gap-2">
                            {aiLoading ? <Loader2 className="animate-spin" size={16} /> : <Zap size={16} className="text-yellow-300 fill-yellow-300" />}
                            {aiLoading ? "正在運算..." : "啟動 GPU 預測"}
                        </div>
                    </button>
                ) : (
                    <div className="bg-slate-950 border border-slate-700 rounded-lg p-3 animate-in fade-in slide-in-from-bottom-2">
                        <div className="flex justify-between items-start mb-2 border-b border-slate-800 pb-2">
                            <div className="flex flex-col">
                                <span className="text-[10px] text-slate-500 flex items-center gap-1"><Cpu size={10} /> {aiPrediction.gpu}</span>
                                <span className="text-[9px] text-indigo-400 font-bold mt-0.5">{aiPrediction.model_type}</span>
                            </div>
                            <button onClick={runAiPrediction} className="text-slate-500 hover:text-white"><RefreshCcw size={12} /></button>
                        </div>
                        <div className="grid grid-cols-3 gap-1 mb-2">
                            {aiPrediction.predicted.map((price, i) => (
                                <div key={i} className="text-center bg-slate-900 rounded p-1">
                                    <div className="text-[8px] text-slate-500">T+{i + 1}</div>
                                    <div className={`text-xs font-mono font-bold ${price > aiPrediction.current ? 'text-rose-400' : 'text-emerald-400'}`}>
                                        ${price}
                                    </div>
                                </div>
                            ))}
                        </div>
                        <div className="flex items-center justify-between text-[10px] mb-1">
                            <span className="text-slate-500">當前: ${aiPrediction.current}</span>
                            <span className={`${aiPrediction.change_pct >= 0 ? 'text-rose-400' : 'text-emerald-400'} font-bold`}>
                                均幅 {aiPrediction.change_pct > 0 ? '+' : ''}{aiPrediction.change_pct}%
                            </span>
                        </div>
                        <div className="mt-1 h-1 w-full bg-slate-800 rounded-full overflow-hidden">
                            <div className={`h-full ${aiPrediction.trend === 'BULL' ? 'bg-rose-500' : 'bg-emerald-500'}`} style={{ width: `${aiPrediction.confidence}%` }}></div>
                        </div>
                        <div className="text-[9px] text-right text-slate-500 mt-0.5">Attention 信心度: {aiPrediction.confidence}%</div>
                    </div>
                )}
            </div>

            {batchOptimizing && (
                <div className="p-3 bg-indigo-900/20 border-b border-indigo-500/30">
                    <div className="flex justify-between items-center mb-1">
                        <span className="text-[10px] text-indigo-400 font-bold flex items-center gap-1"><Loader2 className="animate-spin" size={10} /> 正在優化: {batchProgress.currentStock}</span>
                        <span className="text-[10px] text-indigo-300">{Math.round((batchProgress.current / batchProgress.total) * 100)}%</span>
                    </div>
                    <div className="w-full bg-slate-800 h-1.5 rounded-full overflow-hidden">
                        <div className="bg-indigo-500 h-full transition-all duration-300" style={{ width: `${(batchProgress.current / batchProgress.total) * 100}%` }}></div>
                    </div>
                </div>
            )}

            {gaResult && !batchOptimizing && (
                <div className="p-3 bg-emerald-900/20 border-b border-emerald-500/30 animate-in slide-in-from-top-2">
                    <div className="flex justify-between items-center mb-1">
                        <span className="text-[10px] text-emerald-400 font-bold flex items-center gap-1"><Zap size={10} /> 優化完成，已自動套用</span>
                        <span className="text-[10px] text-emerald-300">+{gaResult.improvement}%</span>
                    </div>
                    <div className="grid grid-cols-2 gap-1 opacity-70">
                        <div className="text-[9px] text-slate-400">RSI高: {gaResult.best_params.rsi_upper}</div>
                        <div className="text-[9px] text-slate-400">ADX: {gaResult.best_params.adx_threshold}</div>
                    </div>
                </div>
            )}

            <div className="p-3 border-b border-slate-700">
                <form onSubmit={handleAddStock} className="relative">
                    <input type="text" placeholder="代號 (2330)" value={newStock} onChange={e => setNewStock(e.target.value)} className="w-full bg-slate-800 border border-slate-600 rounded py-1.5 pl-8 pr-2 text-sm text-white focus:border-blue-500 focus:outline-none" />
                    <Search className="absolute left-2 top-2 text-slate-400 w-4 h-4" />
                </form>
            </div>

            <div className="flex-1 overflow-y-auto">
                {watchlist.map(s => <WatchlistItem key={s.id} stock={s} />)}
            </div>
            
            <div className="h-1/3 min-h-[180px] border-t border-slate-700 bg-slate-900/50 flex flex-col">
                <div className="p-2 bg-slate-800 text-xs font-bold text-slate-400 flex items-center gap-2 flex-shrink-0"><Filter size={12}/> 狙擊紀錄 (Log)</div>
                <div className="flex-1 overflow-y-auto p-2 space-y-2">
                    {strategyInfo?.logs && strategyInfo.logs.length > 0 ? (
                        strategyInfo.logs.slice().reverse().map((log, idx) => (
                            <div key={idx} className="text-xs flex flex-col border-b border-slate-800 pb-2">
                                <div className="flex justify-between items-center mb-1">
                                    <span className="text-slate-500 text-[10px]">{new Date(log.date).toLocaleDateString()}</span>
                                    <span className={`font-bold px-1 py-0.5 rounded text-[10px] ${log.type === 'BUY' ? 'bg-rose-500/20 text-rose-400' : 'bg-emerald-500/20 text-emerald-400'}`}>{log.type === 'BUY' ? '買進' : '賣出'}</span>
                                </div>
                                <div className="flex justify-between items-start gap-3">
                                    <span className="text-[10px] text-slate-400 break-words whitespace-normal leading-tight flex-1">{log.desc}</span>
                                    <span className="text-[10px] text-slate-300 font-mono font-bold flex-shrink-0 bg-slate-800 px-1 rounded">${log.price.toFixed(0)}</span>
                                </div>
                            </div>
                        ))
                    ) : <div className="text-xs text-slate-600 text-center mt-4">等待獵物中...</div>}
                </div>
            </div>
        </div>
    );
};

export default LeftSidebar;
