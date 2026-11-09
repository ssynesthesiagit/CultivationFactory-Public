ALTER TABLE character_creation_runs ADD COLUMN owner_descriptive_fields_json TEXT NOT NULL DEFAULT '{}';
ALTER TABLE character_creation_runs ADD COLUMN accepted_descriptive_fields_json TEXT NOT NULL DEFAULT '{}';
