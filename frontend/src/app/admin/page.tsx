"use client";

import { useEffect, useState } from "react";
import { AdminShell } from "@/components/AdminShell";
import { fetchAssets, fetchSignals } from "@/lib/api";
import type { Asset, Signal } from "@/lib/types";

export default function AdminPage() {
  const [signals, setSignals] = useState<Signal[]>([]);
  const [assets, setAssets] = useState<Asset[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    let active = true;
    Promise.all([fetchSignals(), fetchAssets()])
      .then(([nextSignals, nextAssets]) => {
        if (!active) return;
        setSignals(nextSignals);
        setAssets(nextAssets);
      })
      .catch((reason: unknown) => {
        if (!active) return;
        setError(reason instanceof Error ? reason.message : "数据加载失败");
      })
      .finally(() => {
        if (active) setLoading(false);
      });

    return () => {
      active = false;
    };
  }, []);

  return <AdminShell assets={assets} signals={signals} loading={loading} error={error} />;
}
