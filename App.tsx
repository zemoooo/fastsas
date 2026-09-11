import { useState, useEffect, useCallback } from 'react';
import {
  Store, Bot, BookOpen, MessageCircle, Settings, LogOut,
  Loader2, Check, AlertCircle, Send, Trash2, Plus, Search,
  QrCode, Phone, Globe, Upload, Zap, Calendar, ShoppingBag,
  ChevronRight, Activity, FileText, Link2,
} from 'lucide-react';
import type { StoreData, UserData, ChatMessage, AgentStatus, KnowledgeDoc, ViewType } from './types';
import * as api from './api';

export default function App() {
  const [user, setUser] = useState<UserData | null>(null);
  const [store, setStore] = useState<StoreData | null>(null);
  const [loading, setLoading] = useState(true);
  const [authMode, setAuthMode] = useState<'login' | 'register'>('login');
  const [verificationPending, setVerificationPending] = useState<string | null>(null);
  const [view, setView] = useState<ViewType>('dashboard');
  const [error, setError] = useState('');
  const [success, setSuccess] = useState('');

  const checkSession = useCallback(async () => {
    try {
      const data = await api.getMe();
      setUser(data.user);
      setStore(data.store);
    } catch {
      setUser(null);
      setStore(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    checkSession();
  }, [checkSession]);

  const handleLogout = async () => {
    try {
      await api.logout();
    } catch { /* ignore */ }
    setUser(null);
    setStore(null);
    setView('dashboard');
  };

  const showErr = (msg: string) => {
    setError(msg);
    setTimeout(() => setError(''), 5000);
  };

  const showOk = (msg: string) => {
    setSuccess(msg);
    setTimeout(() => setSuccess(''), 4000);
  };

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-[#0a0f1e]">
        <Loader2 className="w-8 h-8 text-blue-500 animate-spin" />
      </div>
    );
  }

  if (!user || !store) {
    if (verificationPending) {
      return (
        <VerifyScreen
          email={verificationPending}
          onVerified={async () => {
            setVerificationPending(null);
            await checkSession();
          }}
          onResend={async (email) => {
            await api.resendVerification(email);
            showOk('تم إرسال رمز جديد');
          }}
          showErr={showErr}
        />
      );
    }
    return (
      <AuthScreen
        mode={authMode}
        setMode={setAuthMode}
        onLogin={async (u, p) => {
          const data = await api.login(u, p);
          if (data.verification_required) {
            setVerificationPending(data.email);
            return;
          }
          setUser(data.user);
          setStore(data.store);
          showOk('تم تسجيل الدخول بنجاح');
        }}
        onRegister={async (sn, u, e, p) => {
          const data = await api.registerStore(sn, u, e, p);
          if (data.verification_required) {
            setVerificationPending(e);
            showOk(data.message || 'تم إنشاء الحساب. أدخل رمز التحقق.');
          } else {
            setUser(data.user);
            setStore(data.store);
          }
        }}
        showErr={showErr}
      />
    );
  }

  const navItems: { id: ViewType; label: string; icon: typeof Store }[] = [
    { id: 'dashboard', label: 'الرئيسية', icon: Activity },
    { id: 'agent', label: 'إعدادات الإيجنت', icon: Bot },
    { id: 'knowledge', label: 'قاعدة المعرفة', icon: BookOpen },
    { id: 'whatsapp', label: 'واتساب', icon: MessageCircle },
    { id: 'chat', label: 'معاينة المحادثة', icon: Send },
    { id: 'settings', label: 'الإعدادات', icon: Settings },
  ];

  return (
    <div className="min-h-screen bg-[#0a0f1e] text-slate-100 flex" dir="rtl">
      {/* Sidebar */}
      <aside className="w-64 shrink-0 border-l border-slate-800 bg-[#0d1421] flex flex-col">
        <div className="p-5 border-b border-slate-800">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-blue-600 to-cyan-500 flex items-center justify-center">
              <Bot className="w-5 h-5 text-white" />
            </div>
            <div>
              <h1 className="text-sm font-bold">مساعد المتجر</h1>
              <p className="text-xs text-slate-500">{store.store_name}</p>
            </div>
          </div>
        </div>

        <nav className="flex-1 p-3 space-y-1">
          {navItems.map((item) => {
            const Icon = item.icon;
            const active = view === item.id;
            return (
              <button
                key={item.id}
                onClick={() => setView(item.id)}
                className={`w-full flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium transition-all ${
                  active
                    ? 'bg-blue-600/15 text-blue-400 border border-blue-600/30'
                    : 'text-slate-400 hover:text-slate-200 hover:bg-slate-800/50'
                }`}
              >
                <Icon className="w-4 h-4" />
                {item.label}
                {active && <ChevronRight className="w-4 h-4 mr-auto rotate-180" />}
              </button>
            );
          })}
        </nav>

        <div className="p-3 border-t border-slate-800">
          <div className="px-3 py-2 mb-2">
            <p className="text-xs text-slate-500 truncate">{user.email}</p>
          </div>
          <button
            onClick={handleLogout}
            className="w-full flex items-center gap-2 px-3 py-2 rounded-lg text-sm text-slate-400 hover:text-red-400 hover:bg-red-500/10 transition-all"
          >
            <LogOut className="w-4 h-4" />
            تسجيل الخروج
          </button>
        </div>
      </aside>

      {/* Main content */}
      <main className="flex-1 overflow-y-auto">
        {/* Top bar */}
        <div className="sticky top-0 z-10 bg-[#0a0f1e]/80 backdrop-blur-md border-b border-slate-800 px-8 py-4">
          <div className="flex items-center justify-between">
            <h2 className="text-lg font-bold">
              {navItems.find((n) => n.id === view)?.label || 'الرئيسية'}
            </h2>
            {error && (
              <div className="flex items-center gap-2 text-sm text-red-400 bg-red-500/10 px-4 py-2 rounded-lg">
                <AlertCircle className="w-4 h-4" />
                {error}
              </div>
            )}
            {success && !error && (
              <div className="flex items-center gap-2 text-sm text-emerald-400 bg-emerald-500/10 px-4 py-2 rounded-lg">
                <Check className="w-4 h-4" />
                {success}
              </div>
            )}
          </div>
        </div>

        <div className="p-8 fade-in" key={view}>
          {view === 'dashboard' && <DashboardView store={store} />}
          {view === 'agent' && (
            <AgentView store={store} onUpdated={(s) => { setStore(s); showOk('تم حفظ الإعدادات بنجاح'); }} showErr={showErr} />
          )}
          {view === 'knowledge' && <KnowledgeView showErr={showErr} showOk={showOk} />}
          {view === 'whatsapp' && <WhatsappView store={store} showErr={showErr} showOk={showOk} />}
          {view === 'chat' && <ChatView store={store} showErr={showErr} />}
          {view === 'settings' && <SettingsView user={user} store={store} />}
        </div>
      </main>
    </div>
  );
}

/* ==================================================== */
/* AUTH SCREEN                                          */
/* ==================================================== */

function AuthScreen({
  mode,
  setMode,
  onLogin,
  onRegister,
  showErr,
}: {
  mode: 'login' | 'register';
  setMode: (m: 'login' | 'register') => void;
  onLogin: (u: string, p: string) => Promise<void>;
  onRegister: (sn: string, u: string, e: string, p: string) => Promise<void>;
  showErr: (m: string) => void;
}) {
  const [storeName, setStoreName] = useState('');
  const [username, setUsername] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    try {
      if (mode === 'login') {
        await onLogin(username, password);
      } else {
        await onRegister(storeName, username, email, password);
      }
    } catch (err: any) {
      showErr(err.message || 'حدث خطأ');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen bg-[#0a0f1e] flex items-center justify-center p-4" dir="rtl">
      <div className="absolute inset-0 overflow-hidden">
        <div className="absolute top-1/4 right-1/4 w-96 h-96 bg-blue-600/10 rounded-full blur-3xl" />
        <div className="absolute bottom-1/4 left-1/4 w-96 h-96 bg-cyan-500/10 rounded-full blur-3xl" />
      </div>

      <div className="relative w-full max-w-md glass-card p-8 fade-in">
        <div className="text-center mb-8">
          <div className="inline-flex items-center justify-center w-16 h-16 rounded-2xl bg-gradient-to-br from-blue-600 to-cyan-500 mb-4">
            <Bot className="w-8 h-8 text-white" />
          </div>
          <h1 className="text-2xl font-bold mb-1">مساعد المتجر الذكي</h1>
          <p className="text-sm text-slate-400">
            {mode === 'login' ? 'سجل الدخول إلى لوحة التحكم' : 'أنشئ حساب متجرك في دقيقة'}
          </p>
        </div>

        <form onSubmit={handleSubmit} className="space-y-4">
          {mode === 'register' && (
            <div>
              <label className="text-xs text-slate-400 mb-1.5 block">اسم المتجر</label>
              <input
                className="input-field"
                value={storeName}
                onChange={(e) => setStoreName(e.target.value)}
                placeholder="متجري"
                required
              />
            </div>
          )}

          <div>
            <label className="text-xs text-slate-400 mb-1.5 block">
              {mode === 'login' ? 'اسم المستخدم أو البريد' : 'اسم المستخدم'}
            </label>
            <input
              className="input-field"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              placeholder="username"
              required
            />
          </div>

          {mode === 'register' && (
            <div>
              <label className="text-xs text-slate-400 mb-1.5 block">البريد الإلكتروني</label>
              <input
                className="input-field"
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="store@example.com"
                required
              />
            </div>
          )}

          <div>
            <label className="text-xs text-slate-400 mb-1.5 block">كلمة المرور</label>
            <input
              className="input-field"
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="••••••••"
              required
            />
          </div>

          <button type="submit" disabled={loading} className="btn-primary w-full flex items-center justify-center gap-2">
            {loading && <Loader2 className="w-4 h-4 animate-spin" />}
            {mode === 'login' ? 'تسجيل الدخول' : 'إنشاء الحساب'}
          </button>
        </form>

        <div className="mt-6 text-center">
          <button
            onClick={() => setMode(mode === 'login' ? 'register' : 'login')}
            className="text-sm text-slate-400 hover:text-blue-400 transition-colors"
          >
            {mode === 'login' ? 'ليس لديك حساب؟ أنشئ حساباً' : 'لديك حساب؟ سجل الدخول'}
          </button>
        </div>
      </div>
    </div>
  );
}

/* ==================================================== */
/* VERIFY SCREEN                                        */
/* ==================================================== */

function VerifyScreen({
  email,
  onVerified,
  onResend,
  showErr,
}: {
  email: string;
  onVerified: () => Promise<void>;
  onResend: (email: string) => Promise<void>;
  showErr: (m: string) => void;
}) {
  const [code, setCode] = useState('');
  const [loading, setLoading] = useState(false);
  const [resendLoading, setResendLoading] = useState(false);

  const handleVerify = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    try {
      await api.verifyEmail(email, code);
      await onVerified();
    } catch (err: any) {
      showErr(err.message || 'رمز غير صحيح');
    } finally {
      setLoading(false);
    }
  };

  const handleResend = async () => {
    setResendLoading(true);
    try {
      await onResend(email);
    } catch (err: any) {
      showErr(err.message || 'تعذر إرسال رمز جديد');
    } finally {
      setResendLoading(false);
    }
  };

  return (
    <div className="min-h-screen bg-[#0a0f1e] flex items-center justify-center p-4" dir="rtl">
      <div className="w-full max-w-md glass-card p-8 fade-in">
        <div className="text-center mb-6">
          <div className="inline-flex items-center justify-center w-16 h-16 rounded-2xl bg-gradient-to-br from-blue-600 to-cyan-500 mb-4">
            <Bot className="w-8 h-8 text-white" />
          </div>
          <h1 className="text-xl font-bold mb-1">تأكيد البريد الإلكتروني</h1>
          <p className="text-sm text-slate-400">
            أدخل الرمز المرسل إلى <span className="text-blue-400">{email}</span>
          </p>
        </div>

        <form onSubmit={handleVerify} className="space-y-4">
          <input
            className="input-field text-center text-2xl tracking-widest"
            value={code}
            onChange={(e) => setCode(e.target.value.replace(/\D/g, '').slice(0, 8))}
            placeholder="••••••"
            required
            autoFocus
          />
          <button type="submit" disabled={loading} className="btn-primary w-full flex items-center justify-center gap-2">
            {loading && <Loader2 className="w-4 h-4 animate-spin" />}
            تأكيد
          </button>
        </form>

        <button
          onClick={handleResend}
          disabled={resendLoading}
          className="mt-4 w-full text-center text-sm text-slate-400 hover:text-blue-400 transition-colors"
        >
          {resendLoading ? 'جاري الإرسال...' : 'إعادة إرسال الرمز'}
        </button>
      </div>
    </div>
  );
}

/* ==================================================== */
/* DASHBOARD VIEW                                        */
/* ==================================================== */

function DashboardView({ store }: { store: StoreData }) {
  const [status, setStatus] = useState<AgentStatus | null>(null);

  useEffect(() => {
    api.getAgentStatus().then(setStatus).catch(() => {});
  }, []);

  const tools = [
    { name: 'knowledge_search', label: 'قاعدة المعرفة', icon: BookOpen, configured: true },
    { name: 'web_search', label: 'بحث الإنترنت', icon: Search, configured: status?.tavily_configured },
    { name: 'scrape_website', label: 'استخراج المواقع', icon: Globe, configured: status?.firecrawl_configured },
    { name: 'shopify_products', label: 'Shopify', icon: ShoppingBag, configured: status?.shopify_configured },
    { name: 'google_calendar_events', label: 'Google Calendar', icon: Calendar, configured: status?.google_calendar_configured },
    { name: 'whatsapp_send', label: 'واتساب', icon: MessageCircle, configured: status?.evolution_configured },
    { name: 'browser_action', label: 'Browser Agent', icon: Zap, configured: true },
  ];

  return (
    <div className="space-y-6">
      {/* Welcome card */}
      <div className="glass-card p-6">
        <div className="flex items-start justify-between">
          <div>
            <h3 className="text-lg font-bold mb-1">مرحباً بك في لوحة التحكم</h3>
            <p className="text-sm text-slate-400">
              متجر: <span className="text-blue-400">{store.store_name}</span>
            </p>
          </div>
          <div className="w-12 h-12 rounded-xl bg-gradient-to-br from-blue-600/20 to-cyan-500/20 flex items-center justify-center">
            <Store className="w-6 h-6 text-blue-400" />
          </div>
        </div>
      </div>

      {/* Stats grid */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <StatCard icon={Bot} label="نموذج الذكاء" value={status?.model || '—'} color="blue" />
        <StatCard icon={Zap} label="عدد الأدوات" value={String(status?.tool_count || 0)} color="cyan" />
        <StatCard icon={BookOpen} label="قواعد المعرفة" value={String(status?.knowledge_bases || 0)} color="emerald" />
      </div>

      {/* Tools status */}
      <div className="glass-card p-6">
        <h3 className="text-sm font-bold text-slate-300 mb-4 flex items-center gap-2">
          <Activity className="w-4 h-4 text-blue-400" />
          حالة أدوات الإيجنت
        </h3>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
          {tools.map((tool) => {
            const Icon = tool.icon;
            const configured = tool.configured;
            return (
              <div
                key={tool.name}
                className={`flex items-center gap-3 p-3 rounded-lg border transition-all ${
                  configured
                    ? 'border-emerald-600/30 bg-emerald-500/5'
                    : 'border-slate-700/50 bg-slate-800/30'
                }`}
              >
                <div className={`w-8 h-8 rounded-lg flex items-center justify-center ${
                  configured ? 'bg-emerald-500/15 text-emerald-400' : 'bg-slate-700/50 text-slate-500'
                }`}>
                  <Icon className="w-4 h-4" />
                </div>
                <div className="flex-1">
                  <p className="text-sm font-medium">{tool.label}</p>
                  <p className={`text-xs ${configured ? 'text-emerald-400' : 'text-slate-500'}`}>
                    {configured ? 'مفعل' : 'غير مفعل'}
                  </p>
                </div>
                {configured ? (
                  <Check className="w-4 h-4 text-emerald-400" />
                ) : (
                  <AlertCircle className="w-4 h-4 text-slate-600" />
                )}
              </div>
            );
          })}
        </div>
      </div>

      {/* Quick info */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <InfoCard icon={Globe} label="رابط المتجر" value={store.store_url || 'غير محدد'} />
        <InfoCard icon={Phone} label="رقم واتساب" value={store.whatsapp_number || 'غير محدد'} />
      </div>
    </div>
  );
}

function StatCard({ icon: Icon, label, value, color }: { icon: typeof Store; label: string; value: string; color: string }) {
  const colors: Record<string, string> = {
    blue: 'from-blue-600/20 to-blue-500/5 text-blue-400',
    cyan: 'from-cyan-600/20 to-cyan-500/5 text-cyan-400',
    emerald: 'from-emerald-600/20 to-emerald-500/5 text-emerald-400',
  };
  return (
    <div className={`glass-card p-5 bg-gradient-to-br ${colors[color]}`}>
      <div className="flex items-center justify-between mb-3">
        <Icon className="w-5 h-5" />
      </div>
      <p className="text-2xl font-bold mb-1">{value}</p>
      <p className="text-xs text-slate-400">{label}</p>
    </div>
  );
}

function InfoCard({ icon: Icon, label, value }: { icon: typeof Store; label: string; value: string }) {
  return (
    <div className="glass-card p-5 flex items-center gap-4">
      <div className="w-10 h-10 rounded-lg bg-slate-800 flex items-center justify-center text-slate-400">
        <Icon className="w-5 h-5" />
      </div>
      <div className="min-w-0">
        <p className="text-xs text-slate-500 mb-0.5">{label}</p>
        <p className="text-sm font-medium truncate">{value}</p>
      </div>
    </div>
  );
}

/* ==================================================== */
/* AGENT VIEW                                            */
/* ==================================================== */

function AgentView({ store, onUpdated, showErr }: { store: StoreData; onUpdated: (s: StoreData) => void; showErr: (m: string) => void }) {
  const [storeUrl, setStoreUrl] = useState(store.store_url || '');
  const [whatsapp, setWhatsapp] = useState(store.whatsapp_number || '');
  const [notes, setNotes] = useState(store.agent_notes || '');
  const [pdfFile, setPdfFile] = useState<File | null>(null);
  const [loading, setLoading] = useState(false);

  const handleSave = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    try {
      const data = await api.updateAgent(store.id, storeUrl, whatsapp, notes, pdfFile);
      onUpdated(data.store);
    } catch (err: any) {
      showErr(err.message || 'فشل الحفظ');
    } finally {
      setLoading(false);
    }
  };

  return (
    <form onSubmit={handleSave} className="max-w-2xl space-y-5">
      <div>
        <label className="text-sm font-medium text-slate-300 mb-2 block">رابط المتجر</label>
        <div className="relative">
          <Globe className="absolute right-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-500" />
          <input
            className="input-field pr-10"
            value={storeUrl}
            onChange={(e) => setStoreUrl(e.target.value)}
            placeholder="https://mystore.com"
          />
        </div>
      </div>

      <div>
        <label className="text-sm font-medium text-slate-300 mb-2 block">رقم واتساب (مع المفتاح الدولي)</label>
        <div className="relative">
          <Phone className="absolute right-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-500" />
          <input
            className="input-field pr-10"
            value={whatsapp}
            onChange={(e) => setWhatsapp(e.target.value)}
            placeholder="967777123456"
          />
        </div>
      </div>

      <div>
        <label className="text-sm font-medium text-slate-300 mb-2 block">تعليمات الإيجنت</label>
        <textarea
          className="input-field min-h-[120px] resize-y"
          value={notes}
          onChange={(e) => setNotes(e.target.value)}
          placeholder="مثال: كن ودوداً ومختصراً. اعرض الأسعار بالريال. اذكر أن التوصيل مجاني للطلبات فوق 500 ريال."
        />
        <p className="text-xs text-slate-500 mt-1.5">هذه التعليمات توجه سلوك الإيجنت عند الرد على العملاء</p>
      </div>

      <div>
        <label className="text-sm font-medium text-slate-300 mb-2 block">كتالوج المنتجات (PDF)</label>
        <div className="glass-card p-4 border-dashed border-2 border-slate-700">
          <label className="flex items-center gap-3 cursor-pointer">
            <div className="w-10 h-10 rounded-lg bg-blue-600/15 flex items-center justify-center">
              <Upload className="w-5 h-5 text-blue-400" />
            </div>
            <div className="flex-1">
              <p className="text-sm font-medium">
                {pdfFile ? pdfFile.name : 'اختر ملف PDF'}
              </p>
              <p className="text-xs text-slate-500">
                {store.has_catalog && !pdfFile ? 'يوجد كتالوج محفوظ — الرفع سيستبدله' : 'ارفع كتالوج منتجاتك ليستخدمه الإيجنت'}
              </p>
            </div>
            <input
              type="file"
              accept=".pdf"
              className="hidden"
              onChange={(e) => setPdfFile(e.target.files?.[0] || null)}
            />
          </label>
        </div>
      </div>

      <button type="submit" disabled={loading} className="btn-primary flex items-center gap-2">
        {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Check className="w-4 h-4" />}
        حفظ الإعدادات
      </button>
    </form>
  );
}

/* ==================================================== */
/* KNOWLEDGE VIEW                                        */
/* ==================================================== */

function KnowledgeView({ showErr, showOk }: { showErr: (m: string) => void; showOk: (m: string) => void }) {
  const [docs, setDocs] = useState<KnowledgeDoc[]>([]);
  const [loading, setLoading] = useState(true);
  const [showAdd, setShowAdd] = useState(false);
  const [showScrape, setShowScrape] = useState(false);
  const [searchQuery, setSearchQuery] = useState('');
  const [searchResults, setSearchResults] = useState<any[]>([]);

  const loadDocs = useCallback(async () => {
    try {
      const data = await api.listKnowledge();
      setDocs(data.documents);
    } catch (err: any) {
      showErr(err.message);
    } finally {
      setLoading(false);
    }
  }, [showErr]);

  useEffect(() => {
    loadDocs();
  }, [loadDocs]);

  const handleDelete = async (id: string) => {
    try {
      await api.deleteKnowledge(id);
      setDocs(docs.filter((d) => d.id !== id));
      showOk('تم حذف المستند');
    } catch (err: any) {
      showErr(err.message);
    }
  };

  const handleSearch = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!searchQuery.trim()) return;
    try {
      const data = await api.searchKnowledge(searchQuery);
      setSearchResults(data.results);
    } catch (err: any) {
      showErr(err.message);
    }
  };

  return (
    <div className="space-y-5">
      {/* Actions bar */}
      <div className="flex flex-wrap gap-3">
        <button onClick={() => setShowAdd(true)} className="btn-primary flex items-center gap-2 text-sm">
          <Plus className="w-4 h-4" />
          إضافة مستند
        </button>
        <button onClick={() => setShowScrape(true)} className="btn-ghost flex items-center gap-2 text-sm">
          <Link2 className="w-4 h-4" />
          استخراج من موقع
        </button>
      </div>

      {/* Search */}
      <form onSubmit={handleSearch} className="flex gap-2">
        <div className="relative flex-1">
          <Search className="absolute right-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-500" />
          <input
            className="input-field pr-10"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder="ابحث في قاعدة المعرفة..."
          />
        </div>
        <button type="submit" className="btn-ghost">بحث</button>
      </form>

      {searchResults.length > 0 && (
        <div className="glass-card p-4">
          <h4 className="text-sm font-bold mb-3">نتائج البحث</h4>
          <div className="space-y-2">
            {searchResults.map((r, i) => (
              <div key={i} className="text-sm text-slate-300 p-3 rounded-lg bg-slate-800/50">
                {r.content}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Documents list */}
      {loading ? (
        <div className="flex justify-center py-12">
          <Loader2 className="w-6 h-6 text-blue-500 animate-spin" />
        </div>
      ) : docs.length === 0 ? (
        <div className="glass-card p-12 text-center">
          <BookOpen className="w-12 h-12 text-slate-600 mx-auto mb-3" />
          <p className="text-slate-400">لا توجد مستندات في قاعدة المعرفة بعد</p>
          <p className="text-xs text-slate-500 mt-1">أضف مستندات ليجد الإيجنت الإجابات فيها</p>
        </div>
      ) : (
        <div className="space-y-3">
          {docs.map((doc) => (
            <div key={doc.id} className="glass-card p-4 flex items-start gap-3">
              <div className="w-9 h-9 rounded-lg bg-slate-800 flex items-center justify-center shrink-0">
                <FileText className="w-4 h-4 text-slate-400" />
              </div>
              <div className="flex-1 min-w-0">
                <p className="text-sm font-medium mb-0.5">{doc.title || 'بدون عنوان'}</p>
                <p className="text-xs text-slate-500 line-clamp-2">{doc.content}</p>
                <div className="flex items-center gap-2 mt-2">
                  {doc.source && (
                    <span className="text-xs px-2 py-0.5 rounded bg-slate-800 text-slate-400">{doc.source}</span>
                  )}
                  {doc.doc_type && (
                    <span className="text-xs px-2 py-0.5 rounded bg-blue-600/15 text-blue-400">{doc.doc_type}</span>
                  )}
                </div>
              </div>
              <button
                onClick={() => handleDelete(doc.id)}
                className="p-2 rounded-lg text-slate-500 hover:text-red-400 hover:bg-red-500/10 transition-all"
              >
                <Trash2 className="w-4 h-4" />
              </button>
            </div>
          ))}
        </div>
      )}

      {/* Add modal */}
      {showAdd && (
        <AddDocModal
          onClose={() => setShowAdd(false)}
          onAdded={() => { setShowAdd(false); loadDocs(); showOk('تمت إضافة المستند'); }}
          showErr={showErr}
        />
      )}

      {/* Scrape modal */}
      {showScrape && (
        <ScrapeModal
          onClose={() => setShowScrape(false)}
          onDone={() => { setShowScrape(false); loadDocs(); showOk('تم استخراج المحتوى وإضافته'); }}
          showErr={showErr}
        />
      )}
    </div>
  );
}

function AddDocModal({ onClose, onAdded, showErr }: { onClose: () => void; onAdded: () => void; showErr: (m: string) => void }) {
  const [title, setTitle] = useState('');
  const [content, setContent] = useState('');
  const [loading, setLoading] = useState(false);

  const handleAdd = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    try {
      await api.addKnowledge(title, content);
      onAdded();
    } catch (err: any) {
      showErr(err.message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="fixed inset-0 bg-black/60 backdrop-blur-sm flex items-center justify-center p-4 z-50 fade-in" onClick={onClose}>
      <div className="glass-card p-6 w-full max-w-lg" onClick={(e) => e.stopPropagation()}>
        <h3 className="text-lg font-bold mb-4">إضافة مستند للقاعدة المعرفة</h3>
        <form onSubmit={handleAdd} className="space-y-4">
          <input
            className="input-field"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder="عنوان المستند (اختياري)"
          />
          <textarea
            className="input-field min-h-[160px] resize-y"
            value={content}
            onChange={(e) => setContent(e.target.value)}
            placeholder="محتوى المستند: معلومات المنتجات، الأسئلة الشائعة، سياسات المتجر..."
            required
          />
          <div className="flex gap-2">
            <button type="submit" disabled={loading} className="btn-primary flex items-center gap-2">
              {loading && <Loader2 className="w-4 h-4 animate-spin" />}
              إضافة
            </button>
            <button type="button" onClick={onClose} className="btn-ghost">إلغاء</button>
          </div>
        </form>
      </div>
    </div>
  );
}

function ScrapeModal({ onClose, onDone, showErr }: { onClose: () => void; onDone: () => void; showErr: (m: string) => void }) {
  const [url, setUrl] = useState('');
  const [title, setTitle] = useState('');
  const [loading, setLoading] = useState(false);

  const handleScrape = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    try {
      await api.scrapeUrl(url, title);
      onDone();
    } catch (err: any) {
      showErr(err.message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="fixed inset-0 bg-black/60 backdrop-blur-sm flex items-center justify-center p-4 z-50 fade-in" onClick={onClose}>
      <div className="glass-card p-6 w-full max-w-lg" onClick={(e) => e.stopPropagation()}>
        <h3 className="text-lg font-bold mb-4">استخراج محتوى من موقع</h3>
        <form onSubmit={handleScrape} className="space-y-4">
          <input
            className="input-field"
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            placeholder="https://example.com/products"
            required
          />
          <input
            className="input-field"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder="عنوان اختياري للمستند"
          />
          <p className="text-xs text-slate-500">سيتم استخراج محتوى الصفحة وإضافته لقاعدة المعرفة تلقائياً</p>
          <div className="flex gap-2">
            <button type="submit" disabled={loading} className="btn-primary flex items-center gap-2">
              {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Globe className="w-4 h-4" />}
              استخراج
            </button>
            <button type="button" onClick={onClose} className="btn-ghost">إلغاء</button>
          </div>
        </form>
      </div>
    </div>
  );
}

/* ==================================================== */
/* WHATSAPP VIEW                                         */
/* ==================================================== */

function WhatsappView({ store, showErr, showOk }: { store: StoreData; showErr: (m: string) => void; showOk: (m: string) => void }) {
  const [qr, setQr] = useState<string | null>(null);
  const [status, setStatus] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [polling, setPolling] = useState(false);

  const fetchQR = async () => {
    setLoading(true);
    try {
      const data = await api.getWhatsappQR(store.id);
      setQr(data.qr_code);
      setStatus(data.connection_state || 'pending');
      showOk('تم إنشاء رمز QR');
    } catch (err: any) {
      showErr(err.message || 'تعذر الحصول على QR');
    } finally {
      setLoading(false);
    }
  };

  const checkStatus = async () => {
    setPolling(true);
    try {
      const data = await api.getWhatsappStatus(store.id);
      setStatus(data.connection_state);
      if (data.connection_state === 'open') {
        showOk('واتساب متصل!');
      }
    } catch { /* ignore */ } finally {
      setPolling(false);
    }
  };

  useEffect(() => {
    checkStatus();
    const interval = setInterval(checkStatus, 10000);
    return () => clearInterval(interval);
  }, []);

  const isConnected = status?.toLowerCase() === 'open';

  return (
    <div className="max-w-2xl space-y-5">
      {/* Status card */}
      <div className="glass-card p-6">
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-3">
            <div className={`w-3 h-3 rounded-full ${isConnected ? 'bg-emerald-500' : 'bg-amber-500'} pulse-dot`} />
            <div>
              <p className="text-sm font-bold">
                {isConnected ? 'واتساب متصل' : 'واتساب غير متصل'}
              </p>
              <p className="text-xs text-slate-500">
                الحالة: {status || 'غير معروف'}
              </p>
            </div>
          </div>
          <button onClick={checkStatus} disabled={polling} className="btn-ghost text-sm flex items-center gap-2">
            {polling ? <Loader2 className="w-4 h-4 animate-spin" /> : <Activity className="w-4 h-4" />}
            تحديث
          </button>
        </div>

        {!store.whatsapp_number ? (
          <div className="text-sm text-amber-400 bg-amber-500/10 p-3 rounded-lg flex items-center gap-2">
            <AlertCircle className="w-4 h-4" />
            يجب حفظ رقم واتساب أولاً في إعدادات الإيجنت
          </div>
        ) : (
          <div className="text-sm text-slate-400">
            الرقم المسجل: <span className="text-blue-400 font-mono">{store.whatsapp_number}</span>
          </div>
        )}
      </div>

      {/* QR card */}
      {!isConnected && store.whatsapp_number && (
        <div className="glass-card p-6 text-center">
          <h3 className="text-sm font-bold mb-4 flex items-center justify-center gap-2">
            <QrCode className="w-5 h-5 text-blue-400" />
            امسح رمز QR للاتصال
          </h3>

          {qr ? (
            <div className="inline-block p-4 bg-white rounded-xl">
              <img src={qr} alt="WhatsApp QR" className="w-56 h-56" />
            </div>
          ) : (
            <div className="w-56 h-56 mx-auto flex items-center justify-center bg-slate-800/50 rounded-xl">
              {loading ? (
                <Loader2 className="w-8 h-8 text-blue-500 animate-spin" />
              ) : (
                <QrCode className="w-16 h-16 text-slate-600" />
              )}
            </div>
          )}

          <button
            onClick={fetchQR}
            disabled={loading || !store.whatsapp_number}
            className="btn-primary mt-4 flex items-center gap-2 mx-auto"
          >
            {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : <QrCode className="w-4 h-4" />}
            {qr ? 'إعادة إنشاء QR' : 'إنشاء رمز QR'}
          </button>

          <p className="text-xs text-slate-500 mt-3">
            افتح واتساب على هاتفك ← الإعدادات ← الأجهزة المرتبطة ← امسح الرمز
          </p>
        </div>
      )}
    </div>
  );
}

/* ==================================================== */
/* CHAT VIEW                                             */
/* ==================================================== */

function ChatView({ store, showErr }: { store: StoreData; showErr: (m: string) => void }) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);

  const handleSend = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!input.trim() || loading) return;

    const userMsg = input.trim();
    setMessages((prev) => [...prev, { role: 'user', content: userMsg }]);
    setInput('');
    setLoading(true);

    try {
      const data = await api.sendChat(store.id, userMsg);
      setMessages((prev) => [...prev, { role: 'assistant', content: data.reply || data.response }]);
    } catch (err: any) {
      showErr(err.message || 'فشل الإرسال');
      setMessages((prev) => [...prev, { role: 'assistant', content: 'عذراً، حدث خطأ. حاول مرة أخرى.' }]);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="max-w-2xl">
      <div className="glass-card flex flex-col h-[600px]">
        {/* Header */}
        <div className="px-5 py-4 border-b border-slate-800 flex items-center gap-3">
          <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-blue-600 to-cyan-500 flex items-center justify-center">
            <Bot className="w-5 h-5 text-white" />
          </div>
          <div>
            <p className="text-sm font-bold">مساعد {store.store_name}</p>
            <p className="text-xs text-emerald-400 flex items-center gap-1">
              <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 pulse-dot" />
              متصل
            </p>
          </div>
        </div>

        {/* Messages */}
        <div className="flex-1 overflow-y-auto p-5 space-y-3">
          {messages.length === 0 && (
            <div className="text-center py-12">
              <Bot className="w-12 h-12 text-slate-600 mx-auto mb-3" />
              <p className="text-slate-400 text-sm">ابدأ المحادثة — اكتب رسالة لترى كيف يرد الإيجنت</p>
            </div>
          )}

          {messages.map((msg, i) => (
            <div
              key={i}
              className={`flex ${msg.role === 'user' ? 'justify-start' : 'justify-end'} slide-in`}
            >
              <div
                className={`max-w-[80%] px-4 py-2.5 rounded-2xl text-sm leading-relaxed ${
                  msg.role === 'user'
                    ? 'bg-slate-800 text-slate-100 rounded-tr-sm'
                    : 'bg-gradient-to-br from-blue-600 to-blue-500 text-white rounded-tl-sm'
                }`}
              >
                {msg.content}
              </div>
            </div>
          ))}

          {loading && (
            <div className="flex justify-end">
              <div className="bg-blue-600 px-4 py-3 rounded-2xl rounded-tl-sm">
                <div className="typing-dots flex gap-1">
                  <span className="w-1.5 h-1.5 bg-white rounded-full" />
                  <span className="w-1.5 h-1.5 bg-white rounded-full" />
                  <span className="w-1.5 h-1.5 bg-white rounded-full" />
                </div>
              </div>
            </div>
          )}
        </div>

        {/* Input */}
        <form onSubmit={handleSend} className="p-4 border-t border-slate-800 flex gap-2">
          <input
            className="input-field"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="اكتب رسالة..."
            disabled={loading}
          />
          <button
            type="submit"
            disabled={loading || !input.trim()}
            className="btn-primary shrink-0 flex items-center justify-center w-10 h-10 p-0"
          >
            <Send className="w-4 h-4" />
          </button>
        </form>
      </div>
    </div>
  );
}

/* ==================================================== */
/* SETTINGS VIEW                                        */
/* ==================================================== */

function SettingsView({ user, store }: { user: UserData; store: StoreData }) {
  return (
    <div className="max-w-2xl space-y-5">
      <div className="glass-card p-6">
        <h3 className="text-sm font-bold mb-4">معلومات الحساب</h3>
        <div className="space-y-3">
          <Row label="اسم المستخدم" value={user.username} />
          <Row label="البريد الإلكتروني" value={user.email} />
          <Row label="تأكيد البريد" value={user.email_verified ? 'مؤكد' : 'غير مؤكد'} />
        </div>
      </div>

      <div className="glass-card p-6">
        <h3 className="text-sm font-bold mb-4">معلومات المتجر</h3>
        <div className="space-y-3">
          <Row label="اسم المتجر" value={store.store_name} />
          <Row label="رابط المتجر" value={store.store_url || 'غير محدد'} />
          <Row label="رقم واتساب" value={store.whatsapp_number || 'غير محدد'} />
          <Row label="يوجد كتالوج" value={store.has_catalog ? 'نعم' : 'لا'} />
        </div>
      </div>
    </div>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between py-2 border-b border-slate-800 last:border-0">
      <span className="text-sm text-slate-400">{label}</span>
      <span className="text-sm font-medium">{value}</span>
    </div>
  );
}
