#!/usr/bin/env python3
# LOOM Messenger - Full Backend
# Запуск: python server.py

import json
import sqlite3
import hashlib
import uuid
import os
from datetime import datetime
from typing import List, Optional
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import uvicorn

# === ИНИЦИАЛИЗАЦИЯ ===
app = FastAPI(title="LOOM Messenger API", version="1.0.0")

# Разрешаем CORS для всех доменов (для разработки)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

DB_PATH = "loom.db"
os.makedirs("uploads", exist_ok=True)

# === БАЗА ДАННЫХ ===
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    conn.executescript('''
        CREATE TABLE IF NOT EXISTS users (
            id TEXT PRIMARY KEY,
            phone TEXT UNIQUE NOT NULL,
            name TEXT NOT NULL,
            password_hash TEXT NOT NULL,
            avatar TEXT DEFAULT '',
            status TEXT DEFAULT 'online',
            online INTEGER DEFAULT 0,
            last_seen TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS chats (
            id TEXT PRIMARY KEY,
            name TEXT,
            type TEXT DEFAULT 'private',
            avatar TEXT DEFAULT '',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS chat_members (
            chat_id TEXT,
            user_id TEXT,
            role TEXT DEFAULT 'member',
            joined_at TEXT DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (chat_id, user_id)
        );

        CREATE TABLE IF NOT EXISTS messages (
            id TEXT PRIMARY KEY,
            chat_id TEXT NOT NULL,
            sender_id TEXT NOT NULL,
            text TEXT,
            file_url TEXT,
            file_type TEXT,
            reply_to TEXT,
            read_by TEXT DEFAULT '',
            deleted_for TEXT DEFAULT '',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT,
            FOREIGN KEY (chat_id) REFERENCES chats(id),
            FOREIGN KEY (sender_id) REFERENCES users(id)
        );

        CREATE TABLE IF NOT EXISTS reactions (
            id TEXT PRIMARY KEY,
            message_id TEXT NOT NULL,
            user_id TEXT NOT NULL,
            emoji TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (message_id) REFERENCES messages(id),
            FOREIGN KEY (user_id) REFERENCES users(id),
            UNIQUE(message_id, user_id)
        );

        CREATE TABLE IF NOT EXISTS contacts (
            user_id TEXT,
            contact_id TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (user_id, contact_id),
            FOREIGN KEY (user_id) REFERENCES users(id),
            FOREIGN KEY (contact_id) REFERENCES users(id)
        );

        CREATE TABLE IF NOT EXISTS pinned_chats (
            user_id TEXT,
            chat_id TEXT,
            order_num INTEGER DEFAULT 0,
            PRIMARY KEY (user_id, chat_id),
            FOREIGN KEY (user_id) REFERENCES users(id),
            FOREIGN KEY (chat_id) REFERENCES chats(id)
        );

        CREATE TABLE IF NOT EXISTS archived_chats (
            user_id TEXT,
            chat_id TEXT,
            PRIMARY KEY (user_id, chat_id),
            FOREIGN KEY (user_id) REFERENCES users(id),
            FOREIGN KEY (chat_id) REFERENCES chats(id)
        );

        CREATE TABLE IF NOT EXISTS calls (
            id TEXT PRIMARY KEY,
            caller_id TEXT NOT NULL,
            receiver_id TEXT NOT NULL,
            type TEXT CHECK(type IN ('audio', 'video')),
            duration INTEGER DEFAULT 0,
            status TEXT CHECK(status IN ('ringing', 'active', 'ended', 'missed')),
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (caller_id) REFERENCES users(id),
            FOREIGN KEY (receiver_id) REFERENCES users(id)
        );

        CREATE TABLE IF NOT EXISTS blocked (
            user_id TEXT,
            blocked_id TEXT,
            PRIMARY KEY (user_id, blocked_id),
            FOREIGN KEY (user_id) REFERENCES users(id),
            FOREIGN KEY (blocked_id) REFERENCES users(id)
        );

        CREATE TABLE IF NOT EXISTS typing_status (
            chat_id TEXT,
            user_id TEXT,
            is_typing INTEGER DEFAULT 0,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (chat_id, user_id)
        );
    ''')
    conn.commit()
    conn.close()

init_db()

# === МОДЕЛИ ===
class UserRegister(BaseModel):
    phone: str
    name: str
    password: str

class UserLogin(BaseModel):
    phone: str
    password: str

class MessageCreate(BaseModel):
    chat_id: str
    text: Optional[str] = None
    reply_to: Optional[str] = None

class ChatCreate(BaseModel):
    name: Optional[str] = None
    type: str = "private"
    members: List[str]

class ReactionCreate(BaseModel):
    emoji: str

# === ВЕБСОКЕТ МЕНЕДЖЕР ===
class ConnectionManager:
    def __init__(self):
        self.active_connections: dict = {}
        self.user_chats: dict = {}

    async def connect(self, user_id: str, websocket: WebSocket):
        await websocket.accept()
        self.active_connections[user_id] = websocket
        # Обновляем статус в БД
        conn = get_db()
        conn.execute("UPDATE users SET online = 1, last_seen = CURRENT_TIMESTAMP WHERE id = ?", (user_id,))
        conn.commit()
        conn.close()
        # Уведомляем всех о статусе
        await self.broadcast_status(user_id, True)

    def disconnect(self, user_id: str):
        if user_id in self.active_connections:
            del self.active_connections[user_id]
        # Обновляем статус в БД
        conn = get_db()
        conn.execute("UPDATE users SET online = 0, last_seen = CURRENT_TIMESTAMP WHERE id = ?", (user_id,))
        conn.commit()
        conn.close()
        asyncio.create_task(self.broadcast_status(user_id, False))

    async def send_to_user(self, user_id: str, data: dict):
        if user_id in self.active_connections:
            await self.active_connections[user_id].send_text(json.dumps(data))

    async def broadcast_to_chat(self, chat_id: str, data: dict):
        conn = get_db()
        members = conn.execute("SELECT user_id FROM chat_members WHERE chat_id = ?", (chat_id,)).fetchall()
        conn.close()
        for member in members:
            await self.send_to_user(member['user_id'], data)

    async def broadcast_status(self, user_id: str, online: bool):
        status_data = {
            "type": "status",
            "user_id": user_id,
            "online": online,
            "last_seen": datetime.now().isoformat()
        }
        for uid, ws in self.active_connections.items():
            if uid != user_id:
                await ws.send_text(json.dumps(status_data))

manager = ConnectionManager()

# === АСИНХРОННЫЙ ИМПОРТ ДЛЯ WEBSOCKET ===
import asyncio

# === API ЭНДПОИНТЫ ===

# --- Аутентификация ---
@app.post("/api/register")
async def register(user: UserRegister):
    conn = get_db()
    existing = conn.execute("SELECT id FROM users WHERE phone = ?", (user.phone,)).fetchone()
    if existing:
        conn.close()
        raise HTTPException(status_code=400, detail="Phone already registered")
    
    user_id = str(uuid.uuid4())
    password_hash = hashlib.sha256(user.password.encode()).hexdigest()
    conn.execute(
        "INSERT INTO users (id, phone, name, password_hash) VALUES (?, ?, ?, ?)",
        (user_id, user.phone, user.name, password_hash)
    )
    conn.commit()
    conn.close()
    return {"id": user_id, "phone": user.phone, "name": user.name}

@app.post("/api/login")
async def login(user: UserLogin):
    conn = get_db()
    db_user = conn.execute(
        "SELECT id, phone, name, avatar, status FROM users WHERE phone = ?",
        (user.phone,)
    ).fetchone()
    if not db_user:
        conn.close()
        raise HTTPException(status_code=400, detail="User not found")
    
    password_hash = hashlib.sha256(user.password.encode()).hexdigest()
    stored_hash = conn.execute(
        "SELECT password_hash FROM users WHERE id = ?",
        (db_user['id'],)
    ).fetchone()['password_hash']
    
    if stored_hash != password_hash:
        conn.close()
        raise HTTPException(status_code=400, detail="Wrong password")
    
    conn.close()
    return dict(db_user)

# --- Пользователи ---
@app.get("/api/users")
async def get_users():
    conn = get_db()
    users = conn.execute(
        "SELECT id, phone, name, avatar, status, online FROM users"
    ).fetchall()
    conn.close()
    return [dict(u) for u in users]

@app.get("/api/users/{user_id}")
async def get_user(user_id: str):
    conn = get_db()
    user = conn.execute(
        "SELECT id, phone, name, avatar, status, online FROM users WHERE id = ?",
        (user_id,)
    ).fetchone()
    conn.close()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return dict(user)

@app.put("/api/users/{user_id}")
async def update_user(user_id: str, name: Optional[str] = None, avatar: Optional[str] = None):
    conn = get_db()
    if name:
        conn.execute("UPDATE users SET name = ? WHERE id = ?", (name, user_id))
    if avatar is not None:
        conn.execute("UPDATE users SET avatar = ? WHERE id = ?", (avatar, user_id))
    conn.commit()
    conn.close()
    return {"success": True}

# --- Чаты ---
@app.post("/api/chats")
async def create_chat(chat: ChatCreate):
    conn = get_db()
    chat_id = str(uuid.uuid4())
    
    # Проверяем, существует ли уже приватный чат
    if chat.type == "private" and len(chat.members) == 2:
        existing = conn.execute('''
            SELECT c.id FROM chats c
            JOIN chat_members cm1 ON c.id = cm1.chat_id
            JOIN chat_members cm2 ON c.id = cm2.chat_id
            WHERE c.type = 'private' 
            AND cm1.user_id = ? AND cm2.user_id = ?
        ''', (chat.members[0], chat.members[1])).fetchone()
        if existing:
            conn.close()
            return {"id": existing['id']}
    
    conn.execute(
        "INSERT INTO chats (id, type, name) VALUES (?, ?, ?)",
        (chat_id, chat.type, chat.name)
    )
    for member in chat.members:
        conn.execute(
            "INSERT INTO chat_members (chat_id, user_id) VALUES (?, ?)",
            (chat_id, member)
        )
    conn.commit()
    conn.close()
    return {"id": chat_id}

@app.get("/api/chats/{user_id}")
async def get_chats(user_id: str):
    conn = get_db()
    chats = conn.execute('''
        SELECT 
            c.id, 
            c.name, 
            c.type, 
            c.avatar,
            (SELECT text FROM messages WHERE chat_id = c.id ORDER BY created_at DESC LIMIT 1) as last_message,
            (SELECT created_at FROM messages WHERE chat_id = c.id ORDER BY created_at DESC LIMIT 1) as last_time,
            (SELECT COUNT(*) FROM messages WHERE chat_id = c.id AND read_by NOT LIKE ?) as unread,
            (SELECT MAX(created_at) FROM messages WHERE chat_id = c.id AND sender_id != ?) as last_incoming
        FROM chats c
        JOIN chat_members cm ON c.id = cm.chat_id
        WHERE cm.user_id = ?
        ORDER BY last_time DESC
    ''', (f'%{user_id}%', user_id, user_id)).fetchall()
    conn.close()
    
    result = []
    for chat in chats:
        chat_dict = dict(chat)
        # Получаем имя для приватного чата
        if chat['type'] == 'private':
            conn = get_db()
            other = conn.execute('''
                SELECT u.id, u.name, u.avatar, u.status, u.online FROM users u
                JOIN chat_members cm ON u.id = cm.user_id
                WHERE cm.chat_id = ? AND u.id != ?
            ''', (chat['id'], user_id)).fetchone()
            conn.close()
            if other:
                chat_dict['other_user'] = dict(other)
                chat_dict['name'] = other['name']
                chat_dict['avatar'] = other['avatar']
        result.append(chat_dict)
    return result

# --- Сообщения ---
@app.post("/api/messages")
async def send_message(msg: MessageCreate):
    conn = get_db()
    msg_id = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO messages (id, chat_id, sender_id, text, reply_to) VALUES (?, ?, ?, ?, ?)",
        (msg_id, msg.chat_id, "system", msg.text, msg.reply_to)
    )
    conn.commit()
    conn.close()
    
    # Отправляем через WebSocket
    await manager.broadcast_to_chat(msg.chat_id, {
        "type": "message",
        "id": msg_id,
        "chat_id": msg.chat_id,
        "text": msg.text,
        "created_at": datetime.now().isoformat()
    })
    return {"id": msg_id}

@app.get("/api/messages/{chat_id}")
async def get_messages(chat_id: str, limit: int = 50, offset: int = 0):
    conn = get_db()
    messages = conn.execute('''
        SELECT m.*, u.name as sender_name, u.avatar as sender_avatar
        FROM messages m
        JOIN users u ON m.sender_id = u.id
        WHERE m.chat_id = ? AND (m.deleted_for IS NULL OR m.deleted_for = '')
        ORDER BY m.created_at DESC
        LIMIT ? OFFSET ?
    ''', (chat_id, limit, offset)).fetchall()
    conn.close()
    
    result = []
    for msg in messages:
        msg_dict = dict(msg)
        # Получаем реакции
        conn = get_db()
        reactions = conn.execute(
            "SELECT user_id, emoji FROM reactions WHERE message_id = ?",
            (msg['id'],)
        ).fetchall()
        conn.close()
        msg_dict['reactions'] = [{"user_id": r['user_id'], "emoji": r['emoji']} for r in reactions]
        result.append(msg_dict)
    return result

@app.put("/api/messages/{message_id}")
async def edit_message(message_id: str, text: str):
    conn = get_db()
    conn.execute(
        "UPDATE messages SET text = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
        (text, message_id)
    )
    conn.commit()
    conn.close()
    return {"success": True}

@app.delete("/api/messages/{message_id}")
async def delete_message(message_id: str, user_id: str, delete_for_all: bool = False):
    conn = get_db()
    if delete_for_all:
        conn.execute("DELETE FROM messages WHERE id = ?", (message_id,))
    else:
        conn.execute(
            "UPDATE messages SET deleted_for = ? WHERE id = ?",
            (user_id, message_id)
        )
    conn.commit()
    conn.close()
    return {"success": True}

# --- Реакции ---
@app.post("/api/reactions/{message_id}")
async def add_reaction(message_id: str, user_id: str, reaction: ReactionCreate):
    conn = get_db()
    existing = conn.execute(
        "SELECT id FROM reactions WHERE message_id = ? AND user_id = ?",
        (message_id, user_id)
    ).fetchone()
    
    if existing:
        conn.execute(
            "UPDATE reactions SET emoji = ? WHERE message_id = ? AND user_id = ?",
            (reaction.emoji, message_id, user_id)
        )
    else:
        reaction_id = str(uuid.uuid4())
        conn.execute(
            "INSERT INTO reactions (id, message_id, user_id, emoji) VALUES (?, ?, ?, ?)",
            (reaction_id, message_id, user_id, reaction.emoji)
        )
    conn.commit()
    conn.close()
    return {"success": True}

@app.delete("/api/reactions/{message_id}")
async def remove_reaction(message_id: str, user_id: str):
    conn = get_db()
    conn.execute(
        "DELETE FROM reactions WHERE message_id = ? AND user_id = ?",
        (message_id, user_id)
    )
    conn.commit()
    conn.close()
    return {"success": True}

# --- Контакты ---
@app.post("/api/contacts")
async def add_contact(user_id: str, contact_id: str):
    conn = get_db()
    conn.execute(
        "INSERT OR IGNORE INTO contacts (user_id, contact_id) VALUES (?, ?)",
        (user_id, contact_id)
    )
    conn.commit()
    conn.close()
    return {"success": True}

@app.get("/api/contacts/{user_id}")
async def get_contacts(user_id: str):
    conn = get_db()
    contacts = conn.execute('''
        SELECT u.id, u.phone, u.name, u.avatar, u.status, u.online
        FROM contacts c
        JOIN users u ON c.contact_id = u.id
        WHERE c.user_id = ?
    ''', (user_id,)).fetchall()
    conn.close()
    return [dict(c) for c in contacts]

# --- Чат pinned/archived ---
@app.post("/api/pinned")
async def pin_chat(user_id: str, chat_id: str):
    conn = get_db()
    # Получаем максимальный order
    max_order = conn.execute(
        "SELECT MAX(order_num) FROM pinned_chats WHERE user_id = ?",
        (user_id,)
    ).fetchone()[0] or 0
    conn.execute(
        "INSERT OR REPLACE INTO pinned_chats (user_id, chat_id, order_num) VALUES (?, ?, ?)",
        (user_id, chat_id, max_order + 1)
    )
    conn.commit()
    conn.close()
    return {"success": True}

@app.delete("/api/pinned")
async def unpin_chat(user_id: str, chat_id: str):
    conn = get_db()
    conn.execute(
        "DELETE FROM pinned_chats WHERE user_id = ? AND chat_id = ?",
        (user_id, chat_id)
    )
    conn.commit()
    conn.close()
    return {"success": True}

@app.post("/api/archived")
async def archive_chat(user_id: str, chat_id: str):
    conn = get_db()
    conn.execute(
        "INSERT OR IGNORE INTO archived_chats (user_id, chat_id) VALUES (?, ?)",
        (user_id, chat_id)
    )
    conn.commit()
    conn.close()
    return {"success": True}

@app.delete("/api/archived")
async def unarchive_chat(user_id: str, chat_id: str):
    conn = get_db()
    conn.execute(
        "DELETE FROM archived_chats WHERE user_id = ? AND chat_id = ?",
        (user_id, chat_id)
    )
    conn.commit()
    conn.close()
    return {"success": True}

# --- Звонки ---
@app.post("/api/calls")
async def create_call(caller_id: str, receiver_id: str, call_type: str = "audio"):
    call_id = str(uuid.uuid4())
    conn = get_db()
    conn.execute(
        "INSERT INTO calls (id, caller_id, receiver_id, type, status) VALUES (?, ?, ?, ?, 'ringing')",
        (call_id, caller_id, receiver_id, call_type)
    )
    conn.commit()
    conn.close()
    
    # Уведомляем получателя через WebSocket
    await manager.send_to_user(receiver_id, {
        "type": "call",
        "call_id": call_id,
        "caller_id": caller_id,
        "type": call_type
    })
    return {"call_id": call_id}

@app.put("/api/calls/{call_id}")
async def update_call(call_id: str, status: str, duration: Optional[int] = None):
    conn = get_db()
    if duration is not None:
        conn.execute(
            "UPDATE calls SET status = ?, duration = ? WHERE id = ?",
            (status, duration, call_id)
        )
    else:
        conn.execute(
            "UPDATE calls SET status = ? WHERE id = ?",
            (status, call_id)
        )
    conn.commit()
    conn.close()
    return {"success": True}

@app.get("/api/calls/{user_id}")
async def get_calls(user_id: str):
    conn = get_db()
    calls = conn.execute('''
        SELECT c.*, 
               u1.name as caller_name, 
               u2.name as receiver_name
        FROM calls c
        JOIN users u1 ON c.caller_id = u1.id
        JOIN users u2 ON c.receiver_id = u2.id
        WHERE c.caller_id = ? OR c.receiver_id = ?
        ORDER BY c.created_at DESC
        LIMIT 100
    ''', (user_id, user_id)).fetchall()
    conn.close()
    return [dict(c) for c in calls]

# --- Поиск ---
@app.get("/api/search")
async def search(q: str, user_id: Optional[str] = None):
    conn = get_db()
    # Поиск по пользователям
    users = conn.execute('''
        SELECT id, phone, name, avatar FROM users
        WHERE (name LIKE ? OR phone LIKE ?)
        AND id != ?
        LIMIT 20
    ''', (f'%{q}%', f'%{q}%', user_id or '')).fetchall()
    
    # Поиск по сообщениям (для конкретного пользователя)
    messages = []
    if user_id:
        messages = conn.execute('''
            SELECT m.*, c.id as chat_id, u.name as sender_name
            FROM messages m
            JOIN chats c ON m.chat_id = c.id
            JOIN chat_members cm ON c.id = cm.chat_id
            JOIN users u ON m.sender_id = u.id
            WHERE cm.user_id = ? AND m.text LIKE ?
            ORDER BY m.created_at DESC
            LIMIT 50
        ''', (user_id, f'%{q}%')).fetchall()
    
    conn.close()
    return {
        "users": [dict(u) for u in users],
        "messages": [dict(m) for m in messages]
    }

# --- Статус "печатает" ---
@app.post("/api/typing")
async def set_typing(chat_id: str, user_id: str, is_typing: bool):
    conn = get_db()
    conn.execute('''
        INSERT OR REPLACE INTO typing_status (chat_id, user_id, is_typing, updated_at)
        VALUES (?, ?, ?, CURRENT_TIMESTAMP)
    ''', (chat_id, user_id, 1 if is_typing else 0))
    conn.commit()
    conn.close()
    
    await manager.broadcast_to_chat(chat_id, {
        "type": "typing",
        "chat_id": chat_id,
        "user_id": user_id,
        "is_typing": is_typing
    })
    return {"success": True}

# === WEB SOCKET ===
@app.websocket("/ws/{user_id}")
async def websocket_endpoint(websocket: WebSocket, user_id: str):
    await manager.connect(user_id, websocket)
    try:
        while True:
            data = await websocket.receive_text()
            try:
                msg = json.loads(data)
                msg_type = msg.get("type")
                
                if msg_type == "message":
                    # Сохраняем сообщение в БД
                    conn = get_db()
                    msg_id = str(uuid.uuid4())
                    conn.execute(
                        "INSERT INTO messages (id, chat_id, sender_id, text) VALUES (?, ?, ?, ?)",
                        (msg_id, msg['chat_id'], user_id, msg['text'])
                    )
                    conn.commit()
                    conn.close()
                    
                    # Отправляем всем в чате
                    await manager.broadcast_to_chat(msg['chat_id'], {
                        "type": "message",
                        "id": msg_id,
                        "chat_id": msg['chat_id'],
                        "sender_id": user_id,
                        "text": msg['text'],
                        "created_at": datetime.now().isoformat()
                    })
                
                elif msg_type == "typing":
                    await manager.broadcast_to_chat(msg['chat_id'], {
                        "type": "typing",
                        "chat_id": msg['chat_id'],
                        "user_id": user_id,
                        "is_typing": msg.get('is_typing', True)
                    })
                
                elif msg_type == "read":
                    conn = get_db()
                    conn.execute(
                        "UPDATE messages SET read_by = read_by || ? || ',' WHERE chat_id = ? AND sender_id != ?",
                        (user_id, msg['chat_id'], user_id)
                    )
                    conn.commit()
                    conn.close()
                    
                    await manager.broadcast_to_chat(msg['chat_id'], {
                        "type": "read",
                        "chat_id": msg['chat_id'],
                        "user_id": user_id
                    })
                
                elif msg_type == "delete":
                    conn = get_db()
                    if msg.get('delete_for_all', False):
                        conn.execute("DELETE FROM messages WHERE id = ?", (msg['message_id'],))
                    else:
                        conn.execute(
                            "UPDATE messages SET deleted_for = ? WHERE id = ?",
                            (user_id, msg['message_id'])
                        )
                    conn.commit()
                    conn.close()
                    
                    await manager.broadcast_to_chat(msg['chat_id'], {
                        "type": "delete",
                        "message_id": msg['message_id'],
                        "chat_id": msg['chat_id'],
                        "user_id": user_id
                    })
                    
            except Exception as e:
                print(f"Error processing message: {e}")
                
    except WebSocketDisconnect:
        manager.disconnect(user_id)

# === ОТДАЧА СТАТИКИ ===
app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")

@app.get("/")
async def root():
    return {
        "name": "LOOM Messenger API",
        "version": "1.0.0",
        "status": "running",
        "endpoints": {
            "register": "/api/register",
            "login": "/api/login",
            "users": "/api/users",
            "chats": "/api/chats/{user_id}",
            "messages": "/api/messages/{chat_id}",
            "ws": "/ws/{user_id}"
        }
    }

# === ЗАПУСК ===
if __name__ == "__main__":
    print("🚀 LOOM Server запущен на http://localhost:8000")
    print("📊 Документация: http://localhost:8000/docs")
    uvicorn.run(app, host="0.0.0.0", port=8000)
