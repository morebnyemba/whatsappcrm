import { useState, useEffect, useRef } from 'react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Skeleton } from '@/components/ui/skeleton'
import { 
  FiSend, 
  FiPaperclip, 
  FiSmile, 
  FiCheckCircle, 
  FiCheck, 
  FiArrowLeft 
} from 'react-icons/fi'
import { FaSpinner } from 'react-icons/fa'
import { Picker } from 'emoji-mart'
import { 
  Dialog,
  DialogContent,
  DialogTitle
} from '@/components/ui/dialog'

const MAX_FILE_SIZE = 5 * 1024 * 1024;
const ALLOWED_FILE_TYPES = [
  'image/jpeg',
  'image/png',
  'image/gif',
  'application/pdf',
  'text/plain'
];

const MessageSkeleton = () => (
  <div className="flex gap-3 items-start p-3">
    <Skeleton className="h-8 w-8 rounded-full" />
    <div className="space-y-2">
      <Skeleton className="h-4 w-[200px]" />
      <Skeleton className="h-4 w-[150px]" />
    </div>
  </div>
);

const MessageStatus = ({ status }) => {
  switch (status) {
    case 'sending':
      return <FaSpinner className="animate-spin h-3 w-3 ml-1" />;
    case 'sent':
      return <FiCheck className="h-3 w-3 ml-1" />;
    case 'delivered':
      return <FiCheckCircle className="h-3 w-3 ml-1" />;
    default:
      return null;
  }
};

const FilePreview = ({ file, onRemove }) => {
  const isImage = file.type.startsWith('image/');
  const previewUrl = isImage ? URL.createObjectURL(file) : null;
  
  useEffect(() => {
    if (previewUrl) {
      return () => URL.revokeObjectURL(previewUrl);
    }
  }, [previewUrl]);

  return (
    <div className="mt-2 p-2 border rounded flex items-center gap-2 bg-muted/30">
      {isImage ? (
        <img src={previewUrl} alt={file.name} className="h-12 w-12 object-cover rounded" />
      ) : (
        <div className="h-12 w-12 flex items-center justify-center bg-muted rounded">
          📄
        </div>
      )}
      <div className="flex-1 truncate">
        <p className="text-xs font-medium truncate">{file.name}</p>
        <p className="text-xs text-muted-foreground">
          {(file.size / 1024).toFixed(1)} KB
        </p>
      </div>
      <Button 
        variant="ghost" 
        size="sm" 
        onClick={onRemove}
        className="h-6 w-6 p-0 rounded-full"
      >
        ✕
      </Button>
    </div>
  );
};

export default function Conversation() {
  const [selectedConversationId, setSelectedConversationId] = useState(null)
  const [conversations, setConversations] = useState([
    {
      id: 1,
      name: 'John Doe',
      lastMessage: 'Hello!',
      timestamp: new Date(),
      unread: 2,
      messages: [
        { id: 1, text: 'Hello!', direction: 'in', timestamp: new Date() },
        { 
          id: 2, 
          text: 'Hi there!', 
          direction: 'out', 
          timestamp: new Date(),
          status: 'delivered'
        }
      ]
    },
    {
      id: 2,
      name: 'Jane Smith',
      lastMessage: 'How are you?',
      timestamp: new Date(Date.now() - 3600000),
      unread: 0,
      messages: [
        { id: 3, text: 'How are you?', direction: 'in', timestamp: new Date(Date.now() - 3600000) }
      ]
    }
  ])
  const [messages, setMessages] = useState([])
  const [newMessage, setNewMessage] = useState('')
  const [loading, setLoading] = useState(true)
  const [showEmojiPicker, setShowEmojiPicker] = useState(false)
  const [file, setFile] = useState(null)
  const [fileError, setFileError] = useState('')
  const [showFileError, setShowFileError] = useState(false)

  const messagesEndRef = useRef(null)
  const inputRef = useRef(null)
  const fileInputRef = useRef(null)

  useEffect(() => {
    if (selectedConversationId) {
      setLoading(true)
      setTimeout(() => {
        const conversation = conversations.find(c => c.id === selectedConversationId)
        setMessages(conversation?.messages || [])
        setLoading(false)
      }, 1500)
    }
  }, [selectedConversationId])

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  useEffect(() => {
    return () => {
      messages.forEach(msg => {
        if (msg.fileUrl) {
          URL.revokeObjectURL(msg.fileUrl);
        }
      });
    };
  }, [messages]);

  const validateFile = (file) => {
    if (!file) return true;
    
    if (file.size > MAX_FILE_SIZE) {
      setFileError(`File is too large. Maximum size is ${MAX_FILE_SIZE / (1024 * 1024)}MB.`);
      return false;
    }
    
    if (!ALLOWED_FILE_TYPES.includes(file.type)) {
      setFileError('Invalid file type. Allowed types: JPEG, PNG, GIF, PDF, TXT');
      return false;
    }
    
    return true;
  };

  const handleSend = () => {
    if (!newMessage.trim() && !file) return;

    if (file && !validateFile(file)) {
      setShowFileError(true);
      return;
    }

    const newMsg = {
      id: Date.now(),
      text: newMessage.trim(),
      direction: 'out',
      timestamp: new Date(),
      status: 'sending',
      file: file ? file : null,
      fileUrl: file ? URL.createObjectURL(file) : null,
      fileName: file ? file.name : null
    }

    setMessages(prev => [...prev, newMsg])
    setConversations(prev => prev.map(conv => {
      if (conv.id === selectedConversationId) {
        return {
          ...conv,
          lastMessage: newMsg.text,
          timestamp: new Date(),
          unread: 0,
          messages: [...conv.messages, newMsg]
        }
      }
      return conv
    }))
    setNewMessage('')
    setFile(null)
    setShowEmojiPicker(false)

    setTimeout(() => {
      setMessages(prev => 
        prev.map(msg => 
          msg.id === newMsg.id ? { ...msg, status: 'sent' } : msg
        )
      );
      
      setTimeout(() => {
        setMessages(prev => 
          prev.map(msg => 
            msg.id === newMsg.id ? { ...msg, status: 'delivered' } : msg
          )
        );
      }, 1000);
    }, 800);
  }

  const handleEmojiSelect = (emoji) => {
    setNewMessage((prev) => prev + emoji.native)
    inputRef.current?.focus();
  }

  const handleFileChange = (e) => {
    if (e.target.files.length) {
      const selectedFile = e.target.files[0];
      if (validateFile(selectedFile)) {
        setFile(selectedFile);
        setFileError('');
      } else {
        setShowFileError(true);
        e.target.value = '';
      }
    }
  }

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  const handleClickOutside = (e) => {
    if (showEmojiPicker && !e.target.closest('.emoji-picker-container')) {
      setShowEmojiPicker(false);
    }
  };

  useEffect(() => {
    document.addEventListener('click', handleClickOutside);
    return () => {
      document.removeEventListener('click', handleClickOutside);
    };
  }, [showEmojiPicker]);

  if (!selectedConversationId) {
    return (
      <div className="h-screen flex flex-col bg-background">
        <div className="flex-1 overflow-y-auto px-4 py-3">
          {conversations.map(convo => (
            <div
              key={convo.id}
              onClick={() => setSelectedConversationId(convo.id)}
              className="p-4 border-b cursor-pointer hover:bg-muted/50"
            >
              <div className="flex justify-between items-start">
                <h3 className="font-medium">{convo.name}</h3>
                {convo.unread > 0 && (
                  <span className="bg-primary text-primary-foreground rounded-full px-2 py-1 text-xs">
                    {convo.unread}
                  </span>
                )}
              </div>
              <p className="text-sm text-muted-foreground truncate">{convo.lastMessage}</p>
              <p className="text-xs text-muted-foreground mt-1">
                {convo.timestamp.toLocaleDateString()}
              </p>
            </div>
          ))}
        </div>
      </div>
    )
  }

  const selectedConversation = conversations.find(c => c.id === selectedConversationId)

  return (
    <div className="h-screen flex flex-col bg-background border rounded-none sm:rounded-lg">
      <div className="border-b p-4 flex items-center gap-4">
        <Button 
          variant="ghost" 
          size="icon" 
          onClick={() => setSelectedConversationId(null)}
          className="sm:hidden"
        >
          <FiArrowLeft />
        </Button>
        <h2 className="text-lg font-semibold">{selectedConversation?.name}</h2>
      </div>

      <div className="flex-1 overflow-y-auto px-4 py-3 space-y-3 sm:px-6 sm:py-4">
        {loading ? (
          <>
            <MessageSkeleton />
            <MessageSkeleton />
          </>
        ) : (
          messages.map((msg) => (
            <div
              key={msg.id}
              className={`w-full flex ${
                msg.direction === 'in' ? 'justify-start' : 'justify-end'
              }`}
            >
              <div className="max-w-[80%] sm:max-w-[60%] flex flex-col gap-1">
                <div
                  className={`px-4 py-2 rounded-xl text-sm shadow-sm break-words ${
                    msg.direction === 'in'
                      ? 'bg-muted text-foreground'
                      : 'bg-primary text-primary-foreground'
                  }`}
                >
                  {msg.text}
                  {msg.fileUrl && (
                    <div className="mt-2">
                      {msg.file?.type.startsWith('image/') ? (
                        <img 
                          src={msg.fileUrl} 
                          alt={msg.fileName} 
                          className="max-w-full rounded mt-1 max-h-40 object-contain"
                        />
                      ) : (
                        <a
                          href={msg.fileUrl}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="underline text-xs flex items-center gap-1"
                        >
                          📎 {msg.fileName}
                        </a>
                      )}
                    </div>
                  )}
                </div>
                <div className={`text-xs text-muted-foreground flex items-center ${
                  msg.direction === 'in' ? 'justify-start' : 'justify-end'
                }`}>
                  <span>{msg.timestamp.toLocaleTimeString()}</span>
                  {msg.direction === 'out' && <MessageStatus status={msg.status} />}
                </div>
              </div>
            </div>
          ))
        )}
        <div ref={messagesEndRef} />
      </div>

      <div className="border-t px-4 py-3 bg-background relative">
        {file && (
          <FilePreview file={file} onRemove={() => setFile(null)} />
        )}
        
        {showEmojiPicker && (
          <div className="absolute bottom-20 left-4 z-50 emoji-picker-container">
            <Picker onSelect={handleEmojiSelect} theme="light" />
          </div>
        )}

        <form
          onSubmit={(e) => {
            e.preventDefault()
            handleSend()
          }}
          className="flex items-center gap-2"
        >
          <Button
            type="button"
            variant="ghost"
            size="icon"
            onClick={() => setShowEmojiPicker(!showEmojiPicker)}
            className="text-muted-foreground"
          >
            <FiSmile />
          </Button>

          <label
            htmlFor="file-upload"
            className="cursor-pointer text-muted-foreground"
          >
            <FiPaperclip />
            <input
              type="file"
              id="file-upload"
              onChange={handleFileChange}
              className="hidden"
              ref={fileInputRef}
            />
          </label>

          <Input
            value={newMessage}
            onChange={(e) => setNewMessage(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Type a message... (Shift+Enter for new line)"
            className="flex-1"
            ref={inputRef}
          />
          <Button type="submit">
            <FiSend className="mr-1 h-4 w-4" />
            Send
          </Button>
        </form>
      </div>
      
      <Dialog open={showFileError} onOpenChange={setShowFileError}>
        <DialogContent>
          <DialogTitle>File Error</DialogTitle>
          <div className="py-4">
            <p className="text-destructive">{fileError}</p>
          </div>
          <div className="flex justify-end">
            <Button onClick={() => setShowFileError(false)}>
              Close
            </Button>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  )
}