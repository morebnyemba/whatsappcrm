// src/components/bot_builder/nodes/MessageNode.jsx
import React from 'react';
import { Handle, Position } from 'reactflow';
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { Textarea } from '@/components/ui/textarea';
import { Label } from '@/components/ui/label';
import { FiMessageSquare } from 'react-icons/fi';

// Assuming these styles are defined in a shared location or passed as props
const nodeBaseStyle = "border-2 shadow-lg rounded-lg w-72 dark:bg-slate-800 dark:border-slate-700 text-slate-900 dark:text-slate-50";
const nodeHeaderStyle = "p-3 border-b dark:border-slate-700 flex items-center justify-between";
const nodeTitleStyle = "font-semibold text-sm";
const nodeContentStyle = "p-3 space-y-2";
const nodeInputStyle = "w-full p-2 text-sm border border-slate-300 dark:border-slate-600 rounded-md bg-slate-50 dark:bg-slate-700 focus:ring-green-500 focus:border-green-500";
const nodeHandleStyle = (type) => `!w-3 !h-3 !bg-green-500 dark:!bg-green-400 !border-2 !border-white dark:!border-slate-800 !rounded-full ${type === 'source' ? '!right-[-7px]' : '!left-[-7px]'}`;

const MessageNode = ({ id, data, selected }) => {
  // data.onChange should be: (nodeId, fieldPath, value) => void
  const handleChange = (e) => {
    // Assuming the simple case where data.message is directly updated.
    // For structured config, it would be 'config.text.body'
    data.onChange(id, 'config.text.body', e.target.value); 
    // Or if data.message is the primary store for this node's text:
    // data.onChange(id, 'message', e.target.value); 
  };

  const messageValue = data.config?.text?.body || data.message || '';


  return (
    <Card className={`${nodeBaseStyle} ${selected ? 'border-green-600 dark:border-green-500' : 'border-slate-400 dark:border-slate-700'}`}>
      <CardHeader className={`${nodeHeaderStyle} bg-green-100 dark:bg-green-900/50`}>
        <div className="flex items-center gap-2"><FiMessageSquare className="h-5 w-5 text-green-700 dark:text-green-400" /><CardTitle className={nodeTitleStyle}>{data.name || 'Send Message'}</CardTitle></div>
      </CardHeader>
      <CardContent className={nodeContentStyle}>
        <Label htmlFor={`msg-body-${id}`} className="text-xs dark:text-slate-300">Message Text:</Label>
        <Textarea
          id={`msg-body-${id}`}
          value={messageValue}
          onChange={handleChange}
          className={nodeInputStyle}
          placeholder="Hello {{ contact.name }}!"
          rows={2}
        />
        <p className="text-xs text-slate-500 dark:text-slate-400">
          Type: {data.config?.message_type || 'text'}. Click node to configure advanced options in panel.
        </p>
      </CardContent>
      <Handle type="target" position={Position.Left} id={`${id}-in`} className={nodeHandleStyle('target')} />
      <Handle type="source" position={Position.Right} id={`${id}-out`} className={nodeHandleStyle('source')} />
    </Card>
  );
};

export default MessageNode;