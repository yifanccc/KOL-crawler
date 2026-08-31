"use client";

import Link from "next/link";
import { FormEvent, useEffect, useMemo, useState } from "react";
import {
  ArrowLeft,
  BellRing,
  Bot,
  Database,
  Edit3,
  Plus,
  Save,
  ShieldCheck,
  Trash2,
  Users,
} from "lucide-react";

import { CollectorHealthCard } from "@/components/CollectorHealthCard";
import {
  createAdminSubscription,
  createBinanceCopySubscription,
  deleteAdminSubscription,
  fetchAdminConfigOptions,
  fetchAdminSubscriptions,
  isoToBeijingDateTimeLocal,
  updateAdminSubscription,
  updateBinanceCopySubscription,
} from "@/lib/api";
import {
  configurablePlatforms,
  platformLabel,
  requiresAccountId,
  requiresPromptConfiguration,
} from "@/lib/platforms";
import type { AdminConfigOptions, AdminSubscription, Asset, Signal } from "@/lib/types";


const marketLabels: Record<string, string> = {
  crypto: "加密货币",
  us_stock: "美股",
  a_share: "A 股",
  hk_stock: "港股",
  macro: "宏观",
  unknown: "未分类",
};

interface SubscriptionForm {
  platform: string;
  handle: string;
  accountId: string;
  positionStartAt: string;
  intervalMinutes: string;
  markets: string[];
  systemPrompt: string;
  userPrompt: string;
  outputSchema: string;
  ntfyServer: string;
  ntfyTopic: string;
  enabled: boolean;
}

function newForm(options: AdminConfigOptions): SubscriptionForm {
  const platforms = configurablePlatforms(options.platforms);
  return {
    platform: platforms.includes("x") ? "x" : platforms[0] || "x",
    handle: "",
    accountId: "",
    positionStartAt: "",
    intervalMinutes: String(options.defaultIntervalMinutes),
    markets: [...options.markets],
    systemPrompt: options.defaultSystemPrompt,
    userPrompt: options.defaultUserPrompt,
    outputSchema: JSON.stringify(options.defaultOutputSchema, null, 2),
    ntfyServer: options.defaultNtfyServer,
    ntfyTopic: options.defaultNtfyTopic,
    enabled: true,
  };
}

function subscriptionForm(subscription: AdminSubscription): SubscriptionForm {
  return {
    platform: subscription.platform,
    handle: subscription.handle,
    accountId: subscription.accountId || "",
    positionStartAt: isoToBeijingDateTimeLocal(subscription.positionStartAt),
    intervalMinutes: String(subscription.intervalMinutes),
    markets: subscription.markets,
    systemPrompt: subscription.systemPrompt || subscription.effectiveSystemPrompt,
    userPrompt: subscription.userPrompt || subscription.effectiveUserPrompt,
    outputSchema: JSON.stringify(
      subscription.outputSchema || subscription.effectiveOutputSchema,
      null,
      2,
    ),
    ntfyServer: subscription.ntfyServer || "",
    ntfyTopic: subscription.ntfyTopic || "",
    enabled: subscription.enabled,
  };
}

export function AdminShell({
  assets,
  signals,
  loading,
  error,
}: {
  assets: Asset[];
  signals: Signal[];
  loading: boolean;
  error?: string;
}) {
  const [options, setOptions] = useState<AdminConfigOptions | null>(null);
  const [subscriptions, setSubscriptions] = useState<AdminSubscription[]>([]);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [form, setForm] = useState<SubscriptionForm | null>(null);
  const [message, setMessage] = useState("");
  const [settingsError, setSettingsError] = useState("");
  const [saving, setSaving] = useState(false);
  const [deleting, setDeleting] = useState(false);

  useEffect(() => {
    let active = true;
    Promise.all([fetchAdminConfigOptions(), fetchAdminSubscriptions()])
      .then(([nextOptions, nextSubscriptions]) => {
        if (!active) return;
        setOptions(nextOptions);
        setSubscriptions(nextSubscriptions);
        const first = nextSubscriptions[0];
        if (first) {
          setSelectedId(first.id);
          setForm(subscriptionForm(first));
        } else {
          setForm(newForm(nextOptions));
        }
      })
      .catch((reason) => {
        if (active) {
          setSettingsError(reason instanceof Error ? reason.message : "设置读取失败");
        }
      });
    return () => {
      active = false;
    };
  }, []);

  const stats = useMemo(
    () => [
      { label: "订阅 KOL", value: subscriptions.length, icon: Users },
      { label: "跟踪标的", value: assets.length, icon: Database },
      { label: "结构化信号", value: signals.length, icon: ShieldCheck },
    ],
    [assets.length, signals.length, subscriptions.length],
  );

  function startNew() {
    if (!options) return;
    setSelectedId(null);
    setForm(newForm(options));
    setMessage("");
    setSettingsError("");
  }

  function selectSubscription(subscription: AdminSubscription) {
    setSelectedId(subscription.id);
    setForm(subscriptionForm(subscription));
    setMessage("");
    setSettingsError("");
  }

  function toggleMarket(market: string) {
    if (!form) return;
    const selected = form.markets.includes(market);
    const markets = selected
      ? form.markets.filter((item) => item !== market)
      : [...form.markets, market];
    setForm({ ...form, markets: markets.length ? markets : options?.markets || [] });
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!form) return;
    setSaving(true);
    setMessage("");
    setSettingsError("");
    try {
      let saved: AdminSubscription;
      if (requiresAccountId(form.platform)) {
        if (!form.accountId.trim()) throw new Error("Portfolio ID 不能为空");
        if (!form.positionStartAt) throw new Error("空仓起算时间不能为空");
        const tradeInput = {
          handle: form.handle,
          accountId: form.accountId,
          positionStartAt: form.positionStartAt,
          enabled: form.enabled,
          ntfyServer: form.ntfyServer,
          ntfyTopic: form.ntfyTopic,
        };
        saved = selectedId
          ? await updateBinanceCopySubscription(selectedId, tradeInput)
          : await createBinanceCopySubscription(tradeInput);
      } else {
        const parsedSchema = JSON.parse(form.outputSchema) as Record<string, unknown>;
        if (!parsedSchema || typeof parsedSchema !== "object" || Array.isArray(parsedSchema)) {
          throw new Error("Output schema 必须是 JSON 对象");
        }
        const common = {
          intervalMinutes: Math.max(1, Number(form.intervalMinutes) || 10),
          markets: form.markets,
          systemPrompt: form.systemPrompt,
          userPrompt: form.userPrompt,
          outputSchema: parsedSchema,
          ntfyServer: form.ntfyServer,
          ntfyTopic: form.ntfyTopic,
          enabled: form.enabled,
        };
        saved = selectedId
          ? await updateAdminSubscription(selectedId, common)
          : await createAdminSubscription({
              ...common,
              platform: form.platform,
              handle: form.handle,
            });
      }
      setSubscriptions((current) => {
        const exists = current.some((item) => item.id === saved.id);
        return exists
          ? current.map((item) => (item.id === saved.id ? saved : item))
          : [saved, ...current];
      });
      setSelectedId(saved.id);
      setForm(subscriptionForm(saved));
      setMessage(`已保存 ${saved.handle} 的监控配置`);
    } catch (reason) {
      setSettingsError(reason instanceof Error ? reason.message : "保存失败");
    } finally {
      setSaving(false);
    }
  }

  async function handleDelete() {
    if (!selectedId || !form || !options) return;
    const confirmed = window.confirm(
      `删除 ${platformLabel(form.platform)} ${form.handle} 的监控订阅？历史情报会保留。`,
    );
    if (!confirmed) return;
    setDeleting(true);
    setMessage("");
    setSettingsError("");
    try {
      await deleteAdminSubscription(selectedId);
      const remaining = subscriptions.filter((subscription) => subscription.id !== selectedId);
      setSubscriptions(remaining);
      const next = remaining[0];
      if (next) {
        setSelectedId(next.id);
        setForm(subscriptionForm(next));
      } else {
        setSelectedId(null);
        setForm(newForm(options));
      }
      setMessage(`已删除 ${form.handle} 的监控订阅，历史情报已保留`);
    } catch (reason) {
      setSettingsError(reason instanceof Error ? reason.message : "删除失败");
    } finally {
      setDeleting(false);
    }
  }

  const isTrade = form ? requiresAccountId(form.platform) : false;
  const EditorIcon = isTrade ? Database : Bot;

  return (
    <main className="admin-shell settings-shell">
      <header className="settings-header">
        <div>
          <Link className="back-link" href="/"><ArrowLeft size={14} aria-hidden="true" />返回情报流</Link>
          <p className="eyebrow">Monitor Settings</p>
          <h1>KOL 监控设置</h1>
        </div>
        <div className="settings-header-actions">
          <button type="button" className="settings-new-button" onClick={startNew} disabled={!options}>
            <Plus size={16} aria-hidden="true" />配置订阅
          </button>
        </div>
      </header>

      {error || settingsError ? <div className="state-panel error">{error || settingsError}</div> : null}
      {loading || !form ? <div className="state-panel">正在读取配置...</div> : null}

      <section className="admin-grid" aria-label="管理指标">
        {stats.map((stat) => {
          const Icon = stat.icon;
          return <article className="metric-card" key={stat.label}><Icon size={20} aria-hidden="true" /><strong>{stat.value}</strong><span>{stat.label}</span></article>;
        })}
      </section>

      <CollectorHealthCard health={options?.collectorHealth} />

      {form && options ? (
        <section className="settings-workspace">
          <aside className="settings-subscriptions">
            <div className="settings-section-title"><BellRing size={16} aria-hidden="true" /><h2>监控订阅</h2><span>{subscriptions.length}</span></div>
            <div className="settings-subscription-list">
              {subscriptions.map((subscription) => (
                <button
                  className={selectedId === subscription.id ? "active" : ""}
                  key={subscription.id}
                  type="button"
                  onClick={() => selectSubscription(subscription)}
                >
                  <span className={`source-dot source-dot-${subscription.platform}`} aria-hidden="true" />
                  <div>
                    <strong>{subscription.platform === "x" ? `@${subscription.handle}` : subscription.handle}</strong>
                    <small className="settings-subscription-meta">
                      <span>{platformLabel(subscription.platform)}</span>
                      <span>{subscription.intervalMinutes} 分钟</span>
                    </small>
                  </div>
                  <Edit3 size={14} aria-hidden="true" />
                </button>
              ))}
            </div>
          </aside>

          <form className="settings-editor" onSubmit={handleSubmit}>
            <div className="settings-section-title"><EditorIcon size={17} aria-hidden="true" /><div><p className="eyebrow">{selectedId ? "Edit Subscription" : "New Subscription"}</p><h2>{selectedId ? form.handle : "添加 KOL"}</h2></div></div>

            <div className="settings-basic-grid">
              <label><span>平台</span><select disabled={Boolean(selectedId)} value={form.platform} onChange={(event) => {
                const platform = event.target.value;
                setForm({
                  ...form,
                  platform,
                  accountId: requiresAccountId(platform) ? form.accountId : "",
                  positionStartAt: requiresAccountId(platform)
                    ? form.positionStartAt
                    : "",
                  intervalMinutes: requiresAccountId(platform) ? "1" : form.intervalMinutes,
                  markets: requiresAccountId(platform) ? ["crypto"] : form.markets,
                });
              }}>{configurablePlatforms(options.platforms).map((platform) => <option key={platform} value={platform}>{platformLabel(platform)}</option>)}</select></label>
              <label><span>{isTrade ? "KOL 名称" : "KOL handle"}</span><input disabled={Boolean(selectedId)} required value={form.handle} onChange={(event) => setForm({ ...form, handle: event.target.value })} placeholder={isTrade ? "熬鹰资本" : "senerity"} /></label>
              {isTrade ? <label><span>Portfolio ID</span><input disabled={Boolean(selectedId)} inputMode="numeric" pattern="[0-9]{8,32}" required value={form.accountId} onChange={(event) => setForm({ ...form, accountId: event.target.value })} placeholder="5075281354358777856" /></label> : null}
              {isTrade ? <label><span>空仓起算时间（北京时间）</span><input required step="60" type="datetime-local" value={form.positionStartAt} onChange={(event) => setForm({ ...form, positionStartAt: event.target.value })} /></label> : null}
              <label><span>抓取间隔（分钟）</span><input disabled={isTrade} min="1" type="number" value={form.intervalMinutes} onChange={(event) => setForm({ ...form, intervalMinutes: event.target.value })} /></label>
              <label className="settings-toggle"><input type="checkbox" checked={form.enabled} onChange={(event) => setForm({ ...form, enabled: event.target.checked })} /><span>启用监控</span></label>
            </div>

            {requiresPromptConfiguration(form.platform) ? (
              <>
                <fieldset className="market-selector"><legend>关注市场</legend><div>{options.markets.map((market) => <label className={form.markets.includes(market) ? "selected" : ""} key={market}><input type="checkbox" checked={form.markets.includes(market)} onChange={() => toggleMarket(market)} /><span>{marketLabels[market] || market}</span></label>)}</div></fieldset>
                <div className="prompt-editor">
                  <label><span>System prompt</span><textarea value={form.systemPrompt} onChange={(event) => setForm({ ...form, systemPrompt: event.target.value })} /></label>
                  <label><span>User prompt</span><textarea value={form.userPrompt} onChange={(event) => setForm({ ...form, userPrompt: event.target.value })} /></label>
                  <label><span>Output schema</span><textarea className="schema-editor" spellCheck={false} value={form.outputSchema} onChange={(event) => setForm({ ...form, outputSchema: event.target.value })} /></label>
                </div>
              </>
            ) : (
              <div className="trade-config-summary"><Database size={18} aria-hidden="true" /><div><strong>Binance Copy 使用固定交易账本</strong><span>起算时间视为空仓，只使用此后的成交记录推算仓位。修改时间会重置已推算的仓位与操作记录；首次重建不推送 ntfy。</span></div></div>
            )}

            <div className="settings-basic-grid settings-notify-grid">
              <label><span>ntfy server</span><input value={form.ntfyServer} onChange={(event) => setForm({ ...form, ntfyServer: event.target.value })} placeholder="https://ntfy.sh" /></label>
              <label><span>ntfy topic</span><input value={form.ntfyTopic} onChange={(event) => setForm({ ...form, ntfyTopic: event.target.value })} /></label>
            </div>

            <footer className="settings-actions">
              <span>{message}</span>
              <button type="button" className="settings-delete-button" disabled={!selectedId || saving || deleting} onClick={handleDelete}>
                <Trash2 size={16} aria-hidden="true" />{deleting ? "删除中" : "删除订阅"}
              </button>
              <button type="submit" disabled={saving || deleting}><Save size={16} aria-hidden="true" />{saving ? "保存中" : "保存配置"}</button>
            </footer>
          </form>
        </section>
      ) : null}
    </main>
  );
}
