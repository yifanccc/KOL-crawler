import type { Signal, SignalPage } from "./types";

export const SIGNAL_BATCH_SIZE = 20;

function uniqueSignals(groups: Signal[][]): Signal[] {
  const seen = new Set<string>();
  return groups.flat().filter((signal) => {
    if (seen.has(signal.id)) return false;
    seen.add(signal.id);
    return true;
  });
}

export function nextSignalOffset(page: SignalPage): number {
  return page.items.length ? page.offset + page.items.length : page.total;
}

export function appendSignalPage(
  current: SignalPage,
  next: SignalPage,
): { page: SignalPage; nextOffset: number } {
  const items = uniqueSignals([current.items, next.items]).slice(0, next.total);
  return {
    page: {
      ...next,
      items,
      offset: 0,
    },
    nextOffset: nextSignalOffset(next),
  };
}

export function refreshSignalPage(current: SignalPage, refreshed: SignalPage): SignalPage {
  return {
    ...refreshed,
    items: uniqueSignals([refreshed.items, current.items]).slice(0, refreshed.total),
  };
}

export function hasMoreSignals(nextOffset: number, total: number): boolean {
  return nextOffset < total;
}

export function loadedSignalsLabel(itemCount: number, total: number): string {
  return `已加载 ${Math.min(itemCount, total)} / ${total}`;
}
