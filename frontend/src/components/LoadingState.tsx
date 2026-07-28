"use client";

export function LoadingState() {
  return (
    <div className="feed-skeleton" aria-busy="true" aria-label="正在加载 KOL 情报">
      {Array.from({ length: 4 }).map((_, index) => (
        <div className="skeleton-card" key={index}>
          <span />
          <strong />
          <p />
          <p />
        </div>
      ))}
    </div>
  );
}
