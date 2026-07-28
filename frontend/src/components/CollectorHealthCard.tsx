import type { CollectorHealth } from "@/lib/types";

function formatLastSeen(value: string) {
  const timestamp = new Date(value).getTime();
  if (Number.isNaN(timestamp)) return value;
  const minutes = Math.max(0, Math.floor((Date.now() - timestamp) / 60_000));
  if (minutes < 1) return "刚刚";
  if (minutes < 60) return `${minutes} 分钟前`;
  return `${Math.floor(minutes / 60)} 小时前`;
}

export function CollectorHealthCard({ health }: { health?: CollectorHealth | null }) {
  return (
    <section className="collector-health-card" aria-label="本地采集器状态">
      <div>
        <span className="terminal-label">Local Collector</span>
        <h2>采集器状态</h2>
      </div>
      {health ? (
        <>
          <p>{health.status === "healthy" ? "运行正常" : health.status}</p>
          <dl>
            <div><dt>最后心跳</dt><dd>{formatLastSeen(health.lastSeenAt)}</dd></div>
            <div><dt>待上传</dt><dd>{health.outboxPending}</dd></div>
          </dl>
          {health.providers.length ? (
            <ul>
              {health.providers.map((provider) => (
                <li key={provider.platform}>
                  <span>{provider.platform}</span>
                  <strong>{provider.status}</strong>
                  {provider.message ? <small>{provider.message}</small> : null}
                </li>
              ))}
            </ul>
          ) : null}
        </>
      ) : (
        <p>尚未收到本地采集器心跳。</p>
      )}
    </section>
  );
}
