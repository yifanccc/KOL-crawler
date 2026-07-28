"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { fetchAssets, fetchCollectorHealth, fetchKols, fetchSignals } from "./api";
import { isBlockingRefresh, refreshErrorMessage } from "./refreshPolicy";
import type { Asset, CollectorHealth, Kol, Signal } from "./types";

export function useMarketData() {
  const [signals, setSignals] = useState<Signal[]>([]);
  const [kols, setKols] = useState<Kol[]>([]);
  const [assets, setAssets] = useState<Asset[]>([]);
  const [collectorHealth, setCollectorHealth] = useState<CollectorHealth | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const hasLoadedRef = useRef(false);

  const reload = useCallback(async () => {
    const blocking = isBlockingRefresh(hasLoadedRef.current);
    if (blocking) {
      setLoading(true);
      setError("");
    }
    try {
      const [nextSignals, nextKols, nextAssets, nextCollectorHealth] = await Promise.all([
        fetchSignals(),
        fetchKols(),
        fetchAssets(),
        fetchCollectorHealth(),
      ]);
      setSignals(nextSignals);
      setKols(nextKols);
      setAssets(nextAssets);
      setCollectorHealth(nextCollectorHealth);
      hasLoadedRef.current = true;
      setError("");
    } catch (reason: unknown) {
      const message = reason instanceof Error ? reason.message : "数据加载失败";
      setError(refreshErrorMessage(hasLoadedRef.current, message));
    } finally {
      if (blocking) {
        setLoading(false);
      }
    }
  }, []);

  useEffect(() => {
    void reload();
    const timer = window.setInterval(() => {
      void reload();
    }, 60_000);
    return () => window.clearInterval(timer);
  }, [reload]);

  return { signals, kols, assets, collectorHealth, loading, error, reload };
}
