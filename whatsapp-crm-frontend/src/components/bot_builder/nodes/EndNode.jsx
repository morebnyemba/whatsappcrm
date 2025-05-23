// src/components/bot_builder/nodes/EndNode.jsx
import React from 'react';
import { Handle, Position } from 'reactflow';
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { FiChevronsRight } from 'react-icons/fi';

const nodeBaseStyle = "border-2 shadow-lg rounded-lg w-48 dark:bg-slate-800 dark:border-slate-700 text-slate-900 dark:text-slate-50";
const nodeHeaderStyle = "p-3 border-b dark:border-slate-700 flex items-center justify-center";
const nodeTitleStyle = "font-semibold text-sm";
const nodeHandleStyle = (type) => `!w-3 !h-3 !bg-green-500 dark:!bg-green-400 !border-2 !border-white dark:!border-slate-800 !rounded-full ${type === 'source' ? '!right-[-7px]' : '!left-[-7px]'}`;

const EndNode = ({ selected }) => {
  return (
    <Card className={`${nodeBaseStyle} ${selected ? 'border-red-500 dark:border-red-400' : 'border-slate-400 dark:border-slate-700'}`}>
      <CardHeader className={`${nodeHeaderStyle} bg-red-100 dark:bg-red-900/50`}>
        <div className="flex items-center gap-2">
          <FiChevronsRight className="h-5 w-5 text-red-600 dark:text-red-400" />
          <CardTitle className={nodeTitleStyle}>Flow End</CardTitle>
        </div>
      </CardHeader>
      <CardContent className="p-3 text-center">
        <p className="text-xs text-slate-500 dark:text-slate-400">End of a flow path.</p>
      </CardContent>
      <Handle type="target" position={Position.Left} id="in" className={nodeHandleStyle('target')} />
    </Card>
  );
};

export default EndNode;