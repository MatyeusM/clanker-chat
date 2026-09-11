PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS channels (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    owner_password_hash TEXT,
    channel_password_hash TEXT
);

CREATE TABLE IF NOT EXISTS channel_members (
    channel_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    joined_at INTEGER NOT NULL,
    UNIQUE (channel_id, user_id),
    FOREIGN KEY (channel_id) REFERENCES channels(id) ON DELETE CASCADE,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS channel_owners (
    channel_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    UNIQUE (channel_id, user_id),
    FOREIGN KEY (channel_id) REFERENCES channels(id) ON DELETE CASCADE,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY,
    last_nickname TEXT NOT NULL,
    last_ip TEXT NOT NULL,
    last_seen INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS attachments (
    id INTEGER PRIMARY KEY,
    filename TEXT NOT NULL,
    mime_type TEXT NOT NULL,
    uploaded_at INTEGER NOT NULL,
    location TEXT NOT NULL,
    size INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY,
    channel_id INTEGER NOT NULL,
    author_id INTEGER NOT NULL,
    content TEXT NOT NULL,
    attachment_id INTEGER,
    created_at INTEGER NOT NULL,

    FOREIGN KEY (channel_id) REFERENCES channels(id) ON DELETE CASCADE,
    FOREIGN KEY (author_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_messages_channel_created
    ON messages(channel_id, created_at);

CREATE INDEX IF NOT EXISTS idx_attachments_uploaded
    ON attachments(uploaded_at);
