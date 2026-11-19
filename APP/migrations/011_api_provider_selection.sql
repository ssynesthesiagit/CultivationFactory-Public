-- Provider-neutral selection over the existing per-provider settings rows.
-- The historical DeepSeek row is retained as the default for compatibility.
CREATE TABLE IF NOT EXISTS ai_provider_selection (
    singleton INTEGER PRIMARY KEY CHECK(singleton=1),
    provider_id TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

INSERT OR IGNORE INTO ai_provider_selection(singleton, provider_id, updated_at)
SELECT 1,
       COALESCE((SELECT provider_id FROM ai_provider_settings ORDER BY updated_at DESC LIMIT 1), 'deepseek'),
       datetime('now');
