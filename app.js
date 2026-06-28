// LOOM Messenger - Full Mobile Client
// Запуск: npx expo start

import React, { useState, useEffect, useRef } from 'react';
import {
  View,
  Text,
  TextInput,
  TouchableOpacity,
  FlatList,
  Image,
  StyleSheet,
  SafeAreaView,
  Alert,
  ActivityIndicator,
  Modal,
  KeyboardAvoidingView,
  Platform,
  StatusBar,
  ScrollView,
} from 'react-native';

const API_URL = 'https://ВАШ_СЕРВЕР.onrender.com'; // ЗАМЕНИТЬ!
const WS_URL = 'wss://ВАШ_СЕРВЕР.onrender.com';   // ЗАМЕНИТЬ!

// --- ЭКРАН ВХОДА ---
function LoginScreen({ onLogin }) {
  const [phone, setPhone] = useState('');
  const [password, setPassword] = useState('');
  const [loading, setLoading] = useState(false);
  const [isRegister, setIsRegister] = useState(false);

  const handleSubmit = async () => {
    if (!phone || !password) {
      Alert.alert('Ошибка', 'Заполните все поля');
      return;
    }
    setLoading(true);
    try {
      const endpoint = isRegister ? '/api/register' : '/api/login';
      const res = await fetch(`${API_URL}${endpoint}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ phone, name: phone, password }),
      });
      const data = await res.json();
      if (res.ok) {
        if (isRegister) {
          Alert.alert('Успех', 'Аккаунт создан!');
          setIsRegister(false);
        } else {
          onLogin(data);
        }
      } else {
        Alert.alert('Ошибка', data.detail || 'Неверные данные');
      }
    } catch {
      Alert.alert('Ошибка', 'Сервер недоступен');
    }
    setLoading(false);
  };

  return (
    <SafeAreaView style={styles.container}>
      <View style={styles.loginBox}>
        <Text style={styles.logo}>🚀 LOOM</Text>
        <Text style={styles.slogan}>Бесплатный мессенджер</Text>
        <TextInput
          style={styles.input}
          placeholder="Телефон"
          placeholderTextColor="#666"
          value={phone}
          onChangeText={setPhone}
          keyboardType="phone-pad"
        />
        <TextInput
          style={styles.input}
          placeholder="Пароль"
          placeholderTextColor="#666"
          value={password}
          onChangeText={setPassword}
          secureTextEntry
        />
        <TouchableOpacity style={styles.button} onPress={handleSubmit} disabled={loading}>
          <Text style={styles.buttonText}>
            {loading ? 'Загрузка...' : isRegister ? 'Зарегистрироваться' : 'Войти'}
          </Text>
        </TouchableOpacity>
        <TouchableOpacity onPress={() => setIsRegister(!isRegister)}>
          <Text style={styles.link}>
            {isRegister ? 'Уже есть аккаунт? Войти' : 'Нет аккаунта? Зарегистрироваться'}
          </Text>
        </TouchableOpacity>
      </View>
    </SafeAreaView>
  );
}

// --- ЭКРАН ЧАТОВ ---
function ChatsScreen({ user, onLogout, onChatSelect }) {
  const [chats, setChats] = useState([]);
  const [loading, setLoading] = useState(true);
  const [ws, setWs] = useState(null);

  useEffect(() => {
    connectWebSocket();
    loadChats();
    return () => { if (ws) ws.close(); };
  }, []);

  const connectWebSocket = () => {
    const socket = new WebSocket(`${WS_URL}/ws/${user.id}`);
    socket.onmessage = (event) => {
      const data = JSON.parse(event.data);
      if (data.type === 'message' || data.type === 'typing') {
        loadChats();
      }
    };
    socket.onopen = () => console.log('WebSocket connected');
    setWs(socket);
  };

  const loadChats = async () => {
    try {
      const res = await fetch(`${API_URL}/api/chats/${user.id}`);
      const data = await res.json();
      setChats(data);
    } catch (e) {
      console.error(e);
    }
    setLoading(false);
  };

  const renderChat = ({ item }) => (
    <TouchableOpacity style={styles.chatItem} onPress={() => onChatSelect(item)}>
      <View style={styles.avatar}>
        <Text style={styles.avatarText}>
          {(item.other_user?.name || item.name || 'U')[0].toUpperCase()}
        </Text>
      </View>
      <View style={styles.chatInfo}>
        <View style={styles.chatRow}>
          <Text style={styles.chatName}>{item.other_user?.name || item.name || 'Без имени'}</Text>
          <Text style={styles.chatTime}>
            {item.last_time ? new Date(item.last_time).toLocaleTimeString() : ''}
          </Text>
        </View>
        <View style={styles.chatRow}>
          <Text style={styles.chatLast} numberOfLines={1}>
            {item.last_message || 'Нет сообщений'}
          </Text>
          {item.unread > 0 && (
            <View style={styles.badge}>
              <Text style={styles.badgeText}>{item.unread}</Text>
            </View>
          )}
        </View>
      </View>
    </TouchableOpacity>
  );

  return (
    <SafeAreaView style={styles.safeArea}>
      <View style={styles.header}>
        <Text style={styles.headerTitle}>LOOM</Text>
        <TouchableOpacity onPress={onLogout}>
          <Text style={styles.headerButton}>Выйти</Text>
        </TouchableOpacity>
      </View>
      <FlatList
        data={chats}
        renderItem={renderChat}
        keyExtractor={item => item.id}
        refreshing={loading}
        onRefresh={loadChats}
        ListEmptyComponent={
          <Text style={styles.emptyText}>Нет чатов. Начните общение!</Text>
        }
      />
      <TouchableOpacity
        style={styles.fab}
        onPress={() => Alert.alert('Новый чат', 'Выберите контакт')}
      >
        <Text style={styles.fabText}>✏️</Text>
      </TouchableOpacity>
    </SafeAreaView>
  );
}

// --- ЭКРАН ЧАТА ---
function ChatScreen({ chat, user, onBack }) {
  const [messages, setMessages] = useState([]);
  const [text, setText] = useState('');
  const [ws, setWs] = useState(null);
  const [typing, setTyping] = useState(false);
  const flatListRef = useRef();

  useEffect(() => {
    connectWebSocket();
    loadMessages();
    return () => { if (ws) ws.close(); };
  }, []);

  const connectWebSocket = () => {
    const socket = new WebSocket(`${WS_URL}/ws/${user.id}`);
    socket.onmessage = (event) => {
      const data = JSON.parse(event.data);
      if (data.type === 'message') {
        setMessages(prev => [...prev, data]);
        flatListRef.current?.scrollToEnd();
      } else if (data.type === 'typing') {
        setTyping(data.is_typing);
      }
    };
    setWs(socket);
  };

  const loadMessages = async () => {
    try {
      const res = await fetch(`${API_URL}/api/messages/${chat.id}`);
      const data = await res.json();
      setMessages(data.reverse());
    } catch (e) {
      console.error(e);
    }
  };

  const sendMessage = async () => {
    if (!text.trim()) return;
    const msg = { type: 'message', chat_id: chat.id, text: text.trim() };
    if (ws) {
      ws.send(JSON.stringify(msg));
    }
    setText('');
  };

  const renderMessage = ({ item }) => {
    const isMine = item.sender_id === user.id;
    return (
      <View style={[styles.messageBubble, isMine ? styles.myMessage : styles.theirMessage]}>
        <Text style={styles.messageText}>{item.text}</Text>
        <Text style={styles.messageTime}>
          {new Date(item.created_at).toLocaleTimeString()}
        </Text>
      </View>
    );
  };

  return (
    <SafeAreaView style={styles.safeArea}>
      <View style={styles.chatHeader}>
        <TouchableOpacity onPress={onBack}>
          <Text style={styles.backButton}>←</Text>
        </TouchableOpacity>
        <Text style={styles.chatHeaderTitle}>
          {chat.other_user?.name || chat.name || 'Чат'}
        </Text>
        {typing && <Text style={styles.typingStatus}>печатает...</Text>}
      </View>
      <FlatList
        ref={flatListRef}
        data={messages}
        renderItem={renderMessage}
        keyExtractor={item => item.id}
        style={styles.messagesList}
        onContentSizeChange={() => flatListRef.current?.scrollToEnd()}
      />
      <View style={styles.inputContainer}>
        <TextInput
          style={styles.messageInput}
          placeholder="Сообщение..."
          placeholderTextColor="#666"
          value={text}
          onChangeText={t => {
            setText(t);
            if (ws && t.length > 0) {
              ws.send(JSON.stringify({ type: 'typing', chat_id: chat.id, is_typing: true }));
            }
          }}
        />
        <TouchableOpacity style={styles.sendButton} onPress={sendMessage}>
          <Text style={styles.sendButtonText}>➤</Text>
        </TouchableOpacity>
      </View>
    </SafeAreaView>
  );
}

// --- ГЛАВНОЕ ПРИЛОЖЕНИЕ ---
export default function App() {
  const [user, setUser] = useState(null);
  const [currentChat, setCurrentChat] = useState(null);

  if (!user) {
    return <LoginScreen onLogin={setUser} />;
  }

  if (currentChat) {
    return <ChatScreen chat={currentChat} user={user} onBack={() => setCurrentChat(null)} />;
  }

  return (
    <ChatsScreen
      user={user}
      onLogout={() => setUser(null)}
      onChatSelect={setCurrentChat}
    />
  );
}

// --- СТИЛИ ---
const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: '#0A0A0A', justifyContent: 'center' },
  loginBox: { padding: 30, alignItems: 'center' },
  logo: { fontSize: 48, color: '#4A90D9', fontWeight: 'bold' },
  slogan: { color: '#666', fontSize: 16, marginBottom: 30 },
  input: {
    width: '100%',
    backgroundColor: '#1A1A1A',
    color: '#FFF',
    padding: 15,
    borderRadius: 12,
    marginBottom: 15,
    borderWidth: 1,
    borderColor: '#333',
    fontSize: 16,
  },
  button: {
    width: '100%',
    backgroundColor: '#4A90D9',
    padding: 15,
    borderRadius: 12,
    alignItems: 'center',
  },
  buttonText: { color: '#FFF', fontSize: 18, fontWeight: '600' },
  link: { color: '#4A90D9', marginTop: 15, fontSize: 16 },
  safeArea: { flex: 1, backgroundColor: '#0A0A0A' },
  header: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    padding: 15,
    borderBottomWidth: 1,
    borderBottomColor: '#1A1A1A',
  },
  headerTitle: { fontSize: 22, fontWeight: 'bold', color: '#4A90D9' },
  headerButton: { color: '#4A90D9', fontSize: 16 },
  chatItem: {
    flexDirection: 'row',
    alignItems: 'center',
    padding: 15,
    borderBottomWidth: 1,
    borderBottomColor: '#1A1A1A',
  },
  avatar: {
    width: 50,
    height: 50,
    borderRadius: 25,
    backgroundColor: '#2A2A2A',
    justifyContent: 'center',
    alignItems: 'center',
    marginRight: 12,
  },
  avatarText: { fontSize: 20, color: '#FFF', fontWeight: '600' },
  chatInfo: { flex: 1 },
  chatRow: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center' },
  chatName: { fontSize: 16, fontWeight: '600', color: '#FFF' },
  chatTime: { fontSize: 12, color: '#666' },
  chatLast: { fontSize: 14, color: '#666', flex: 1, marginRight: 10 },
  badge: {
    backgroundColor: '#4A90D9',
    borderRadius: 12,
    minWidth: 24,
    height: 24,
    justifyContent: 'center',
    alignItems: 'center',
    paddingHorizontal: 6,
  },
  badgeText: { color: '#FFF', fontSize: 12, fontWeight: 'bold' },
  fab: {
    position: 'absolute',
    bottom: 30,
    right: 30,
    backgroundColor: '#4A90D9',
    width: 56,
    height: 56,
    borderRadius: 28,
    justifyContent: 'center',
    alignItems: 'center',
    elevation: 5,
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 2 },
    shadowOpacity: 0.3,
    shadowRadius: 4,
  },
  fabText: { fontSize: 24, color: '#FFF' },
  emptyText: { color: '#666', textAlign: 'center', marginTop: 50, fontSize: 16 },
  chatHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    padding: 15,
    borderBottomWidth: 1,
    borderBottomColor: '#1A1A1A',
  },
  backButton: { fontSize: 28, color: '#4A90D9', marginRight: 15 },
  chatHeaderTitle: { fontSize: 18, fontWeight: '600', color: '#FFF', flex: 1 },
  typingStatus: { color: '#4A90D9', fontSize: 12, marginLeft: 10 },
  messagesList: { flex: 1, padding: 15 },
  messageBubble: { maxWidth: '80%', padding: 12, borderRadius: 16, marginBottom: 8 },
  myMessage: {
    backgroundColor: '#4A90D9',
    alignSelf: 'flex-end',
    borderBottomRightRadius: 4,
  },
  theirMessage: {
    backgroundColor: '#1A1A1A',
    alignSelf: 'flex-start',
    borderBottomLeftRadius: 4,
  },
  messageText: { color: '#FFF', fontSize: 16 },
  messageTime: { color: '#888', fontSize: 10, marginTop: 4, alignSelf: 'flex-end' },
  inputContainer: {
    flexDirection: 'row',
    padding: 10,
    borderTopWidth: 1,
    borderTopColor: '#1A1A1A',
    backgroundColor: '#0A0A0A',
  },
  messageInput: {
    flex: 1,
    backgroundColor: '#1A1A1A',
    color: '#FFF',
    borderRadius: 20,
    paddingHorizontal: 15,
    paddingVertical: 10,
    fontSize: 16,
  },
  sendButton: {
    backgroundColor: '#4A90D9',
    width: 44,
    height: 44,
    borderRadius: 22,
    justifyContent: 'center',
    alignItems: 'center',
    marginLeft: 10,
  },
  sendButtonText: { color: '#FFF', fontSize: 20 },
});
