// src/pages/ConversationsPage.jsx
import React, { useState, useEffect, useCallback, useRef, useMemo } from 'react';
import { Link } from 'react-router-dom';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { ScrollArea } from "@/components/ui/scroll-area";
import { toast } from 'sonner';
import {
  FiSend, FiUser, FiUsers, FiMessageSquare, FiSearch, FiLoader, 
  FiAlertCircle, FiPaperclip, FiSmile, FiImage, FiList, FiMic, 
  FiVideo, FiFileText, FiMapPin, FiChevronRight
} from 'react-icons/fi';
import { formatDistanceToNow, parseISO } from 'date-fns';
import { motion } from 'framer-motion';

// API Configuration & Helper (Should be in a separate file like src/services/api.js)
const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000';

const getAuthToken = () => {
  try {
    return localStorage.getItem('accessToken');
  } catch (error) {
    console.error('Error accessing localStorage:', error);
    return null;
  }
};

async function apiCall(endpoint, method = 'GET', body = null, isPaginatedFallback = false) {
  const token = getAuthToken();
  const headers = {
    ...(!(body instanceof FormData) && { 'Content-Type': 'application/json' }),
    ...(token && { 'Authorization': `Bearer ${token}` }),
  };

  const config = { 
    method, 
    headers, 
    ...(body && { body: body instanceof FormData ? body : JSON.stringify(body) }) 
  };

  try {
    const response = await fetch(`${API_BASE_URL}${endpoint}`, config);
    
    if (!response.ok) {
      let errorData = { detail: `Request failed: ${response.status} ${response.statusText}` };
      try {
        const contentType = response.headers.get("content-type");
        if (contentType?.includes("application/json")) {
          errorData = await response.json();
        } else {
          errorData.detail = await response.text() || errorData.detail;
        }
      } catch (e) {
        console.error("Error parsing error response:", e);
      }
      
      const errorMessage = errorData.detail || 
        (typeof errorData === 'object' ? 
          Object.entries(errorData)
            .map(([k,v]) => `${k.replace(/_/g, " ")}: ${Array.isArray(v) ? v.join(', ') : String(v)}`)
            .join('; ') : 
          `API Error ${response.status}`);
      
      const err = new Error(errorMessage);
      err.data = errorData;
      throw err;
    }

    if (response.status === 204 || response.headers.get("content-length") === "0") {
      return isPaginatedFallback ? { results: [], count: 0, next: null, previous: null } : null;
    }

    const data = await response.json();
    
    return isPaginatedFallback ? {
      results: data.results || (Array.isArray(data) ? data : []),
      count: data.count ?? (Array.isArray(data) ? data.length : 0),
      next: data.next,
      previous: data.previous
    } : data;
  } catch (error) {
    console.error(`API call to ${method} ${endpoint} failed:`, error);
    if (!error.message?.includes("(toasted)")) {
      toast.error(error.message || 'An error occurred. Please try again.');
      error.message = (error.message || "") + " (toasted)";
    }
    throw error;
  }
}

const getMessageDisplayContent = (message) => {
  if (!message) return "Loading message...";

  // Text messages
  if (message.message_type === 'text' && message.text_content) {
    return message.text_content;
  }

  // Rich content payload
  if (message.content_payload) {
    const payload = message.content_payload;
    
    const typeComponents = {
      image: <span className="text-xs italic flex items-center gap-1"><FiImage/> Image {payload.image?.caption ? `- "${payload.image.caption}"` : (payload.image?.filename || '')}</span>,
      document: <span className="text-xs italic flex items-center gap-1"><FiPaperclip/> Document: {payload.document?.filename || "attachment"}</span>,
      audio: <span className="text-xs italic flex items-center gap-1"><FiMic/> Audio: {payload.audio?.filename || "track"}</span>,
      video: <span className="text-xs italic flex items-center gap-1"><FiVideo/> Video: {payload.video?.filename || (payload.video?.caption || "clip")}</span>,
      interactive: <span className="text-xs italic flex items-center gap-1"><FiList/> Interactive: {payload.type} {(payload.body?.text || "").substring(0,30)}...</span>
    };

    if (typeComponents[message.message_type]) {
      return typeComponents[message.message_type];
    }

    if (typeof payload === 'string') return payload;
  }
  
  // Fallback to content preview
  if (message.content_preview) {
    const iconMap = {
      image: <FiImage className="mr-1"/>,
      document: <FiPaperclip className="mr-1"/>,
      audio: <FiMic className="mr-1"/>,
      video: <FiVideo className="mr-1"/>,
      sticker: <FiSmile className="mr-1"/>,
      location: <FiMapPin className="mr-1"/>,
      contacts: <FiUsers className="mr-1"/>,
      interactive: <FiList className="mr-1"/>,
      button: <FiList className="mr-1"/>,
      system: <FiAlertCircle className="mr-1"/>
    };

    const icon = iconMap[message.message_type] || <FiFileText className="mr-1"/>;
    
    if (message.message_type === 'text') return message.content_preview;
    
    return (
      <span className="text-xs italic flex items-center gap-1">
        {icon}
        {message.content_preview}
      </span>
    );
  }

  return message.message_type_display || message.message_type || "Unsupported message type";
};

const MessageBubble = React.memo(({ message, contactName }) => {
  const isOutgoing = message.direction === 'out';
  const bubbleClass = isOutgoing
    ? 'bg-green-600 dark:bg-green-700 text-white rounded-tr-none'
    : 'bg-slate-100 dark:bg-slate-700 text-slate-800 dark:text-slate-100 rounded-tl-none';

  const content = getMessageDisplayContent(message);
  const timestamp = message.timestamp 
    ? formatDistanceToNow(parseISO(message.timestamp), { addSuffix: true })
    : (message.status === 'pending_upload' ? 'uploading...' : 'sending...');

  return (
    <motion.div
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.2 }}
      className={`flex flex-col my-1 ${isOutgoing ? 'items-end' : 'items-start'}`}
    >
      <div className={`max-w-[70%] md:max-w-[60%] px-3 py-2 rounded-xl shadow ${bubbleClass}`}>
        <p className="text-sm whitespace-pre-wrap">{content}</p>
        {message.status === 'failed' && message.error_details && (
          <p className="text-xs text-red-200 dark:text-red-300 mt-1">
            <FiAlertCircle className="inline mr-1 mb-0.5"/> 
            Failed: {message.error_details.detail || "Could not send."}
          </p>
        )}
      </div>
      <span className="text-xs text-slate-400 dark:text-slate-500 mt-0.5 px-1">
        {isOutgoing ? "You" : contactName || message.contact_details?.name}
        {' · '}
        {timestamp}
        {isOutgoing && message.status && !['pending', 'pending_upload'].includes(message.status) && (
          <span className="ml-1">({message.status_display || message.status})</span>
        )}
      </span>
    </motion.div>
  );
});

MessageBubble.displayName = 'MessageBubble';

const useDebounce = (value, delay) => {
  const [debouncedValue, setDebouncedValue] = useState(value);

  useEffect(() => {
    const handler = setTimeout(() => {
      setDebouncedValue(value);
    }, delay);

    return () => {
      clearTimeout(handler);
    };
  }, [value, delay]);

  return debouncedValue;
};

export default function ConversationsPage() {
  const [contacts, setContacts] = useState([]);
  const [selectedContact, setSelectedContact] = useState(null);
  const [messages, setMessages] = useState([]);
  const [newMessage, setNewMessage] = useState('');
  const [attachmentFile, setAttachmentFile] = useState(null);
  const [searchTerm, setSearchTerm] = useState('');
  const debouncedSearchTerm = useDebounce(searchTerm, 300);

  const [isLoadingContacts, setIsLoadingContacts] = useState(true);
  const [isLoadingMessages, setIsLoadingMessages] = useState(false);
  const [isSendingMessage, setIsSendingMessage] = useState(false);

  const messagesEndRef = useRef(null);
  const fileInputRef = useRef(null);
  const scrollAreaRef = useRef(null);

  // Fetch contacts with debounced search
  const fetchContacts = useCallback(async (search = '') => {
    setIsLoadingContacts(true);
    try {
      const endpoint = search 
        ? `/crm-api/conversations/contacts/?search=${encodeURIComponent(search)}` 
        : '/crm-api/conversations/contacts/';
      const data = await apiCall(endpoint, 'GET', null, true);
      setContacts(data.results || []);
    } finally {
      setIsLoadingContacts(false);
    }
  }, []);

  useEffect(() => {
    fetchContacts(debouncedSearchTerm);
  }, [debouncedSearchTerm, fetchContacts]);

  // Initial fetch
  useEffect(() => {
    fetchContacts();
  }, [fetchContacts]);

  // Fetch messages for selected contact
  const fetchMessagesForContact = useCallback(async (contactId) => {
    if (!contactId) return;
    
    setIsLoadingMessages(true);
    setMessages([]);
    
    try {
      const data = await apiCall(
        `/crm-api/conversations/contacts/${contactId}/messages/`, 
        'GET', 
        null, 
        true
      );
      setMessages((data.results || []).reverse());
    } finally {
      setIsLoadingMessages(false);
    }
  }, []);

  useEffect(() => {
    if (selectedContact) {
      fetchMessagesForContact(selectedContact.id);
    } else {
      setMessages([]);
    }
  }, [selectedContact, fetchMessagesForContact]);

  // Auto-scroll to bottom when messages change
  useEffect(() => {
    if (messages.length > 0 && scrollAreaRef.current) {
      const scrollElement = scrollAreaRef.current;
      scrollElement.scrollTo({
        top: scrollElement.scrollHeight,
        behavior: 'smooth'
      });
    }
  }, [messages]);

  const handleSelectContact = (contact) => {
    setSelectedContact(contact);
  };

  const handleFileSelect = (event) => {
    const file = event.target.files?.[0];
    if (!file) return;

    // Validate file size
    const maxSize = 16 * 1024 * 1024; // 16MB
    if (file.size > maxSize && (file.type.startsWith('image/') || file.type.startsWith('video/'))) {
      toast.error(`File is too large. Max size is ${maxSize / (1024 * 1024)}MB for this file type.`);
      event.target.value = '';
      return;
    }

    setAttachmentFile(file);
    toast.info(`Selected: ${file.name}. Add a caption (optional) and send.`);
  };

  const handleSendMessage = async (e) => {
    e.preventDefault();
    if ((!newMessage.trim() && !attachmentFile) || !selectedContact) return;

    setIsSendingMessage(true);
    const tempMessageId = `temp_${Date.now()}`;
    
    // Create optimistic message
    let optimisticMessage;
    let apiPayload;
    let isFormData = false;

    if (attachmentFile) {
      isFormData = true;
      let messageType = 'document';
      if (attachmentFile.type.startsWith('image/')) messageType = 'image';
      else if (attachmentFile.type.startsWith('video/')) messageType = 'video';
      else if (attachmentFile.type.startsWith('audio/')) messageType = 'audio';

      optimisticMessage = {
        id: tempMessageId,
        contact: selectedContact.id,
        direction: 'out',
        message_type: messageType,
        text_content: newMessage.trim() || attachmentFile.name,
        content_payload: {
          [messageType]: {
            filename: attachmentFile.name,
            caption: newMessage.trim() || undefined
          }
        },
        timestamp: new Date().toISOString(),
        status: 'pending_upload',
        contact_details: {
          name: selectedContact.name,
          whatsapp_id: selectedContact.whatsapp_id
        }
      };

      apiPayload = new FormData();
      apiPayload.append('contact_id', selectedContact.id);
      apiPayload.append('message_type', messageType);
      apiPayload.append('media_file', attachmentFile, attachmentFile.name);
      if (newMessage.trim()) {
        apiPayload.append('caption', newMessage.trim());
      }
    } else {
      optimisticMessage = {
        id: tempMessageId,
        contact: selectedContact.id,
        direction: 'out',
        message_type: 'text',
        text_content: newMessage,
        content_payload: { body: newMessage, preview_url: false },
        timestamp: new Date().toISOString(),
        status: 'pending',
        contact_details: {
          name: selectedContact.name,
          whatsapp_id: selectedContact.whatsapp_id
        }
      };
      
      apiPayload = {
        contact: selectedContact.id,
        message_type: 'text',
        content_payload: { body: newMessage, preview_url: false }
      };
    }

    // Update UI optimistically
    setMessages(prev => [...prev, optimisticMessage]);
    setNewMessage('');
    setAttachmentFile(null);
    if (fileInputRef.current) fileInputRef.current.value = '';

    try {
      const sentMessage = await apiCall(
        '/crm-api/conversations/messages/',
        'POST',
        apiPayload
      );

      // Replace optimistic message with actual response
      setMessages(prev => prev.map(msg => 
        msg.id === tempMessageId 
          ? { ...optimisticMessage, ...sentMessage, status: sentMessage.status || 'sent' } 
          : msg
      ));

      toast.success(`Message ${attachmentFile ? 'with attachment ' : ''}sent!`);
    } catch (error) {
      // Mark message as failed
      setMessages(prev => prev.map(msg => 
        msg.id === tempMessageId 
          ? { 
              ...msg, 
              status: 'failed', 
              error_details: { detail: error.message.replace(" (toasted)", "") } 
            } 
          : msg
      ));
    } finally {
      setIsSendingMessage(false);
    }
  };

  const handleSearchChange = (e) => {
    setSearchTerm(e.target.value);
  };

  const filteredContacts = useMemo(() => {
    return contacts.filter(contact => 
      contact.name?.toLowerCase().includes(searchTerm.toLowerCase()) ||
      contact.whatsapp_id?.toLowerCase().includes(searchTerm.toLowerCase())
    );
  }, [contacts, searchTerm]);

  return (
    <div className="flex h-[calc(100vh-var(--header-height,4rem)-2rem)] border dark:border-slate-700 rounded-lg shadow-md overflow-hidden">
      {/* Contacts Panel */}
      <div className="w-1/3 min-w-[280px] max-w-[400px] border-r dark:border-slate-700 flex flex-col bg-slate-50 dark:bg-slate-800/50">
        <div className="p-3 border-b dark:border-slate-700">
          <div className="relative">
            <FiSearch className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-slate-400" />
            <Input
              type="search"
              placeholder="Search contacts..."
              className="pl-9 dark:bg-slate-700 dark:border-slate-600"
              value={searchTerm}
              onChange={handleSearchChange}
            />
          </div>
        </div>
        
        <ScrollArea className="flex-1">
          {isLoadingContacts && contacts.length === 0 && (
            <div className="flex justify-center p-4">
              <FiLoader className="animate-spin h-5 w-5 text-slate-400" />
            </div>
          )}
          
          {!isLoadingContacts && filteredContacts.length === 0 && (
            <div className="p-4 text-center text-slate-500 dark:text-slate-400">
              {searchTerm ? 'No matching contacts found' : 'No contacts available'}
            </div>
          )}
          
          {filteredContacts.map(contact => (
            <motion.div
              key={contact.id}
              initial={{ opacity: 0, x: -10 }}
              animate={{ opacity: 1, x: 0 }}
              transition={{ duration: 0.2 }}
              onClick={() => handleSelectContact(contact)}
              className={`p-3 border-b dark:border-slate-700 cursor-pointer hover:bg-slate-100 dark:hover:bg-slate-700 transition-colors
                          ${selectedContact?.id === contact.id ? 'bg-blue-50 dark:bg-blue-900/30 border-l-4 border-blue-500 dark:border-blue-400' : ''}`}
            >
              <div className="flex items-center space-x-3">
                <Avatar className="h-10 w-10">
                  <AvatarImage 
                    src={`https://ui-avatars.com/api/?name=${encodeURIComponent(contact.name || contact.whatsapp_id)}&background=random`} 
                    alt={contact.name} 
                  />
                  <AvatarFallback>
                    {(contact.name || contact.whatsapp_id || 'U').substring(0, 2).toUpperCase()}
                  </AvatarFallback>
                </Avatar>
                <div className="flex-1 min-w-0">
                  <p className="font-medium truncate dark:text-slate-100">
                    {contact.name || contact.whatsapp_id}
                  </p>
                  <p className="text-xs text-slate-500 dark:text-slate-400 truncate">
                    {contact.whatsapp_id}
                    {contact.last_seen && ` · Last seen ${formatDistanceToNow(parseISO(contact.last_seen), { addSuffix: true })}`}
                  </p>
                </div>
                {contact.needs_human_intervention && (
                  <FiAlertCircle 
                    title="Needs Human Intervention" 
                    className="h-5 w-5 text-red-500 flex-shrink-0"
                  />
                )}
                <FiChevronRight className="text-slate-400" />
              </div>
            </motion.div>
          ))}
        </ScrollArea>
      </div>

      {/* Chat Panel */}
      <div className="flex-1 flex flex-col bg-white dark:bg-slate-900">
        {selectedContact ? (
          <>
            <div className="p-3 border-b dark:border-slate-700 flex items-center space-x-3">
              <Avatar>
                <AvatarImage 
                  src={`https://ui-avatars.com/api/?name=${encodeURIComponent(selectedContact.name || selectedContact.whatsapp_id)}&background=random`} 
                  alt={selectedContact.name} 
                />
                <AvatarFallback>
                  {(selectedContact.name || selectedContact.whatsapp_id || 'U').substring(0, 2).toUpperCase()}
                </AvatarFallback>
              </Avatar>
              <div>
                <h2 className="font-semibold dark:text-slate-50">
                  {selectedContact.name || selectedContact.whatsapp_id}
                </h2>
                <p className="text-xs text-slate-500 dark:text-slate-400">
                  {selectedContact.whatsapp_id}
                </p>
              </div>
            </div>

            <ScrollArea 
              ref={scrollAreaRef}
              className="flex-1 p-4 space-y-2 bg-slate-50/50 dark:bg-slate-800/30"
            >
              {isLoadingMessages && (
                <div className="text-center p-4">
                  <FiLoader className="animate-spin h-6 w-6 mx-auto my-3" />
                  <p>Loading messages...</p>
                </div>
              )}
              
              {!isLoadingMessages && messages.length === 0 && (
                <p className="text-center text-sm text-slate-500 dark:text-slate-400 py-10">
                  No messages with this contact yet. Start the conversation!
                </p>
              )}
              
              {messages.map(msg => (
                <MessageBubble 
                  key={msg.id} 
                  message={msg} 
                  contactName={selectedContact.name} 
                />
              ))}
              
              <div ref={messagesEndRef} />
            </ScrollArea>

            <form 
              onSubmit={handleSendMessage} 
              className="p-3 border-t dark:border-slate-700 flex items-center space-x-2 bg-slate-50 dark:bg-slate-800"
            >
              <Button 
                variant="ghost" 
                size="icon" 
                type="button" 
                className="dark:text-slate-400 disabled:opacity-50" 
                title="Emoji (coming soon)" 
                disabled
              >
                <FiSmile className="h-5 w-5"/>
              </Button>
              
              <Button 
                variant="ghost" 
                size="icon" 
                type="button" 
                className="dark:text-slate-400"
                title="Attach file"
                onClick={() => fileInputRef.current?.click()}
              >
                <FiPaperclip className="h-5 w-5"/>
              </Button>
              
              <input 
                type="file" 
                ref={fileInputRef} 
                style={{ display: 'none' }} 
                onChange={handleFileSelect} 
                accept="image/*, video/*, audio/*, .pdf, .doc, .docx, .xls, .xlsx"
              />
              
              <Input
                type="text"
                value={newMessage}
                onChange={(e) => setNewMessage(e.target.value)}
                placeholder={attachmentFile ? `Caption for ${attachmentFile.name}... (optional)` : "Type a message..."}
                className="flex-1 dark:bg-slate-700 dark:border-slate-600"
                autoComplete="off"
              />
              
              <Button 
                type="submit" 
                disabled={isSendingMessage || (!newMessage.trim() && !attachmentFile)} 
                className="bg-green-600 hover:bg-green-700 dark:bg-green-500 dark:hover:bg-green-600 text-white"
              >
                {isSendingMessage ? (
                  <FiLoader className="animate-spin h-4 w-4" />
                ) : (
                  <FiSend className="h-4 w-4" />
                )}
                <span className="ml-2 hidden sm:inline">Send</span>
              </Button>
            </form>
          </>
        ) : (
          <div className="flex-1 flex flex-col items-center justify-center text-slate-500 dark:text-slate-400 p-10 text-center">
            <FiMessageSquare className="h-24 w-24 mb-4 text-slate-300 dark:text-slate-600" />
            <p className="text-lg">Select a contact to view messages</p>
            <p className="text-sm">Or search for a contact to start a new conversation</p>
          </div>
        )}
      </div>
    </div>
  );
}