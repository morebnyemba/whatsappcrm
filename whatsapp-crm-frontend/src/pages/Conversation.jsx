// src/pages/ConversationsPage.jsx
import React, { useState, useEffect, useCallback, useRef } from 'react';
import { Link } from 'react-router-dom'; // If you need to link to contact details page
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Card, CardHeader, CardTitle, CardDescription, CardContent, CardFooter } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { toast } from 'sonner';
import {
  FiSend, FiUser, FiUsers, FiMessageSquare, FiSearch, FiLoader, FiAlertCircle, FiPaperclip, FiSmile
} from 'react-icons/fi';
import { formatDistanceToNow, parseISO } from 'date-fns'; // For relative timestamps

// --- API Configuration & Helper (Should be in a shared service file) ---
const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000';
const getAuthToken = () => localStorage.getItem('accessToken');

async function apiCall(endpoint, method = 'GET', body = null, isPaginatedFallback = false) {
  const token = getAuthToken();
  const headers = {
    ...(!body || !(body instanceof FormData) && { 'Content-Type': 'application/json' }),
    ...(token && { 'Authorization': `Bearer ${token}` }),
  };
  const config = { method, headers, ...(body && !(body instanceof FormData) && { body: JSON.stringify(body) }) };
  try {
    const response = await fetch(`${API_BASE_URL}${endpoint}`, config);
    if (!response.ok) {
      let errorData = { detail: `Request to ${endpoint} failed: ${response.status} ${response.statusText}` };
      try {
        const contentType = response.headers.get("content-type");
        if (contentType && contentType.indexOf("application/json") !== -1) { errorData = await response.json(); }
        else { errorData.detail = (await response.text()) || errorData.detail; }
      } catch (e) { console.error("Failed to parse error response:", e); }
      const errorMessage = errorData.detail || 
                           (typeof errorData === 'object' && errorData !== null && !errorData.detail ? 
                             Object.entries(errorData).map(([k,v])=>`${k.replace(/_/g, " ")}: ${Array.isArray(v) ? v.join(', ') : String(v)}`).join('; ') : 
                             `API Error ${response.status}`);
      const err = new Error(errorMessage); err.data = errorData; err.isApiError = true; throw err;
    }
    if (response.status === 204 || (response.headers.get("content-length") || "0") === "0") {
      return isPaginatedFallback ? { results: [], count: 0, next: null, previous: null } : null;
    }
    const data = await response.json();
    return isPaginatedFallback ? { 
      results: data.results || (Array.isArray(data) ? data : []), 
      count: data.count === undefined ? (Array.isArray(data) ? data.length : 0) : data.count,
      next: data.next,
      previous: data.previous
    } : data;
  } catch (error) {
    console.error(`API call to ${method} ${API_BASE_URL}${endpoint} failed:`, error);
    if (!error.isApiError || !error.message.includes("(toasted)")) {
        toast.error(error.message || 'An API error occurred. Check console.');
        error.message = (error.message || "") + " (toasted)";
    }
    throw error;
  }
}


const MessageBubble = ({ message, contactName }) => {
  const isOutgoing = message.direction === 'out';
  const alignClass = isOutgoing ? 'items-end' : 'items-start';
  const bubbleClass = isOutgoing 
    ? 'bg-green-600 dark:bg-green-700 text-white rounded-tr-none' 
    : 'bg-slate-100 dark:bg-slate-700 text-slate-800 dark:text-slate-100 rounded-tl-none';
  
  let content = message.text_content || "Unsupported message type";
  if (message.message_type !== 'text' && message.content_payload) {
      if (message.message_type === 'image' && message.content_payload.image) {
          content = <span className="text-xs italic flex items-center gap-1"><FiImage/> Image {message.content_payload.image.caption ? `- "${message.content_payload.image.caption}"` : ''}</span>;
      } else if (message.message_type === 'document' && message.content_payload.document) {
          content = <span className="text-xs italic flex items-center gap-1"><FiPaperclip/> Document: {message.content_payload.document.filename || "attachment"}</span>;
      } else if (message.message_type === 'interactive' && message.content_payload.type) {
          content = <span className="text-xs italic flex items-center gap-1"><FiList/> Interactive: {message.content_payload.type}</span>;
      }
      // TODO: Add more specific previews for other message types
  }


  return (
    <div className={`flex flex-col my-1 ${alignClass}`}>
      <div className={`max-w-[70%] md:max-w-[60%] px-3 py-2 rounded-xl shadow ${bubbleClass}`}>
        <p className="text-sm whitespace-pre-wrap">{content}</p>
      </div>
      <span className="text-xs text-slate-400 dark:text-slate-500 mt-0.5 px-1">
        {isOutgoing ? "You" : contactName || message.contact_details?.name }
        {' · '}
        {message.timestamp ? formatDistanceToNow(parseISO(message.timestamp), { addSuffix: true }) : 'sending...'}
        {isOutgoing && message.status && message.status !== 'pending' && (
            <span className="ml-1 text-xs">({message.status_display || message.status})</span>
        )}
      </span>
    </div>
  );
};

export default function ConversationsPage() {
  const [contacts, setContacts] = useState([]);
  const [selectedContact, setSelectedContact] = useState(null); // { id, name, whatsapp_id }
  const [messages, setMessages] = useState([]);
  const [newMessage, setNewMessage] = useState('');
  
  const [isLoadingContacts, setIsLoadingContacts] = useState(true);
  const [isLoadingMessages, setIsLoadingMessages] = useState(false);
  const [isSendingMessage, setIsSendingMessage] = useState(false);
  
  const [searchTerm, setSearchTerm] = useState('');
  const messagesEndRef = useRef(null); // To scroll to bottom of messages

  const fetchContacts = useCallback(async (search = '') => {
    setIsLoadingContacts(true);
    try {
      const endpoint = search ? `/crm-api/conversations/contacts/?search=${encodeURIComponent(search)}` : '/crm-api/conversations/contacts/';
      const data = await apiCall(endpoint, 'GET', null, true);
      setContacts(data.results || []);
    } catch (error) {
      toast.error("Failed to fetch contacts.");
    } finally {
      setIsLoadingContacts(false);
    }
  }, []);

  useEffect(() => {
    fetchContacts();
  }, [fetchContacts]);

  const fetchMessagesForContact = useCallback(async (contactId) => {
    if (!contactId) return;
    setIsLoadingMessages(true);
    setMessages([]); // Clear previous messages
    try {
      // Using the custom action from ContactViewSet: /crm-api/conversations/contacts/{pk}/messages/
      const data = await apiCall(`/crm-api/conversations/contacts/${contactId}/messages/`, 'GET', null, true);
      setMessages((data.results || []).reverse()); // API returns newest first, reverse for display
    } catch (error) {
      toast.error("Failed to fetch messages for this contact.");
    } finally {
      setIsLoadingMessages(false);
    }
  }, []);

  useEffect(() => {
    if (selectedContact) {
      fetchMessagesForContact(selectedContact.id);
    }
  }, [selectedContact, fetchMessagesForContact]);

  // Scroll to bottom when messages change
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);


  const handleSelectContact = (contact) => {
    setSelectedContact(contact);
  };

  const handleSendMessage = async (e) => {
    e.preventDefault();
    if (!newMessage.trim() || !selectedContact) return;

    setIsSendingMessage(true);
    const tempMessageId = `temp_${Date.now()}`; // For optimistic update

    // Optimistic UI update
    const optimisticMessage = {
        id: tempMessageId,
        contact: selectedContact.id,
        direction: 'out',
        message_type: 'text',
        text_content: newMessage,
        content_payload: { body: newMessage, preview_url: false }, // Structure for text message
        timestamp: new Date().toISOString(),
        status: 'pending',
    };
    setMessages(prev => [...prev, optimisticMessage]);
    setNewMessage('');

    try {
      const payload = {
        contact: selectedContact.id, // Send contact PK
        message_type: 'text', // For now, only sending text messages from here
        content_payload: { body: optimisticMessage.text_content, preview_url: false },
        // Backend will set direction and initial status
      };
      const sentMessage = await apiCall('/crm-api/conversations/messages/', 'POST', payload);
      
      // Replace optimistic message with actual message from server
      setMessages(prev => prev.map(msg => msg.id === tempMessageId ? {...sentMessage, timestamp: sentMessage.timestamp || optimisticMessage.timestamp} : msg));
      toast.success("Message submitted for sending!");

    } catch (error) {
      toast.error(`Failed to send message: ${error.message}`);
      // Revert optimistic update or mark as failed
      setMessages(prev => prev.map(msg => msg.id === tempMessageId ? {...msg, status: 'failed', error_details: {detail: error.message} } : msg));
    } finally {
      setIsSendingMessage(false);
    }
  };

  const handleSearchChange = (e) => {
    setSearchTerm(e.target.value);
    // Optional: Debounce this call
    fetchContacts(e.target.value);
  };

  return (
    <div className="flex h-[calc(100vh-var(--header-height,4rem)-2rem)] border dark:border-slate-700 rounded-lg shadow-md overflow-hidden"> {/* Adjust height based on your header */}
      {/* Contacts List Panel */}
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
            <div className="p-4 text-center text-sm text-slate-500 dark:text-slate-400">
              <FiLoader className="animate-spin h-6 w-6 mx-auto my-3" /> Loading contacts...
            </div>
          )}
          {!isLoadingContacts && contacts.length === 0 && (
            <div className="p-4 text-center text-sm text-slate-500 dark:text-slate-400">No contacts found.</div>
          )}
          {contacts.map(contact => (
            <div
              key={contact.id}
              onClick={() => handleSelectContact(contact)}
              className={`p-3 border-b dark:border-slate-700 cursor-pointer hover:bg-slate-100 dark:hover:bg-slate-700 transition-colors
                          ${selectedContact?.id === contact.id ? 'bg-blue-50 dark:bg-blue-900/30 border-l-4 border-blue-500 dark:border-blue-400' : ''}`}
            >
              <div className="flex items-center space-x-3">
                <Avatar className="h-10 w-10">
                  <AvatarImage src={`https://ui-avatars.com/api/?name=${encodeURIComponent(contact.name || contact.whatsapp_id)}&background=random`} alt={contact.name} />
                  <AvatarFallback>{(contact.name || contact.whatsapp_id || 'U').substring(0,2).toUpperCase()}</AvatarFallback>
                </Avatar>
                <div className="flex-1 min-w-0">
                  <p className="font-medium truncate dark:text-slate-100">{contact.name || contact.whatsapp_id}</p>
                  <p className="text-xs text-slate-500 dark:text-slate-400 truncate">
                    {contact.whatsapp_id} - Last seen: {contact.last_seen ? formatDistanceToNow(parseISO(contact.last_seen), { addSuffix: true }) : 'N/A'}
                  </p>
                </div>
                {contact.needs_human_intervention && (
                    <FiAlertCircle title="Needs Human Intervention" className="h-5 w-5 text-red-500 flex-shrink-0"/>
                )}
              </div>
            </div>
          ))}
        </ScrollArea>
      </div>

      {/* Message Display and Input Panel */}
      <div className="flex-1 flex flex-col bg-white dark:bg-slate-900">
        {selectedContact ? (
          <>
            <div className="p-3 border-b dark:border-slate-700 flex items-center space-x-3">
              <Avatar>
                <AvatarImage src={`https://ui-avatars.com/api/?name=${encodeURIComponent(selectedContact.name || selectedContact.whatsapp_id)}&background=random`} alt={selectedContact.name} />
                <AvatarFallback>{(selectedContact.name || selectedContact.whatsapp_id || 'U').substring(0,2).toUpperCase()}</AvatarFallback>
              </Avatar>
              <div>
                <h2 className="font-semibold dark:text-slate-50">{selectedContact.name || selectedContact.whatsapp_id}</h2>
                <p className="text-xs text-slate-500 dark:text-slate-400">{selectedContact.whatsapp_id}</p>
              </div>
              {/* TODO: Add link to full contact profile/details page */}
            </div>
            
            <ScrollArea className="flex-1 p-4 space-y-2 bg-slate-50/50 dark:bg-slate-800/30">
              {isLoadingMessages && <div className="text-center p-4"><FiLoader className="animate-spin h-6 w-6 mx-auto my-3" /> Loading messages...</div>}
              {!isLoadingMessages && messages.length === 0 && <p className="text-center text-sm text-slate-500 dark:text-slate-400 py-10">No messages with this contact yet. Start the conversation!</p>}
              {messages.map(msg => (
                <MessageBubble key={msg.id} message={msg} contactName={selectedContact.name} />
              ))}
              <div ref={messagesEndRef} /> {/* Anchor to scroll to */}
            </ScrollArea>

            <form onSubmit={handleSendMessage} className="p-3 border-t dark:border-slate-700 flex items-center space-x-2 bg-slate-50 dark:bg-slate-800">
              {/* TODO: Add emoji picker, attachment button */}
              {/* <Button variant="ghost" size="icon" type="button" className="dark:text-slate-400"><FiSmile className="h-5 w-5"/></Button> */}
              {/* <Button variant="ghost" size="icon" type="button" className="dark:text-slate-400"><FiPaperclip className="h-5 w-5"/></Button> */}
              <Input
                type="text"
                value={newMessage}
                onChange={(e) => setNewMessage(e.target.value)}
                placeholder="Type a message..."
                className="flex-1 dark:bg-slate-700 dark:border-slate-600"
                autoComplete="off"
              />
              <Button type="submit" disabled={isSendingMessage || !newMessage.trim()} className="bg-green-600 hover:bg-green-700 dark:bg-green-500 dark:hover:bg-green-600 text-white">
                {isSendingMessage ? <FiLoader className="animate-spin h-4 w-4" /> : <FiSend className="h-4 w-4" />}
                <span className="ml-2 hidden sm:inline">Send</span>
              </Button>
            </form>
          </>
        ) : (
          <div className="flex-1 flex flex-col items-center justify-center text-slate-500 dark:text-slate-400 p-10 text-center">
            <FiMessageSquare className="h-24 w-24 mb-4 text-slate-300 dark:text-slate-600" />
            <p className="text-lg">Select a contact to view messages.</p>
            <p className="text-sm">Or search for a contact to start a new conversation.</p>
          </div>
        )}
      </div>
    </div>
  );
}