"use client";

import Link from "next/link";
import { FormEvent, useEffect, useState } from "react";
import { ArrowLeft, Clock3, Save, ShieldCheck } from "lucide-react";

import { CollectorHealthCard } from "@/components/CollectorHealthCard";
import {
  createBinanceCopySubscription,
  fetchAdminConfigOptions,
  fetchAdminSubscriptions,
  updateBinanceCopySubscription,
  type BinanceCopySettingsInput,
} from "@/lib/api";
import type { AdminSubscription, CollectorHealth } from "@/lib/types";


const emptyForm: BinanceCopySettingsInput = {
  handle: "",
  accountId: "",
  enabled: true,
  ntfyServer: "",
  ntfyTopic: "",
};

function formFromSubscription(
  subscription: AdminSubscription,
): BinanceCopySettingsInput {
  return {
    handle: subscription.handle,
    accountId: subscription.accountId || "",
    enabled: subscription.enabled,
    ntfyServer: subscription.ntfyServer || "",
    ntfyTopic: subscription.ntfyTopic || "",
  };
}

export function BinanceCopySettings() {
  const [subscription, setSubscription] = useState<AdminSubscription | null>(null);
  const [form, setForm] = useState<BinanceCopySettingsInput>(emptyForm);
  const [collectorHealth, setCollectorHealth] = useState<CollectorHealth | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    let active = true;
    Promise.all([fetchAdminConfigOptions(), fetchAdminSubscriptions()])
      .then(([options, subscriptions]) => {
        if (!active) return;
        const existing =
          subscriptions.find((item) => item.platform === "binance_copy") || null;
        setCollectorHealth(options.collectorHealth || null);
        setSubscription(existing);
        setForm(
          existing
            ? formFromSubscription(existing)
            : {
                ...emptyForm,
                ntfyServer: options.defaultNtfyServer,
                ntfyTopic: options.defaultNtfyTopic,
              },
        );
      })
      .catch((reason: unknown) => {
        if (active) {
          setError(reason instanceof Error ? reason.message : "配置读取失败");
        }
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, []);

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSaving(true);
    setMessage("");
    setError("");
    try {
      const saved = subscription
        ? await updateBinanceCopySubscription(subscription.id, form)
        : await createBinanceCopySubscription(form);
      setSubscription(saved);
      setForm(formFromSubscription(saved));
      setMessage("Binance Copy 监控配置已保存");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "保存失败");
    } finally {
      setSaving(false);
    }
  }

  return (
    <main className="admin-shell settings-shell binance-copy-settings">
      <header className="settings-header">
        <div>
          <Link className="back-link" href="/admin">
            <ArrowLeft size={14} aria-hidden="true" />返回内容订阅设置
          </Link>
          <p className="eyebrow">Private Trade Monitor</p>
          <h1>Binance Copy 监控配置</h1>
          <p className="private-signal-description">
            每 10 分钟读取带单员成交记录，并用确定性规则推测当前持仓。
          </p>
        </div>
      </header>

      {loading ? <div className="state-panel">正在读取 Binance 配置...</div> : null}
      {error ? <div className="state-panel error">{error}</div> : null}

      {!loading ? <CollectorHealthCard health={collectorHealth} /> : null}

      {!loading ? (
        <form className="settings-editor binance-copy-editor" onSubmit={save}>
          <div className="trade-config-summary" role="note">
            <Clock3 size={18} aria-hidden="true" />
            <div>
              <strong>固定 10 分钟采集</strong>
              <span>首轮建立基线，后续成交变化会更新推测持仓。</span>
            </div>
          </div>

          <div className="settings-section-title">
            <ShieldCheck size={17} aria-hidden="true" />
            <div>
              <p className="eyebrow">Account Identity</p>
              <h2>{subscription ? form.handle : "添加私域带单员"}</h2>
            </div>
          </div>

          <div className="settings-basic-grid">
            <label>
              <span>KOL 昵称</span>
              <input
                disabled={Boolean(subscription)}
                required
                value={form.handle}
                onChange={(event) => setForm({ ...form, handle: event.target.value })}
                placeholder="熬鹰资本"
              />
            </label>
            <label>
              <span>Portfolio ID</span>
              <input
                disabled={Boolean(subscription)}
                inputMode="numeric"
                pattern="[0-9]{8,32}"
                required
                value={form.accountId}
                onChange={(event) =>
                  setForm({ ...form, accountId: event.target.value })
                }
                placeholder="5075281354358777856"
              />
            </label>
            <label>
              <span>抓取间隔</span>
              <input disabled value="10 分钟（固定）" readOnly />
            </label>
            <label className="settings-toggle">
              <input
                type="checkbox"
                checked={form.enabled}
                onChange={(event) =>
                  setForm({ ...form, enabled: event.target.checked })
                }
              />
              <span>启用监控</span>
            </label>
          </div>

          <div className="settings-basic-grid settings-notify-grid">
            <label>
              <span>ntfy server</span>
              <input
                value={form.ntfyServer}
                onChange={(event) =>
                  setForm({ ...form, ntfyServer: event.target.value })
                }
                placeholder="https://ntfy.sh"
              />
            </label>
            <label>
              <span>ntfy topic</span>
              <input
                value={form.ntfyTopic}
                onChange={(event) =>
                  setForm({ ...form, ntfyTopic: event.target.value })
                }
              />
            </label>
          </div>

          <footer className="settings-actions">
            <span aria-live="polite">{message}</span>
            <button type="submit" disabled={saving}>
              <Save size={16} aria-hidden="true" />
              {saving ? "保存中" : "保存配置"}
            </button>
          </footer>
        </form>
      ) : null}
    </main>
  );
}
