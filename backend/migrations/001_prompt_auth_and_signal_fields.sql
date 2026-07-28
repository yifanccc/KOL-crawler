ALTER TABLE subscriptions
  ADD COLUMN system_prompt LONGTEXT NULL,
  ADD COLUMN user_prompt LONGTEXT NULL,
  ADD COLUMN output_schema_json LONGTEXT NULL,
  ADD COLUMN markets_json LONGTEXT NULL,
  ADD COLUMN prompt_version VARCHAR(64) NULL;

ALTER TABLE signals
  ADD COLUMN stance_cn VARCHAR(32) NULL,
  ADD COLUMN summary_cn LONGTEXT NULL,
  ADD COLUMN symbols_json LONGTEXT NULL,
  ADD COLUMN market VARCHAR(32) NULL,
  ADD COLUMN key_points_json LONGTEXT NULL,
  ADD COLUMN confidence_score INT NULL,
  ADD COLUMN importance INT NULL,
  ADD COLUMN tags_json LONGTEXT NULL,
  ADD COLUMN action_hint LONGTEXT NULL,
  ADD COLUMN source_language VARCHAR(64) NULL,
  ADD COLUMN translated_text_cn LONGTEXT NULL,
  ADD COLUMN risk_warning LONGTEXT NULL,
  ADD COLUMN prompt_version VARCHAR(64) NULL;
