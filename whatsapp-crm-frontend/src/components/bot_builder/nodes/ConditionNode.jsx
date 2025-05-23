// src/components/bot_builder/nodes/ConditionNode.jsx
import React from 'react';
import { Handle, Position } from 'reactflow';
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { FiGitBranch } from 'react-icons/fi';

const nodeBaseStyle = "border-2 shadow-lg rounded-lg w-72 dark:bg-slate-800 dark:border-slate-700 text-slate-900 dark:text-slate-50";
const nodeHeaderStyle = "p-3 border-b dark:border-slate-700 flex items-center justify-between";
const nodeTitleStyle = "font-semibold text-sm";
const nodeContentStyle = "p-3 space-y-3";
const nodeInputStyle = "w-full p-2 text-sm border border-slate-300 dark:border-slate-600 rounded-md bg-slate-50 dark:bg-slate-700 focus:ring-yellow-500 focus:border-yellow-500";
const nodeHandleStyle = (type) => `!w-3 !h-3 !bg-yellow-500 dark:!bg-yellow-400 !border-2 !border-white dark:!border-slate-800 !rounded-full ${type === 'source' ? '!right-[-7px]' : '!left-[-7px]'}`;

const ConditionNode = ({ id, data, selected }) => {
  // data.config structure for condition:
  // { type: 'variable_equals', variable_name: '...', value: '...' }
  // For simplicity in this node, we might just edit a representative string or open a modal.
  // Here, data.condition was a simplification for direct editing.
  // The real config would be more structured, e.g., data.config.condition_logic or data.config itself
  
  // Assuming data.config.condition_logic holds the string for the condition
  const conditionLogic = data.config?.condition_logic || data.condition || ''; // Fallback to data.condition if it exists

  const handleChange = (value) => {
    // This should update data.config.condition_logic or a similar structured field
    // It's better to update the specific part of the config.
    data.onChange(id, 'config', { ...data.config, condition_logic: value });
  };

  return (
    <Card className={`${nodeBaseStyle} ${selected ? 'border-yellow-500 dark:border-yellow-400' : 'border-slate-400 dark:border-slate-700'}`}>
      <CardHeader className={`${nodeHeaderStyle} bg-yellow-100 dark:bg-yellow-900/50`}>
        <div className="flex items-center gap-2">
          <FiGitBranch className="h-5 w-5 text-yellow-600 dark:text-yellow-400" />
          <CardTitle className={nodeTitleStyle}>Condition</CardTitle>
        </div>
      </CardHeader>
      <CardContent className={nodeContentStyle}>
        <Label htmlFor={`condition-logic-${id}`} className="text-xs dark:text-slate-300">
          {/* MODIFIED LINE: Text content wrapped in {' '} */}
          {'Condition Logic (e.g., `{{flow_context.var}} == "value"`):'}
        </Label>
        <Input
          id={`condition-logic-${id}`}
          value={conditionLogic}
          onChange={(e) => handleChange(e.target.value)}
          className={nodeInputStyle}
          placeholder='e.g., context.user_choice == "yes"'
        />
        {/* TODO: Implement UI to build complex condition_config JSON via a modal */}
        <p className="text-xs text-slate-500 dark:text-slate-400 mt-1">
            Click to edit full condition (type, variable, value, etc.). Use 'out-true' and 'out-false' handles.
        </p>
      </CardContent>
      <Handle type="target" position={Position.Left} id={`${id}-in`} className={nodeHandleStyle('target')} />
      <Handle type="source" position={Position.Right} id={`${id}-out-true`} style={{ top: '30%' }} className={nodeHandleStyle('source')} />
      <Handle type="source" position={Position.Right} id={`${id}-out-false`} style={{ top: '70%' }} className={nodeHandleStyle('source')} />
    </Card>
  );
};

export default ConditionNode;