ALTER TABLE raw_posts
  ADD COLUMN subscription_id BIGINT NULL,
  ADD COLUMN analysis_status VARCHAR(32) NOT NULL DEFAULT 'pending',
  ADD COLUMN analysis_error LONGTEXT NULL,
  ADD COLUMN analysis_attempts INT NOT NULL DEFAULT 0,
  ADD COLUMN analyzed_at DATETIME NULL;

ALTER TABLE kol_profiles
  ADD COLUMN avatar_url VARCHAR(1024) NULL;

UPDATE raw_posts
SET analysis_status = 'pending'
WHERE analysis_status IS NULL OR analysis_status = '';

UPDATE raw_posts
SET analysis_status = 'completed',
    analyzed_at = COALESCE(analyzed_at, created_at)
WHERE EXISTS (
  SELECT 1
  FROM signals
  WHERE signals.raw_post_id = raw_posts.id
);
