"use client";

interface TagBadgeProps {
  tag: string;
  onSelect?: (tag: string) => void;
}

export function TagBadge({ tag, onSelect }: TagBadgeProps) {
  if (onSelect) {
    return (
      <button type="button" className="tag-badge" onClick={() => onSelect(tag)}>
        {tag}
      </button>
    );
  }

  return <span className="tag-badge">{tag}</span>;
}
