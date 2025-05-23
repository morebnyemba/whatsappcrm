// src/components/bot_builder/NodeConfigPanel.jsx (Conceptual - Needs full implementation)
import React from 'react';
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Label } from "@/components/ui/label";
import { FiSettings, FiX } from 'react-icons/fi';

// You'll need to import your MediaAsset selector components, interactive builders etc. here

export default function NodeConfigPanel({ node, onNodeDataChange, onClose }) {
  if (!node) return null;

  const handleInputChange = (fieldPath, value) => {
    // node.data.onChange is now (nodeId, fieldPath, value)
    // We already have nodeId (it's node.id), so we call the passed onNodeDataChange
    onNodeDataChange(node.id, fieldPath, value);
  };
  
  const handleConfigChange = (configField, value) => {
    onNodeDataChange(node.id, `config.${configField}`, value);
  };

  // This is where you build specific forms based on node.type
  const renderConfigFields = () => {
    switch (node.type) {
      case 'message':
        return (
          <>
            <div>
              <Label htmlFor={`node-name-${node.id}`} className="text-xs">Node Name</Label>
              <Input id={`node-name-${node.id}`} value={node.data.name || ''} onChange={(e) => handleInputChange('name', e.target.value)} />
            </div>
            <div>
              <Label htmlFor={`msg-type-${node.id}`} className="text-xs">Message Type (e.g., text, image)</Label>
              <Input id={`msg-type-${node.id}`} value={node.data.config?.message_type || 'text'} onChange={(e) => handleConfigChange('message_type', e.target.value)} />
            </div>
            {node.data.config?.message_type === 'text' && (
              <div>
                <Label htmlFor={`msg-body-${node.id}`} className="text-xs">Body</Label>
                <Textarea id={`msg-body-${node.id}`} value={node.data.config?.text?.body || ''} onChange={(e) => handleConfigChange('text.body', e.target.value)} rows={3} />
              </div>
            )}
            {/* TODO: Add UI for image (media asset selector), interactive, template configs */}
            {/* For image: Call an API to get MediaAssets, show selector, on select, call handleConfigChange('image.id', selected_whatsapp_media_id) */}

          </>
        );
      case 'condition':
        return (
          <>
            <div>
                <Label htmlFor={`node-name-${node.id}`} className="text-xs">Node Name</Label>
                <Input id={`node-name-${node.id}`} value={node.data.name || ''} onChange={(e) => handleInputChange('name', e.target.value)} />
            </div>
            <div>
              <Label htmlFor={`cond-logic-${node.id}`} className="text-xs">Condition Logic Expression</Label>
              <Input id={`cond-logic-${node.id}`} value={node.data.config?.condition_logic || ''} onChange={(e) => handleConfigChange('condition_logic', e.target.value)} />
            </div>
          </>
        );
      case 'action':
         return (
          <>
            <div>
                <Label htmlFor={`node-name-${node.id}`} className="text-xs">Node Name</Label>
                <Input id={`node-name-${node.id}`} value={node.data.name || ''} onChange={(e) => handleInputChange('name', e.target.value)} />
            </div>
            <div>
              <Label htmlFor={`act-config-json-${node.id}`} className="text-xs">Actions (JSON array)</Label>
              <Textarea
                id={`act-config-json-${node.id}`}
                value={typeof node.data.config?.actions_to_run === 'string' ? node.data.config.actions_to_run : JSON.stringify(node.data.config?.actions_to_run || [], null, 2)}
                onChange={(e) => {
                    let val = e.target.value;
                    // Try to parse, if not valid JSON, keep as string for user to continue editing
                    try { val = JSON.parse(e.target.value); } catch (err) { /* no-op */ }
                    handleConfigChange('actions_to_run', val);
                }}
                rows={6}
                className="font-mono text-xs"
              />
            </div>
          </>
        );
      case 'start':
      case 'end':
         return (
            <div>
                <Label htmlFor={`node-name-${node.id}`} className="text-xs">Node Name</Label>
                <Input id={`node-name-${node.id}`} value={node.data.name || (node.type === 'start' ? 'Flow Start' : 'Flow End')} onChange={(e) => handleInputChange('name', e.target.value)} />
            </div>
         );
      default:
        return <p className="text-xs text-slate-500">No specific configuration for this node type, or not yet implemented.</p>;
    }
  };

  return (
    <Card className="w-80 dark:bg-slate-800 dark:border-slate-700 text-slate-900 dark:text-slate-50">
      <CardHeader className="flex flex-row items-center justify-between">
        <div className="flex items-center gap-2">
            <FiSettings className="h-5 w-5 text-blue-500" />
            <CardTitle className="text-base">{node.data?.name || `Configure ${node.type}`}</CardTitle>
        </div>
        <Button variant="ghost" size="icon" onClick={onClose} className="h-7 w-7 dark:text-slate-400 dark:hover:bg-slate-700">
            <FiX className="h-4 w-4"/>
        </Button>
      </CardHeader>
      <CardContent className="space-y-4 text-sm">
        {renderConfigFields()}
      </CardContent>
    </Card>
  );
}