CREATE TABLE assistant.sessions (
    session_id UUID PRIMARY KEY,
    expires_at TIMESTAMPTZ NOT NULL,
    version INTEGER NOT NULL DEFAULT 0,
    state JSONB NOT NULL DEFAULT '{}'::jsonb
);
CREATE TABLE assistant.messages (
    message_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    session_id UUID NOT NULL REFERENCES assistant.sessions ON DELETE CASCADE,
    user_message TEXT NOT NULL,
    assistant_message TEXT NOT NULL
);
CREATE INDEX ON assistant.messages(session_id, message_id);
CREATE TABLE assistant.recommendation_lists (
    list_id UUID PRIMARY KEY,
    list_order BIGINT GENERATED ALWAYS AS IDENTITY,
    session_id UUID NOT NULL REFERENCES assistant.sessions ON DELETE CASCADE,
    items JSONB NOT NULL
);
CREATE INDEX ON assistant.recommendation_lists(session_id, list_order);
CREATE TABLE assistant.requests (
    session_id UUID NOT NULL REFERENCES assistant.sessions ON DELETE CASCADE,
    request_id UUID NOT NULL,
    input_hash TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('QUEUED','RUNNING','DONE','FAILED')),
    response JSONB,
    PRIMARY KEY (session_id, request_id)
);
