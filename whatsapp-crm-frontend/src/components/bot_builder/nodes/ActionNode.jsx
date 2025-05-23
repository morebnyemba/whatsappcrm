// src/components/bot_builder/nodes/ActionNode.jsx
import React from 'react';
import { Handle, Position } from 'reactflow';
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { Textarea } from '@/components/ui/textarea';
import { Label } from '@/components/ui/label';
import { FiTerminal } from 'react-icons/fi';

const nodeBaseStyle = "border-2 shadow-lg rounded-lg w-72 dark:bg-slate-800 dark:border-slate-700 text-slate-900 dark:text-slate-50";
const nodeHeaderStyle = "p-3 border-b dark:border-slate-700 flex items-center justify-between";
const nodeTitleStyle = "font-semibold text-sm";
const nodeContentStyle = "p-3 space-y-3";
const nodeInputStyle = "w-full p-2 text-sm border border-slate-300 dark:border-slate-600 rounded-md bg-slate-50 dark:bg-slate-700 focus:ring-purple-500 focus:border-purple-500 font-mono";
const nodeHandleStyle = (type) => `!w-3 !h-3 !bg-purple-500 dark:!bg-purple-400 !border-2 !border-white dark:!border-slate-800 !rounded-full ${type === 'source' ? '!right-[-7px]' : '!left-[-7px]'}`;

const ActionNode = ({ id, data, selected }) => {
  // data.config structure for action:
  // { actions_to_run: [{ action_type: '...', ... }] }
  // data.actionConfig was a simplification. We'll use data.config.actions_to_run

  const actionsConfigString = useMemo(() => {
    try {
      return JSON.stringify(data.config?.actions_to_run || [], null, 2);
    } catch (e) {
      return "[]"; // Default to empty array string if error
    }
  }, [data.config?.actions_to_run]);

  const handleChange = (jsonString) => {
    try {
      const parsedJson = JSON.parse(jsonString);
      // Basic validation: ensure it's an array
      if (Array.isArray(parsedJson)) {
        data.onChange(id, 'config', { ...data.config, actions_to_run: parsedJson });
      } else {
        // Or handle error, e.g., by not updating or showing a validation message in UI
        console.warn("Action config must be an array.");
        // To reflect invalid input, you might store the raw string temporarily
        // data.onChange(id, 'rawActionConfigString', jsonString); 
        // And then validate before save. For now, only update if valid array.
      }
    } catch (e) {
      console.warn("Invalid JSON for action config:", e);
      // Handle invalid JSON, maybe store raw string for user to fix
      // data.onChange(id, 'rawActionConfigString', jsonString);
    }
  };

  return (
    <Card className={`${nodeBaseStyle} ${selected ? 'border-purple-500 dark:border-purple-400' : 'border-slate-400 dark:border-slate-700'}`}>
      <CardHeader className={`${nodeHeaderStyle} bg-purple-100 dark:bg-purple-900/50`}>
        <div className="flex items-center gap-2">
          <FiTerminal className="h-5 w-5 text-purple-600 dark:text-purple-400" />
          <CardTitle className={nodeTitleStyle}>Perform Action</CardTitle>
        </div>
      </CardHeader>
      <CardContent className={nodeContentStyle}>
        <Label htmlFor={`action-config-${id}`} className="text-xs dark:text-slate-300">
          Actions Configuration (JSON Array):
        </Label>
        <Textarea
          id={`action-config-${id}`}
          value={actionsConfigString}
          onChange={(e) => handleChange(e.target.value)}
          className={nodeInputStyle}
          placeholder='[{"action_type": "set_context_variable", ...}]'
          rows={5}
        />
         {/* TODO: Implement UI to build complex action_config JSON via a modal (e.g., add/remove actions, select types) */}
        <p className="text-xs text-slate-500 dark:text-slate-400 mt-1">
            Click to edit actions (e.g., update contact, set variable).
        </p>
      </CardContent>
      <Handle type="target" position={Position.Left} id={`${id}-in`} className={nodeHandleStyle('target')} />
      <Handle type="source" position={Position.Right} id={`${id}-out`} className={nodeHandleStyle('source')} />
    </Card>
  );
};

export default ActionNode;